"""Append-only job ledger - the coordination substrate for the Agent OS.

Any process (Claude Code, Codex, a dispatcher worker, the dashboard) can enqueue
work here, claim it exactly once, and record the outcome. Agents never call each
other; they claim jobs, read and write files, and append events.

Event-sourced: `.claude/data/ledger/events.jsonl` holds one JSON object per line
and is never rewritten. Current state is a fold over the events, cached in
`snapshot.json` with the byte offset folded to, so a long ledger stays fast.
This matches the never-delete rule and gives a free audit trail.

State machine:

    created --claim--> claimed --+--> completed          (terminal)
       ^                         +--> failed             (terminal, re-enqueueable)
       |                         +--> cancelled          (terminal)
       +---- defer (not_before) -+--> needs_review --+--> approved --> completed
       +---- cancel                                  +--> rejected   (terminal)

`deferred` (2026-09-16) sends a claimed job back to `created` with a
`not_before` timestamp that `claim()` honours: the dispatcher uses it when a
cloud subscription window is spent, so the job waits for the reset instead of
failing, and the next scheduled drain after that time picks it up. Nothing
sleeps; the ledger just declines to hand the job out early.

`needs_review` is the Advisor-mode gate. Any job whose effect reaches outside
VAULT/Memory/ - filing a document into the vault, creating a Gmail draft,
editing source - must land there, never `completed`, until a human approves it.
Jobs confined to agent-owned state may complete directly.

CLI:
  python .claude/scripts/ledger.py create <kind> <payload-json> [--runtime R] [--sensitivity S]
  python .claude/scripts/ledger.py list [--status S] [--kind K] [--limit N] [--json]
  python .claude/scripts/ledger.py show <job_id> [--json]
  python .claude/scripts/ledger.py approve <job_id> [--by NAME] [--no-apply]
  python .claude/scripts/ledger.py reject <job_id> <reason> [--by NAME]
  python .claude/scripts/ledger.py cancel <job_id> [--reason TEXT] [--by NAME]
  python .claude/scripts/ledger.py reap [--older-than-min N]
  python .claude/scripts/ledger.py stats [--json]
"""

import json
import os
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shared import DATA, file_lock, log_line, now  # noqa: E402

LEDGER_DIR = DATA / "ledger"
EVENTS = LEDGER_DIR / "events.jsonl"
SNAPSHOT = LEDGER_DIR / "snapshot.json"

# Fold at most this many events past the snapshot before rewriting it.
SNAPSHOT_EVERY = 500
# A claimed job with no terminal event after this long is considered abandoned.
STALE_CLAIM_SECONDS = 30 * 60

TERMINAL = {
    "completed", "failed", "rejected", "superseded", "resolved", "cancelled",
}
VALID_SENSITIVITY = {"private", "internal"}

# Fail closed: an unknown or missing sensitivity is treated as private, which
# the dispatcher may only route to a local runtime.
DEFAULT_SENSITIVITY = "private"


class LedgerError(RuntimeError):
    pass


def _ensure_dirs() -> None:
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)


def new_job_id() -> str:
    """Sortable, collision-free without coordination. No extra dependency.

    Microsecond precision, not milliseconds: at ms resolution a burst of
    create() calls lands in the same tick and the random suffix decides sort
    order, which silently broke FIFO. Ordering still must not be *relied* on
    from the id alone - claim() walks the fold in event-log order, which is the
    real ground truth. This just keeps ids meaningfully sortable for humans.
    """
    return f"{int(time.time() * 1_000_000):016d}-{uuid.uuid4().hex[:8]}"


