"""Retry explicit failed Agent OS jobs with append-only provenance.

Each failed job gets a new child job carrying the same kind, payload, runtime,
and declared sensitivity. The current dispatcher re-evaluates sensitivity, so
fixed routing policy applies to the replacement. The original failure is
resolved only after its replacement completes or reaches needs_review.

Usage:
  python .claude/scripts/retry_failures.py <job-id> [<job-id> ...]
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import dispatch  # noqa: E402
import jobs as job_registry  # noqa: E402
import ledger  # noqa: E402
from shared import STATE_DIR, atomic_write_json, now  # noqa: E402

STATE_FILE = STATE_DIR / "retry-failures-state.json"


def _write_state(status: str, results: list[dict], **extra) -> None:
    atomic_write_json(
        STATE_FILE,
        {
            "status": status,
            "updatedAt": now().isoformat(timespec="seconds"),
            "results": results,
            **extra,
        },
    )


def retry(job_ids: list[str]) -> list[dict]:
    worker = f"retry-failures-{os.getpid()}"
    results: list[dict] = []
    _write_state("running", results, requested=job_ids)

    for old_id in job_ids:
        old = ledger.get(old_id)
        if not old or old.get("status") != "failed":
            results.append(
                {
                    "original": old_id,
                    "status": "skipped",
                    "reason": "job is missing or no longer failed",
                },
            )
            _write_state("running", results, requested=job_ids)
            continue

        module = job_registry.get(old.get("kind"))
        current_runtime = (
            getattr(module, "DEFAULT_RUNTIME", None)
            if module is not None
            else None
        )
        retry_runtime = current_runtime or old.get("runtime")
        if module is not None and hasattr(module, "retry_runtime"):
            try:
                retry_runtime = (
                    module.retry_runtime(
                        old.get("runtime") or retry_runtime,
                        old.get("error") or "",
                    )
                    or retry_runtime
                )
            except Exception:
                # Retry routing is advisory. The dispatcher still applies the
                # authoritative sensitivity guard to the selected runtime.
                pass

        replacement = ledger.create(
            old.get("kind"),
            old.get("payload"),
            # A retry should use the repaired job configuration rather than
            # blindly preserving the runtime that caused the failure. A job
            # may also skip straight to its guarded fallback when the recorded
            # error already proves the primary provider cannot serve it.
            runtime=retry_runtime,
            sensitivity=old.get("sensitivity", "private"),
            parent=old_id,
        )
        row = {
            "original": old_id,
            "replacement": replacement,
            "kind": old.get("kind"),
            "status": "created",
        }
        results.append(row)
        _write_state("running", results, requested=job_ids)

        claimed = ledger.claim_job(replacement, worker)
        if not claimed:
            row["status"] = "failed"
            row["reason"] = "replacement could not be claimed"
            _write_state("running", results, requested=job_ids)
            continue

        outcome = dispatch.run_one(claimed)
        replacement_state = ledger.get(replacement) or {}
        row["status"] = outcome
        if replacement_state.get("error"):
            row["reason"] = replacement_state["error"]

        if outcome in {"completed", "needs_review"}:
            ancestor_id = old_id
            while ancestor_id:
                ancestor = ledger.get(ancestor_id) or {}
                if ancestor.get("status") == "failed":
                    ledger.resolve(
                        ancestor_id,
                        by="retry-failures",
                        note=f"replacement reached {outcome}",
                        replacement=replacement,
                    )
                ancestor_id = ancestor.get("parent")
            row["originalStatus"] = "resolved"
        _write_state("running", results, requested=job_ids)

    failed = [row for row in results if row.get("status") == "failed"]
    _write_state(
        "failed" if failed else "completed",
        results,
        requested=job_ids,
        finishedAt=now().isoformat(timespec="seconds"),
    )
    return results


def main() -> int:
    job_ids = [arg for arg in sys.argv[1:] if not arg.startswith("-")]
    if not job_ids:
        print("usage: retry_failures.py <failed-job-id> [<failed-job-id> ...]")
        return 2
    results = retry(job_ids)
    for row in results:
        print(
            f"{row.get('kind', 'job')}: {row.get('original')} -> "
            f"{row.get('replacement', '-')} [{row.get('status')}]",
        )
    return 1 if any(row.get("status") == "failed" for row in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
