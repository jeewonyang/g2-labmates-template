"""Run one captured thought through local triage, verification, and apply.

The web capture path launches this script detached after persisting the inbox
item and ledger job. It prioritizes only that known job; scheduled Agent Day
still drains the general FIFO queue. A process lock prevents concurrent model
runs from contending for the local GPU.

  python .claude/scripts/automation_cycle.py --capture-job <ledger-id>
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import apply_jobs  # noqa: E402
import capture_sync  # noqa: E402
import dispatch  # noqa: E402
import ledger  # noqa: E402
from shared import STATE_DIR, file_lock, log_line  # noqa: E402
from triage import review as review_flow  # noqa: E402

os.environ.setdefault("CLAUDE_INVOKED_BY", "capture-automation")
LOCK = STATE_DIR / "capture-automation-cycle"


def _arg(name: str, default=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def run_capture(job_id: str, reclassification_depth: int = 0) -> int:
    worker = f"capture-cycle-{os.getpid()}"
    source = ledger.get(job_id)
    if not source:
        log_line("capture-automation", f"source job not found: {job_id}")
        return 1

    if source.get("status") == "created":
        claimed = ledger.claim_job(job_id, worker)
        if claimed:
            dispatch.run_one(claimed)
    source = ledger.get(job_id)
    if not source:
        return 1
    if source.get("status") == "failed":
        capture_sync.record_failure(source, source.get("error", "local triage failed"))
        return 1

    if source.get("status") == "needs_review" and not source.get("reviewed_by"):
        auditable = review_flow._resolve_protected([source])
        source = ledger.get(job_id) or source
        if auditable:
            # A fresh capture never waits behind the historical review backlog.
            review_id = ledger.create(
                "triage.review",
                {"items": [review_flow.build_review_item(source)]},
                runtime=review_flow.triage_review.DEFAULT_RUNTIME,
                sensitivity="internal",
                parent=job_id,
            )
            automation_id = (source.get("payload") or {}).get("automationId")
            if automation_id:
                capture_sync.record_verifier_queued(automation_id, review_id)
            claimed = ledger.claim_job(review_id, worker)
            if claimed:
                status = dispatch.run_one(claimed)
                if status == "failed":
                    failed = ledger.get(review_id) or claimed
                    capture_sync.record_failure(
                        source, failed.get("error", "verification failed"))
                    return 1

    # Consume every completed audit safely; source status guards make this
    # idempotent even if a scheduled cycle reaches the same review.
    argv = sys.argv
    sys.argv = ["review.py", "process"]
    try:
        review_flow.cmd_process()
    finally:
        sys.argv = argv

    source = ledger.get(job_id)
    if not source:
        return 1
    if source.get("status") == "superseded":
        replacement = source.get("replacement_job")
        if replacement and reclassification_depth < 2:
            return run_capture(replacement, reclassification_depth + 1)
        return 0
    if source.get("status") == "approved":
        # Under the global apply lock, not just the capture lock: a manual
        # approval on /ops now spawns apply_jobs.py at any moment, and it would
        # otherwise pick up this same approved job and apply it twice.
        #
        # The terminal transition is inside the lock too. Releasing between
        # apply() and complete() would leave the job `approved` in the ledger
        # with its effect already performed - precisely the window a concurrent
        # run reads. The recursion is deliberately left outside: run_capture
        # takes this lock again, and it is not reentrant.
        with file_lock(apply_jobs.APPLY_LOCK,
                       timeout=apply_jobs.APPLY_LOCK_TIMEOUT):
            ok, message = apply_jobs.apply_one(source)
            reclass = (message.get("reclassificationJobId")
                       if ok and isinstance(message, dict) else None)
            if ok and not reclass:
                ledger.complete(job_id, {"applied": True, "detail": message})
            elif not ok:
                ledger.fail(job_id, f"apply failed: {message}", retryable=False)
        if ok:
            if reclass:
                return run_capture(reclass, reclassification_depth + 1)
            return 0
        capture_sync.record_failure(source, message)
        return 1

    # Only deliberate taxonomy changes (such as a brand-new project folder)
    # remain in needs_review.
    return 0


def main() -> int:
    job_id = _arg("--capture-job")
    if not job_id:
        print("usage: automation_cycle.py --capture-job <ledger-id>")
        return 2
    try:
        with file_lock(LOCK, timeout=1.0):
            return run_capture(job_id)
    except TimeoutError:
        # Another capture cycle owns the GPU. The job remains durable and the
        # scheduled Agent Day fallback will pick it up.
        log_line("capture-automation",
                 f"deferred {job_id}: another automation cycle is active")
        return 0
    except Exception as exc:
        source = ledger.get(job_id)
        if source:
            capture_sync.record_failure(source, repr(exc))
        log_line("capture-automation", f"{job_id}: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
