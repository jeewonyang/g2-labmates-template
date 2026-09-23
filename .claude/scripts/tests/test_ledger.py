"""Tests for the append-only job ledger.

Plain-python, no pytest - matches test_security.py, and the repo has no test
dependency. Runs against a temporary ledger directory so it never touches real
state.

  python .claude/scripts/tests/test_ledger.py
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import ledger  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"{'PASS' if cond else 'FAIL'} {name}{'' if cond else '  -> ' + detail}")


def fresh_ledger(tmp: Path) -> None:
    """Point the module at an empty ledger dir."""
    ledger.LEDGER_DIR = tmp
    ledger.EVENTS = tmp / "events.jsonl"
    ledger.SNAPSHOT = tmp / "snapshot.json"
    tmp.mkdir(parents=True, exist_ok=True)


def test_lifecycle(tmp):
    fresh_ledger(tmp / "lifecycle")
    jid = ledger.create("test.noop", {"path": "a.md"}, runtime="ollama",
                        sensitivity="internal")
    check("create returns a sortable id", len(jid) > 14 and "-" in jid, jid)
    check("new job is created", ledger.get(jid)["status"] == "created")

    job = ledger.claim("w1")
    check("claim returns the job", job and job["job"] == jid)
    check("claimed status folds", ledger.get(jid)["status"] == "claimed")
    check("claim records the worker", ledger.get(jid)["worker"] == "w1")

    ledger.complete(jid, {"ok": True})
    st = ledger.get(jid)
    check("complete is terminal", st["status"] == "completed")
    check("result is preserved", st["result"] == {"ok": True})


def test_claim_is_exactly_once(tmp):
    fresh_ledger(tmp / "once")
    jid = ledger.create("test.noop", {}, sensitivity="internal")
    first = ledger.claim("w1")
    second = ledger.claim("w2")
    check("second claim of the same job returns None",
          first is not None and second is None)


def test_cancel_preserves_history_and_stops_claims(tmp):
    fresh_ledger(tmp / "cancel")
    queued = ledger.create("draft.reply", {"sender": "Old message"},
                           sensitivity="internal")
    ledger.cancel(queued, by="tester", reason="no longer needed")
    state = ledger.get(queued)
    check("a queued job can be cancelled", state["status"] == "cancelled")
    check("cancellation records who and why",
          state["cancelled_by"] == "tester"
          and state["cancel_reason"] == "no longer needed")
    check("a cancelled job cannot be claimed", ledger.claim("w1") is None)

    running = ledger.create("echo.check", {}, sensitivity="internal")
    ledger.claim_job(running, "w1")
    ledger.cancel(running, by="tester", reason="stop")
    check("a claimed job can be cancelled",
          ledger.get(running)["status"] == "cancelled")
    try:
        ledger.complete(running, {})
        completed_after_cancel = True
    except ledger.LedgerError:
        completed_after_cancel = False
    check("a cancelled job cannot complete later", not completed_after_cancel)


def test_concurrent_claims(tmp):
    """Two OS processes racing for 25 jobs must claim each exactly once."""
    d = tmp / "concurrent"
    fresh_ledger(d)
    for i in range(25):
        ledger.create("test.race", {"i": i}, sensitivity="internal")

    worker = f"""
import sys, json
sys.path.insert(0, r"{SCRIPTS}")
import ledger
from pathlib import Path
ledger.LEDGER_DIR = Path(r"{d}")
ledger.EVENTS = ledger.LEDGER_DIR / "events.jsonl"
ledger.SNAPSHOT = ledger.LEDGER_DIR / "snapshot.json"
got = []
while True:
    j = ledger.claim(sys.argv[1])
    if not j:
        break
    got.append(j["job"])
