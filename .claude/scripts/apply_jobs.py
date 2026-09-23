"""Apply approved jobs - the step that actually performs the effect.

The ledger separates DECIDING from DOING. `approved` records that the owner said
yes; nothing has happened to the filesystem yet. This script walks approved jobs,
calls the job module's apply(), and moves each to `completed`.

They are separate on purpose. Approving 489 files is two clicks and must feel
instant; copying 489 files is slow I/O that would time out an HTTP request. It
also means a failed copy leaves the approval intact and retryable, rather than
losing the decision.

  python .claude/scripts/apply_jobs.py --dry-run    # show what would be filed
  python .claude/scripts/apply_jobs.py              # file everything approved
  python .claude/scripts/apply_jobs.py --kinds triage.classify --max 50

Every job kind copies rather than moves, and records a reversal row in its own
manifest, so this is undoable.

Approving from /ops or the ledger CLI spawns this script detached, so an
approval files itself within seconds instead of waiting for the next Agent Day.
That makes concurrent runs normal rather than exceptional, and apply() is not
idempotent - a second pass over the same job writes a second wiki page and, for
admin.schedule_proposal, inserts a second calendar event. So every call to a job
module's apply() happens under APPLY_LOCK, and the approved queue is read *after*
the lock is held, so a run that waited still sees jobs approved while it waited.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jobs as job_registry  # noqa: E402
import ledger  # noqa: E402
from shared import REPO_ROOT, STATE_DIR, file_lock, log_line  # noqa: E402

# Serializes every apply() in the system, across processes: this script, the
# capture cycle, and Agent Day's drain.
APPLY_LOCK = STATE_DIR / "apply-jobs"

# Generous on purpose. A blocked run is a *detached background* run, so waiting
# costs nothing, and giving up would strand the approval until the next Agent
# Day - the exact failure this automation exists to remove.
APPLY_LOCK_TIMEOUT = 600.0


def _arg(name, default=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def apply_one(job: dict) -> tuple[bool, object]:
    mod = job_registry.get(job.get("kind"))
    if mod is None:
        return False, f"no job module for kind {job.get('kind')!r}"
    if not hasattr(mod, "apply"):
        return True, "no apply() - nothing to do"

    # The approved payload is whatever the runtime proposed and they reviewed.
    result = job.get("proposal")
    if result is None:
        result = job.get("result")
    if result is None:
        return False, "approved job has no proposal to apply"

    try:
        outcome = mod.apply(job, result)
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    return True, outcome if isinstance(outcome, dict) else "applied"


def spawn_background() -> None:
    """Launch a detached apply run. Never raises - the caller is a state change.

    Used by the approve paths. Approving must stay instant (approving 489 files
    is two clicks; copying them is slow I/O), so the effect runs out-of-band.
    If the spawn fails, the job simply stays `approved` and Agent Day files it,
    which is the pre-automation behaviour - degraded, never wrong.
    """
    import subprocess
    try:
        kwargs = {"cwd": str(REPO_ROOT), "stdout": subprocess.DEVNULL,
                  "stderr": subprocess.DEVNULL, "stdin": subprocess.DEVNULL}
        if sys.platform == "win32":
            kwargs["creationflags"] = (
                subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS)
        else:
            kwargs["start_new_session"] = True
        # sys.executable, not a configured path: the child needs exactly the
        # interpreter whose site-packages this parent is already running under.
        subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--max", "200"],
            **kwargs)
    except Exception as e:  # noqa: BLE001 - best-effort by design
        log_line("apply", f"background spawn failed: {type(e).__name__}: {e}")


def _run_batch(kinds, limit) -> int:
    approved = [j for j in ledger.query(status="approved")
                if not kinds or j.get("kind") in kinds]
    if limit:
        approved = approved[:limit]
    if not approved:
        print("nothing approved and waiting")
        return 0

    ok = failed = 0
    for job in approved:
        success, msg = apply_one(job)
        if success:
            # Folder creation supersedes the first classification and enqueues
            # a second pass; prepare_folder_reclassification already recorded
            # that terminal transition, so do not complete it again.
            if not (isinstance(msg, dict)
                    and msg.get("reclassificationJobId")):
                ledger.complete(job["job"], {"applied": True, "detail": msg})
            ok += 1
        else:
            # Fail non-retryably: the decision stands, but the effect needs a
            # human look. Re-approving a failed job would not help by itself.
            ledger.fail(job["job"], f"apply failed: {msg}", retryable=False)
            failed += 1
            log_line("apply", f"{job['job']}: {msg}")

    print(f"applied {ok}, failed {failed}")
    if failed:
        print("see .claude/data/logs/apply.log")
    return 0 if failed == 0 else 1


def main() -> int:
    dry = "--dry-run" in sys.argv
    kinds = None
    if _arg("--kinds"):
        kinds = {k.strip() for k in _arg("--kinds").split(",") if k.strip()}
    limit = int(_arg("--max")) if _arg("--max") else None

    if dry:
        # Read-only: takes no lock, so a preview never blocks a real run.
        from collections import Counter
        approved = [j for j in ledger.query(status="approved")
                    if not kinds or j.get("kind") in kinds]
        if limit:
            approved = approved[:limit]
        if not approved:
            print("nothing approved and waiting")
            return 0
        c = Counter()
        for j in approved:
            p = j.get("proposal") or {}
            c[f"{p.get('vault')}/{p.get('bucket')}"] += 1
        print(f"would apply {len(approved)} jobs:")
        for k, v in c.most_common():
            print(f"  {v:5d}  {k}")
        return 0

    try:
        with file_lock(APPLY_LOCK, timeout=APPLY_LOCK_TIMEOUT):
            return _run_batch(kinds, limit)
    except TimeoutError:
        # The holder re-reads the approved queue, so it will most likely file
        # these jobs itself. Agent Day is the backstop either way.
        log_line("apply", "skipped: another apply run held the lock")
        print("another apply run is in progress")
        return 0


if __name__ == "__main__":
    sys.exit(main())