def _append(event: dict) -> None:
    _ensure_dirs()
    line = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    with open(EVENTS, "a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()
        os.fsync(f.fileno())


def _apply_event(jobs: dict, ev: dict) -> None:
    """Fold one event into the job-state map."""
    jid = ev.get("job")
    if not jid:
        return
    kind = ev.get("event")
    if kind == "created":
        jobs[jid] = {
            "job": jid,
            "kind": ev.get("kind"),
            "payload": ev.get("payload"),
            "runtime": ev.get("runtime"),
            "sensitivity": ev.get("sensitivity", DEFAULT_SENSITIVITY),
            "parent": ev.get("parent"),
            "status": "created",
            "created_ts": ev.get("ts"),
            "updated_ts": ev.get("ts"),
            "worker": None,
            "attempts": 0,
        }
        return
    job = jobs.get(jid)
    if job is None:
        return  # event for an unknown job (truncated history) - ignore
    job["updated_ts"] = ev.get("ts")
    if kind == "claimed":
        job["status"] = "claimed"
        job["worker"] = ev.get("worker")
        job["claimed_ts"] = ev.get("ts")
        job["attempts"] = job.get("attempts", 0) + 1
        job.pop("not_before", None)
    elif kind == "released":
        job["status"] = "created"
        job["worker"] = None
        job.pop("claimed_ts", None)
    elif kind == "deferred":
        # Back in the queue, but not claimable before `not_before`. The
        # reason and count stay on the job so /ops can say "waiting for the
        # Claude window to reset at 10pm" rather than a bare "queued".
        job["status"] = "created"
        job["worker"] = None
        job.pop("claimed_ts", None)
        job["not_before"] = ev.get("not_before")
        job["defer_reason"] = ev.get("reason")
        job["deferrals"] = job.get("deferrals", 0) + 1
    elif kind == "completed":
        job["status"] = "completed"
        job["result"] = ev.get("result")
    elif kind == "failed":
        job["status"] = "failed"
        job["error"] = ev.get("error")
        job["retryable"] = ev.get("retryable", True)
    elif kind == "cancelled":
        job["status"] = "cancelled"
        job["cancelled_by"] = ev.get("by")
        job["cancel_reason"] = ev.get("reason")
    elif kind == "needs_review":
        job["status"] = "needs_review"
        job["proposal"] = ev.get("proposal")
    elif kind == "revised":
        # A reviewer corrected the proposal. Status stays needs_review; the
        # proposal is replaced and the verdict recorded, so /ops shows the
        # corrected destination alongside who changed it and why.
        job["proposal"] = ev.get("proposal", job.get("proposal"))
        job["reviewed_by"] = ev.get("by")
        job["review_verdict"] = ev.get("verdict")
        job["review_note"] = ev.get("note")
    elif kind == "approved":
        job["status"] = "approved"
        job["approved_by"] = ev.get("by")
    elif kind == "rejected":
        job["status"] = "rejected"
        job["rejected_by"] = ev.get("by")
        job["reject_reason"] = ev.get("reason")
    elif kind == "superseded":
        job["status"] = "superseded"
        job["superseded_by"] = ev.get("by")
        job["replacement_job"] = ev.get("replacement")
        job["supersede_note"] = ev.get("note")
    elif kind == "consumed":
        # Completed verifier jobs are immutable audit records. Marking the
        # output consumed prevents an older verdict from being replayed onto a
        # later reclassification pass for the same source.
        job["_consumed"] = True
        job["consumed_by"] = ev.get("by")
    elif kind == "resolved":
        job["status"] = "resolved"
        job["resolved_by"] = ev.get("by")
        job["resolution_note"] = ev.get("note")
        job["replacement_job"] = ev.get("replacement")


def _read_snapshot() -> tuple[dict, int]:
    try:
        snap = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        return snap.get("jobs", {}), int(snap.get("offset", 0))
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        return {}, 0


def _write_snapshot(jobs: dict, offset: int) -> None:
    """Snapshot is a cache: a failed write costs speed, never correctness."""
    try:
        _ensure_dirs()
        tmp = Path(str(SNAPSHOT) + ".tmp")
        tmp.write_text(
            json.dumps({"offset": offset, "jobs": jobs}, ensure_ascii=False),
            encoding="utf-8")
        os.replace(tmp, SNAPSHOT)
    except OSError:
        pass


def fold(*, use_snapshot: bool = True) -> dict:
    """Return {job_id: state}. Replays only the tail past the snapshot."""
    jobs, offset = _read_snapshot() if use_snapshot else ({}, 0)
    if not EVENTS.exists():
        return jobs
    size = EVENTS.stat().st_size
    if offset > size:  # ledger was rotated or truncated - refold from scratch
        jobs, offset = {}, 0
    replayed = 0
    with open(EVENTS, "r", encoding="utf-8") as f:
        f.seek(offset)
        for line in f:
            if not line.endswith("\n"):
                break  # partial trailing write; a later read picks it up
            line = line.strip()
            if not line:
                offset += len(line.encode("utf-8")) + 1
                continue
            try:
                _apply_event(jobs, json.loads(line))
            except json.JSONDecodeError:
                log_line("ledger", f"skipped unparseable event at offset {offset}")
            offset += len(line.encode("utf-8")) + 1
            replayed += 1
    if use_snapshot and replayed >= SNAPSHOT_EVERY:
        _write_snapshot(jobs, offset)
    return jobs


# --------------------------------------------------------------------------
# Write API
# --------------------------------------------------------------------------

def create(kind: str, payload, *, runtime: str | None = None,
           sensitivity: str = DEFAULT_SENSITIVITY, parent: str | None = None) -> str:
    """Enqueue a job. Keep `payload` a reference (a path), not a blob."""
    if not kind:
        raise LedgerError("kind is required")
    if sensitivity not in VALID_SENSITIVITY:
        sensitivity = DEFAULT_SENSITIVITY  # fail closed
    jid = new_job_id()
    with file_lock(EVENTS):
        _append({
            "ts": now().isoformat(timespec="seconds"),
            "job": jid,
            "event": "created",
            "kind": kind,
            "payload": payload,
            "runtime": runtime,
            "sensitivity": sensitivity,
            "parent": parent,
        })
    return jid


def is_waiting(job: dict, at=None) -> bool:
    """True while a deferred job's `not_before` is still in the future.

    An unparseable timestamp counts as not waiting: a bad value must never
    strand a job forever.
    """
    stamp = job.get("not_before")
    if not stamp or job.get("status") != "created":
        return False
    try:
        from datetime import datetime
        not_before = datetime.fromisoformat(str(stamp))
    except (TypeError, ValueError):
        return False
    current = at or now()
    if not_before.tzinfo is None:
        not_before = not_before.replace(tzinfo=current.tzinfo)
    return not_before > current


def claim(worker: str, *, kinds=None, runtimes=None) -> dict | None:
    """Atomically claim the oldest ready job. Returns the job state, or None.

    The whole read-fold-append cycle runs under the lock, so two workers can
    never claim the same job. A deferred job is skipped until its `not_before`
    has passed; it keeps its place in the queue.
    """
    kinds = set(kinds) if kinds else None
    runtimes = set(runtimes) if runtimes else None
    with file_lock(EVENTS):
        jobs = fold()
        current = now()
        # Insertion order == order the `created` events were appended == true
        # FIFO. Do not sort by id: ids can tie, and the log is the ground truth.
        for jid in jobs:
            job = jobs[jid]
            if job.get("status") != "created":
                continue
            if kinds and job.get("kind") not in kinds:
                continue
            if runtimes and job.get("runtime") not in runtimes:
                continue
            if is_waiting(job, current):
                continue
            _append({
                "ts": now().isoformat(timespec="seconds"),
                "job": jid,
                "event": "claimed",
                "worker": worker,
            })
            job["status"] = "claimed"
            job["worker"] = worker
            return job
    return None


def claim_job(job_id: str, worker: str) -> dict | None:
    """Atomically claim one known job, used by low-latency capture automation.

    Scheduled drains remain FIFO. A freshly captured thought may explicitly
    prioritize its own job so it does not wait behind a historical archive
    backlog, while still using the exact same ledger transition and dispatcher.
    """
    with file_lock(EVENTS):
        jobs = fold()
        job = jobs.get(job_id)
        if not job or job.get("status") != "created" or is_waiting(job):
            return None
        _append({
            "ts": now().isoformat(timespec="seconds"),
            "job": job_id,
            "event": "claimed",
            "worker": worker,
        })
        job["status"] = "claimed"
        job["worker"] = worker
        return job


def _transition(job_id: str, event: str, allowed_from: set, **fields) -> None:
    with file_lock(EVENTS):
        jobs = fold()
        job = jobs.get(job_id)
        if job is None:
            raise LedgerError(f"unknown job {job_id}")
        if job["status"] not in allowed_from:
            raise LedgerError(
                f"job {job_id} is {job['status']}; "
                f"{event} requires one of {sorted(allowed_from)}")
        _append({
            "ts": now().isoformat(timespec="seconds"),
            "job": job_id,
            "event": event,
            **fields,
        })


def complete(job_id: str, result=None) -> None:
    # `approved` is allowed so an apply step can finish a reviewed job.
    _transition(job_id, "completed", {"claimed", "approved"}, result=result)


def fail(job_id: str, error: str, *, retryable: bool = True) -> None:
    # `approved` is included so apply_jobs.py can record a failed effect: the
    # decision was made, but the copy did not happen and needs a human look.
    _transition(job_id, "failed", {"claimed", "created", "approved"},
                error=str(error), retryable=retryable)


def defer(job_id: str, not_before, reason: str = "") -> None:
    """Return a claimed job to the queue, not claimable before `not_before`.

    `not_before` is a timezone-aware datetime (or an ISO string). This is the
    dispatcher's answer to a spent subscription window: the job is neither
    failed nor lost, it simply waits for the reset the provider named.
    """
    from datetime import datetime
    if isinstance(not_before, datetime):
        if not_before.tzinfo is None:
            raise LedgerError("defer() needs a timezone-aware not_before")
        stamp = not_before.isoformat(timespec="seconds")
    else:
        stamp = str(not_before)
        datetime.fromisoformat(stamp)  # validate now, not at claim time
    _transition(job_id, "deferred", {"claimed"}, not_before=stamp,
                reason=str(reason or "")[:300])


def needs_review(job_id: str, proposal) -> None:
    _transition(job_id, "needs_review", {"claimed"}, proposal=proposal)


def revise(job_id: str, proposal, *, by: str, verdict: str, note: str = "") -> None:
    """Record a reviewer's correction without changing status."""
    _transition(job_id, "revised", {"needs_review"},
                proposal=proposal, by=by, verdict=verdict, note=note)


def approve(job_id: str, by: str = "owner") -> None:
    _transition(job_id, "approved", {"needs_review"}, by=by)


def reject(job_id: str, reason: str, by: str = "owner") -> None:
    _transition(job_id, "rejected", {"needs_review"}, by=by, reason=str(reason))


def cancel(job_id: str, *, by: str = "owner",
           reason: str = "no longer needed") -> None:
    """Stop queued/running work while retaining its full audit history.

    A claimed worker observes the terminal state through its runtime
    cancellation callback. The state transition is atomic, so either the
    cancellation or the worker's completion wins; a completed effect can never
    be relabelled as cancelled after the fact.
    """
    _transition(
        job_id, "cancelled", {"created", "claimed"},
        by=by, reason=str(reason)[:500],
    )


def supersede(job_id: str, replacement: str, *, by: str,
              note: str = "") -> None:
    """Replace a reviewed classification with a new classification pass."""
    _transition(job_id, "superseded", {"needs_review", "approved"},
                replacement=replacement, by=by, note=note)


def consume(job_id: str, *, by: str = "triage-review") -> None:
    """Record that a completed verifier output has been handled exactly once."""
    _transition(job_id, "consumed", {"completed"}, by=by)


def resolve(job_id: str, *, by: str, note: str,
            replacement: str | None = None) -> None:
    """Acknowledge a historical failure whose work succeeded elsewhere."""
    _transition(
        job_id, "resolved", {"failed"}, by=by, note=str(note),
        replacement=replacement)


def release(job_id: str, why: str = "stale claim") -> None:
    """Return an abandoned claim to the queue."""
    _transition(job_id, "released", {"claimed"}, why=why)


def reap(*, older_than_seconds: int = STALE_CLAIM_SECONDS) -> list[str]:
    """Re-enqueue jobs claimed by a worker that died mid-run."""
    from datetime import datetime, timedelta
    cutoff = now() - timedelta(seconds=older_than_seconds)
    reaped = []
    for jid, job in fold().items():
        if job.get("status") != "claimed":
            continue
        ts = job.get("claimed_ts") or job.get("updated_ts")
        try:
            if ts and datetime.fromisoformat(ts) < cutoff:
                release(jid)
                reaped.append(jid)
        except (ValueError, LedgerError):
            continue
    if reaped:
        log_line("ledger", f"reaped {len(reaped)} stale claims")
    return reaped


# --------------------------------------------------------------------------
# Read API
# --------------------------------------------------------------------------

def get(job_id: str) -> dict | None:
    return fold().get(job_id)


def query(*, status=None, kind=None, limit=None) -> list[dict]:
    out = []
    jobs = fold()
    for jid in jobs:          # event-log order, same reason as claim()
        job = jobs[jid]
        if status and job.get("status") != status:
            continue
        if kind and job.get("kind") != kind:
            continue
        out.append(job)
    if limit:
        out = out[-int(limit):]
    return out


def stats() -> dict:
    jobs = fold()
    by_status, by_kind = {}, {}
    for job in jobs.values():
        by_status[job.get("status")] = by_status.get(job.get("status"), 0) + 1
        by_kind[job.get("kind")] = by_kind.get(job.get("kind"), 0) + 1
    return {"total": len(jobs), "by_status": by_status, "by_kind": by_kind}


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _arg(name: str, default=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def _fmt(job: dict) -> str:
    return (f"{job['job']}  {job.get('status',''):<13} {job.get('kind',''):<22} "
            f"{job.get('runtime') or '-':<8} {job.get('sensitivity',''):<9} "
            f"{json.dumps(job.get('payload'), ensure_ascii=False)[:60]}")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__.strip().split("CLI:")[-1].strip())
        return 1
    cmd = sys.argv[1]
    as_json = "--json" in sys.argv

    if cmd == "create":
        kind = sys.argv[2]
        payload = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
        jid = create(kind, payload,
                     runtime=_arg("--runtime"),
                     sensitivity=_arg("--sensitivity", DEFAULT_SENSITIVITY))
        print(jid)
    elif cmd == "list":
        rows = query(status=_arg("--status"), kind=_arg("--kind"),
                     limit=_arg("--limit"))
        if as_json:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
        else:
            for r in rows:
                print(_fmt(r))
            print(f"({len(rows)} jobs)")
    elif cmd == "show":
        job = get(sys.argv[2])
        print(json.dumps(job, ensure_ascii=False, indent=2) if job else "not found")
        return 0 if job else 1
    elif cmd == "approve":
        approve(sys.argv[2], _arg("--by", "owner"))
        print(f"approved {sys.argv[2]}")
        # Approving is a decision; applying is the effect. They stay separate
        # functions - but a human who approved something meant for it to
        # happen, so the CLI closes the gap by default rather than leaving the
        # job parked until the next Agent Day. --no-apply keeps the old
        # decide-now/file-later behaviour for bulk approvals.
        #
        # Spawned from the CLI layer, never from approve() itself: the library
        # function is the pure state machine, and apply_jobs imports this
        # module.
        if "--no-apply" not in sys.argv:
            import apply_jobs
            apply_jobs.spawn_background()
            print("apply: spawned in background")
    elif cmd == "revise":
        proposal = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
        verdict = _arg("--verdict", "manual")
        prior = get(sys.argv[2])
        revise(sys.argv[2], proposal, by=_arg("--by", "owner"),
               verdict=verdict,
               note=_arg("--note", "corrected from dashboard"))
        print(f"revised {sys.argv[2]}")
        # A human "manual" verdict is a teaching signal: record what she
        # changed so the classifier prompt learns their tendencies. CLI-only on
        # purpose - automated actors (verifier, protection policy) call the
        # library revise() directly and must not pollute the lesson log.
        # Best-effort: a lesson failure never undoes the recorded transition.
        if verdict == "manual" and prior:
            try:
                from triage import lessons
                lessons.record_from_revision(
                    prior, proposal, by=_arg("--by", "owner"))
            except Exception as exc:  # noqa: BLE001
                log_line("ledger", f"lesson record failed: {exc!r}")
    elif cmd == "reject":
        prior = get(sys.argv[2])
        reject(sys.argv[2], sys.argv[3], _arg("--by", "owner"))
        print(f"rejected {sys.argv[2]}")
        if prior:
            try:
                from triage import lessons
                lessons.record_rejection(
                    prior, by=_arg("--by", "owner"), reason=sys.argv[3])
            except Exception as exc:  # noqa: BLE001
                log_line("ledger", f"lesson record failed: {exc!r}")
    elif cmd == "cancel":
        cancel(
            sys.argv[2],
            by=_arg("--by", "owner"),
            reason=_arg("--reason", "no longer needed"),
        )
        print(f"cancelled {sys.argv[2]}")
    elif cmd == "reap":
        mins = int(_arg("--older-than-min", STALE_CLAIM_SECONDS // 60))
        got = reap(older_than_seconds=mins * 60)
        print(f"reaped {len(got)}: {', '.join(got) if got else '-'}")
    elif cmd == "resolve":
        resolve(
            sys.argv[2], by=_arg("--by", "owner"),
            note=_arg("--note", "resolved by later work"),
            replacement=_arg("--replacement"))
        print(f"resolved {sys.argv[2]}")
    elif cmd == "stats":
        s = stats()
        if as_json:
            print(json.dumps(s, ensure_ascii=False, indent=2))
        else:
            print(f"total: {s['total']}")
            for k, v in sorted(s["by_status"].items(), key=lambda x: -x[1]):
                print(f"  {k or '(none)':<14} {v}")
    else:
        print(f"unknown command: {cmd}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