print(json.dumps(got))
"""
    script = d / "worker.py"
    script.write_text(worker, encoding="utf-8")
    procs = [subprocess.Popen([sys.executable, str(script), f"w{i}"],
                              stdout=subprocess.PIPE, text=True) for i in range(2)]
    claimed = []
    for p in procs:
        out, _ = p.communicate(timeout=120)
        claimed.extend(json.loads(out.strip().splitlines()[-1]))

    check("every job claimed exactly once (no duplicates)",
          len(claimed) == len(set(claimed)), f"{len(claimed)} claims, {len(set(claimed))} unique")
    check("no job lost in the race", len(set(claimed)) == 25, f"got {len(set(claimed))}/25")


def test_review_gate(tmp):
    fresh_ledger(tmp / "review")
    jid = ledger.create("test.review", {}, sensitivity="internal")
    ledger.claim("w1")
    ledger.needs_review(jid, {"vault": "01_Projects", "confidence": 0.6})
    check("needs_review folds", ledger.get(jid)["status"] == "needs_review")

    try:
        ledger.complete(jid, {})
        completed_without_approval = True
    except ledger.LedgerError:
        completed_without_approval = False
    check("a review-gated job cannot complete without approval",
          not completed_without_approval)

    ledger.approve(jid, by="tester")
    check("approve folds", ledger.get(jid)["status"] == "approved")
    ledger.complete(jid, {"filed": True})
    check("approved job can then complete",
          ledger.get(jid)["status"] == "completed")


def test_reject(tmp):
    fresh_ledger(tmp / "reject")
    jid = ledger.create("test.review", {}, sensitivity="internal")
    ledger.claim("w1")
    ledger.needs_review(jid, {})
    ledger.reject(jid, "wrong destination", by="tester")
    st = ledger.get(jid)
    check("reject is terminal and keeps the reason",
          st["status"] == "rejected" and st["reject_reason"] == "wrong destination")


def test_sensitivity_fails_closed(tmp):
    fresh_ledger(tmp / "sens")
    jid = ledger.create("test.noop", {}, sensitivity="bogus")
    check("unknown sensitivity falls back to private",
          ledger.get(jid)["sensitivity"] == "private")
    jid2 = ledger.create("test.noop", {})
    check("default sensitivity is private",
          ledger.get(jid2)["sensitivity"] == "private")


def test_snapshot_equivalence(tmp):
    d = tmp / "snap"
    fresh_ledger(d)
    ids = [ledger.create("test.noop", {"i": i}, sensitivity="internal")
           for i in range(30)]
    # Complete whatever claim() actually hands back, and assert it is FIFO -
    # asserting the order here is the point, since ids can tie at the same tick.
    for expected in ids[:10]:
        got = ledger.claim("w1")
        if got["job"] != expected:
            check("claim() returns jobs in FIFO event-log order", False,
                  f"expected {expected}, got {got['job']}")
            return
        ledger.complete(got["job"], {"i": 1})
    check("claim() returns jobs in FIFO event-log order", True)
    ledger._write_snapshot(ledger.fold(use_snapshot=False),
                           d.joinpath("events.jsonl").stat().st_size)
    for jid in ids[10:15]:
        ledger.claim("w2")
        ledger.fail(jid, "boom")

    with_snap = ledger.fold(use_snapshot=True)
    without = ledger.fold(use_snapshot=False)
    check("snapshot + tail replay == full fold", with_snap == without,
          f"{len(with_snap)} vs {len(without)} jobs")


def test_stale_claim_reaped(tmp):
    fresh_ledger(tmp / "reap")
    jid = ledger.create("test.noop", {}, sensitivity="internal")
    ledger.claim("dead-worker")
    check("nothing reaped while the claim is fresh",
          ledger.reap(older_than_seconds=3600) == [])
    time.sleep(1.1)
    reaped = ledger.reap(older_than_seconds=1)
    check("stale claim is released back to the queue",
          reaped == [jid] and ledger.get(jid)["status"] == "created")
    check("reclaim after reap works and counts the attempt",
          ledger.claim("w2") is not None and ledger.get(jid)["attempts"] == 2)


def test_append_only(tmp):
    """The event log must never be rewritten - it is the audit trail."""
    d = tmp / "append"
    fresh_ledger(d)
    jid = ledger.create("test.noop", {}, sensitivity="internal")
    before = (d / "events.jsonl").read_text(encoding="utf-8")
    ledger.claim("w1")
    ledger.complete(jid, {})
    after = (d / "events.jsonl").read_text(encoding="utf-8")
    check("existing events are never modified", after.startswith(before))
    check("events were appended", len(after.splitlines()) == 3)


def test_reclassification_transitions(tmp):
    fresh_ledger(tmp / "reclassification")
    source = ledger.create("triage.classify", {"path": "inbox/source.md"})
    ledger.claim("worker")
    ledger.needs_review(source, {
        "folder_mode": "create",
        "folder": "Protein Design",
    })
    replacement = ledger.create(
        "triage.classify",
        {"path": "inbox/source.md", "reclassificationPass": 1},
        parent=source,
    )
    ledger.supersede(
        source, replacement, by="claude-review",
        note="folder created; classify again",
    )
    state = ledger.get(source)
    check("folder creation supersedes the first classification",
          state["status"] == "superseded")
    check("superseded classification points to its replacement",
          state["replacement_job"] == replacement)

    review = ledger.create("triage.review", {"items": []})
    ledger.claim_job(review, "reviewer")
    ledger.complete(review, {"verdicts": []})
    ledger.consume(review)
    check("completed verifier output is marked consumed",
          ledger.get(review).get("_consumed") is True)


def test_resolved_failure(tmp):
    fresh_ledger(tmp / "resolved")
    jid = ledger.create("triage.review", {"items": []})
    ledger.fail(jid, "old runtime failure")
    ledger.resolve(
        jid, by="test", note="source was handled by a later review",
        replacement="replacement-job")
    state = ledger.get(jid)
    check("historical failure can be resolved append-only",
          state["status"] == "resolved")
    check("resolution retains its replacement",
          state["replacement_job"] == "replacement-job")


def test_deferred_jobs_wait_for_their_reset(tmp):
    from datetime import timedelta
    from shared import now

    fresh_ledger(tmp / "deferred")
    early = ledger.create("test.noop", {"n": 1}, runtime="claude",
                          sensitivity="internal")
    late = ledger.create("test.noop", {"n": 2}, runtime="claude",
                         sensitivity="internal")

    try:
        ledger.defer(early, now() + timedelta(hours=1), "not claimed yet")
        check("defer requires a claimed job", False)
    except ledger.LedgerError:
        check("defer requires a claimed job", True)

    claimed = ledger.claim("w1")
    check("FIFO still hands out the older job first", claimed["job"] == early)
    ledger.defer(early, now() + timedelta(hours=1),
                 "claude session limit, resets 10pm")
    state = ledger.get(early)
    check("a deferred job is back in `created`", state["status"] == "created")
    check("with its worker cleared", state["worker"] is None
          and "claimed_ts" not in state)
    check("and its reason and count recorded",
          state["defer_reason"].startswith("claude session limit")
          and state["deferrals"] == 1)
    check("is_waiting() sees the future not_before", ledger.is_waiting(state))

    nxt = ledger.claim("w1")
    check("claim() skips the waiting job and hands out the next one",
          nxt is not None and nxt["job"] == late, str(nxt and nxt["job"]))
    check("claim_job() refuses a waiting job too",
          ledger.claim_job(early, "w2") is None)
    check("with nothing else ready, claim() returns None",
          ledger.claim("w1") is None)

    # A reset that has already passed makes the job claimable again.
    ledger.release(late, why="test")
    ledger.claim("w1")
    ledger.defer(late, now() - timedelta(seconds=1), "reset already passed")
    got = ledger.claim("w1")
    check("a job whose not_before has passed is claimable",
          got is not None and got["job"] == late, str(got and got["job"]))
    check("claiming clears not_before", "not_before" not in ledger.get(late))
    check("deferrals accumulate across cycles",
          ledger.get(late)["deferrals"] == 1)

    # A deferred job can still be cancelled from /ops - it is `created`.
    ledger.cancel(early, by="tester", reason="no longer wanted")
    check("a waiting job can be cancelled", ledger.get(early)["status"] == "cancelled")

    try:
        ledger.claim("w1")
        ledger.defer(late, "not a timestamp", "bad")
        check("defer rejects an unparseable not_before", False)
    except ValueError:
        check("defer rejects an unparseable not_before", True)

    events = [json.loads(line) for line in
              ledger.EVENTS.read_text(encoding="utf-8").splitlines()]
    check("deferral is an appended event, not a rewrite",
          sum(1 for e in events if e["event"] == "deferred") == 2)


def test_registry_contract():
    sys.path.insert(0, str(SCRIPTS))
    import jobs
    check("job registry imports and lists kinds without error",
          isinstance(jobs.kinds(), list))


def test_apply_is_serialized(tmp):
    """Approval now spawns apply_jobs.py, so concurrent runs are routine.

    apply() is not idempotent - a second pass writes a second wiki page and, for
    admin.schedule_proposal, inserts a second calendar event. The guard is
    APPLY_LOCK, and the job must still be `approved` when a blocked run gives up,
    never applied twice.
    """
    d = tmp / "applylock"
    fresh_ledger(d)
    import apply_jobs
    from shared import file_lock

    jid = ledger.create("echo.check", {"note": "lock test"},
                        sensitivity="internal")
    ledger.claim_job(jid, "w1")
    ledger.needs_review(jid, {"ok": True})
    ledger.approve(jid, by="test")

    lock_target = d / "apply-jobs"
    runner = f"""
import sys
sys.path.insert(0, r"{SCRIPTS}")
from pathlib import Path
import ledger, apply_jobs
ledger.LEDGER_DIR = Path(r"{d}")
ledger.EVENTS = ledger.LEDGER_DIR / "events.jsonl"
ledger.SNAPSHOT = ledger.LEDGER_DIR / "snapshot.json"
apply_jobs.APPLY_LOCK = Path(r"{lock_target}")
apply_jobs.APPLY_LOCK_TIMEOUT = 1.0
sys.argv = ["apply_jobs.py"]
sys.exit(apply_jobs.main())
"""
    # Hold the lock, then race a second run against it.
    with file_lock(lock_target, timeout=5.0):
        p = subprocess.run([sys.executable, "-c", runner],
                           capture_output=True, text=True, timeout=60)
    check("a blocked apply run exits cleanly rather than erroring",
          p.returncode == 0, p.stderr[-300:])
    check("a blocked apply run says so",
          "another apply run is in progress" in p.stdout, p.stdout[-200:])
    check("a blocked apply run does NOT apply the job",
          ledger.get(jid)["status"] == "approved",
          ledger.get(jid)["status"])

    # With the lock free, the same run files it.
    p2 = subprocess.run([sys.executable, "-c", runner],
                        capture_output=True, text=True, timeout=60)
    check("an unblocked apply run files the approved job",
          ledger.get(jid)["status"] == "completed",
          f"{ledger.get(jid)['status']} / {p2.stdout[-200:]}")


def test_approve_cli_spawns_apply(tmp):
    """The /ops button and this CLI are the two manual approval surfaces.

    Both must file the effect without a hand-run apply step - the gap that left
    three approved wiki.ingest jobs unfiled for 15 hours.
    """
    d = tmp / "approvecli"
    fresh_ledger(d)
    import apply_jobs
    check("apply_jobs exposes a background spawn for approve paths",
          callable(getattr(apply_jobs, "spawn_background", None)))

    src = (SCRIPTS / "ledger.py").read_text(encoding="utf-8")
    approve_block = src.split('elif cmd == "approve":')[1].split("elif cmd ==")[0]
    check("the approve CLI spawns apply by default",
          "spawn_background()" in approve_block and "--no-apply" in approve_block)
    check("spawning lives in the CLI layer, not the approve() state machine",
          "spawn_background" not in src.split("def approve(")[1].split("def ")[0])

    route = (SCRIPTS.parents[1] / "src" / "app" / "api" / "ops" / "route.ts"
             ).read_text(encoding="utf-8")
    check("the /ops approve action spawns apply",
          "runApplyJobs()" in route and "apply_jobs.py" in route)
    check("/ops spawns apply detached so approving stays instant",
          "detached: true" in route.split("function runApplyJobs")[1][:400])


def test_run_button_cannot_approve():
    """The /ops "run queued now" button dispatches; it never approves.

    The button exists so the owner does not have to open a terminal to start
    queued work. That convenience must not become a second approval path: the
    drain branch has to return before any approve/apply logic, so a press can
    create review items but can never clear them.
    """
    route = (SCRIPTS.parents[1] / "src" / "app" / "api" / "ops" / "route.ts"
             ).read_text(encoding="utf-8")
    check("the /ops drain action exists",
          'action === "drain"' in route)

    drain_branch = route.split('if (action === "drain")')[1].split("\n  }")[0]
    check("drain only spawns the dispatcher",
          "runDispatcher()" in drain_branch)
    check("drain approves nothing",
          "approve" not in drain_branch and "runApplyJobs" not in drain_branch,
          drain_branch)
    check("drain returns before the approve/reject handling",
          "return NextResponse.json" in drain_branch)

    dispatcher = route.split("function runDispatcher")[1][:400]
    check("the dispatcher runs detached so the click stays instant",
          "detached: true" in dispatcher)
    check("one press is bounded by --max",
          '"--max"' in dispatcher)
    check("drain uses the dispatcher, not the apply script",
          "dispatch.py" in dispatcher and "apply_jobs.py" not in dispatcher)


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        test_lifecycle(tmp)
        test_claim_is_exactly_once(tmp)
        test_cancel_preserves_history_and_stops_claims(tmp)
        test_concurrent_claims(tmp)
        test_review_gate(tmp)
        test_reject(tmp)
        test_sensitivity_fails_closed(tmp)
        test_snapshot_equivalence(tmp)
        test_stale_claim_reaped(tmp)
        test_append_only(tmp)
        test_reclassification_transitions(tmp)
        test_resolved_failure(tmp)
        test_deferred_jobs_wait_for_their_reset(tmp)
        test_registry_contract()
        test_apply_is_serialized(tmp)
        test_approve_cli_spawns_apply(tmp)
        test_run_button_cannot_approve()

    print()
    if FAIL:
        print(f"{len(FAIL)} FAILED: {', '.join(FAIL)}")
        return 1
    print(f"All {len(PASS)} ledger tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
