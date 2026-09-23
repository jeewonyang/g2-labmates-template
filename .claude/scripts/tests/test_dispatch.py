"""Tests for the dispatcher's routing and the confidentiality guard.

The guard is the security-critical code in Phase 3: it is what makes the
`private` sensitivity an enforced boundary rather than a naming convention.
These tests must never be weakened to make a job route.

  python .claude/scripts/tests/test_dispatch.py
"""

import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import dispatch  # noqa: E402
import ledger  # noqa: E402
import runtimes  # noqa: E402
from runtimes import RunResult, capacity  # noqa: E402

PASS, FAIL = [], []

# The dispatcher consults the capacity breaker and the usage snapshot before
# every run. Keep both in a scratch dir so these tests neither read the real
# state nor reach the usage endpoint.
_CAPACITY_TMP = tempfile.TemporaryDirectory()
capacity.STATE_FILE = Path(_CAPACITY_TMP.name) / "runtime-capacity.json"
capacity.SNAPSHOT_FILE = Path(_CAPACITY_TMP.name) / "usage-limits.json"
capacity.REFRESH_ENABLED = False


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"{'PASS' if cond else 'FAIL'} {name}{'' if cond else '  -> ' + detail}")


def job(payload, sensitivity="internal", kind="echo.check", runtime=None):
    return {"job": "test-1", "kind": kind, "payload": payload,
            "sensitivity": sensitivity, "runtime": runtime}


def test_path_derived_sensitivity():
    cases = [
        ({"path": "VAULT/Confidential/20_Areas/Immigration/x.md"}, "private",
         "Confidential is private"),
        ({"path": "VAULT/Research-Private/10_Projects/Alpha/notes.md"}, "private",
         "Research-Private is private"),
        ({"path": "VAULT/Finance/20_Areas/Tax/return.pdf"}, "private",
         "Finance source content is local-only"),
        ({"path": "VAULT/G2OS-Staging/30_Resources/paper.md"}, "internal",
         "G2OS-Staging is internal"),
        ({"path": "archive/staging/SSD/Work/04_Lab/_private/x.md"}, "private",
         "_private anywhere is private"),
    ]
    for payload, expected, label in cases:
        got = dispatch.derive_sensitivity(job(payload))
        check(label, got == expected, f"got {got}")

    # The producer does not get the final say.
    got = dispatch.derive_sensitivity(
        job({"path": "VAULT/Confidential/x.md"}, sensitivity="internal"))
    check("a payload under Confidential/ overrides a declared 'internal'",
          got == "private", f"got {got}")

    # Fail closed.
    check("missing sensitivity defaults to private",
          dispatch.derive_sensitivity({"payload": {"note": "no path here"}}) == "private")
    check("unknown sensitivity value defaults to private",
          dispatch.derive_sensitivity(
              job({"note": "x"}, sensitivity="bogus")) == "private")


def test_guard_blocks_cloud_for_private():
    for rt in ("claude", "codex"):
        try:
            dispatch.guard(job({"path": "VAULT/Confidential/x.md"}), rt)
            blocked = False
        except dispatch.SensitivityViolation:
            blocked = True
        check(f"private job refused on cloud runtime {rt!r}", blocked)

    try:
        s = dispatch.guard(job({"path": "VAULT/Confidential/x.md"}), "ollama")
        ok = s == "private"
    except dispatch.SensitivityViolation:
        ok = False
    check("private job allowed on local runtime 'ollama'", ok)

    try:
        s = dispatch.guard(job({"path": "VAULT/G2OS-Staging/x.md"}), "claude")
        ok = s == "internal"
    except dispatch.SensitivityViolation:
        ok = False
    check("internal job allowed on a cloud runtime", ok)


def test_nested_payload_paths_are_seen():
    """A path buried in a list/dict must not slip past the guard."""
    payload = {"files": [{"src": "VAULT/Confidential/deep/x.md"}], "n": 3}
    check("guard walks nested payload structures",
          dispatch.derive_sensitivity(job(payload)) == "private")


def test_prose_that_mentions_a_private_path_is_not_a_path():
    payload = {
        "watchlist": (
            "This is public market commentary. Financial records belong in "
            "VAULT/Finance/, which this workflow never reads."
        ),
    }
    check(
        "a private path mentioned in prose does not taint the whole payload",
        dispatch.derive_sensitivity(job(payload)) == "internal",
    )


def test_private_jobs_auto_route_local():
    private = job(
        {"recent_files": ["VAULT/Research-Private/10_Projects/Alpha/x.md"]},
        sensitivity="internal",
        runtime="claude",
    )
    check(
        "private payload overrides a cloud runtime with ollama",
        dispatch.resolve_runtime(private, object()) == "ollama",
    )


def test_local_runtimes_allowlist():
    check("ollama is the only local runtime",
          runtimes.LOCAL_RUNTIMES == frozenset({"ollama"}),
          str(runtimes.LOCAL_RUNTIMES))
    check("claude is not local", not runtimes.is_local("claude"))
    check("codex is not local", not runtimes.is_local("codex"))


def test_run_one_autoroutes_private_job():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        ledger.LEDGER_DIR = d
        ledger.EVENTS = d / "events.jsonl"
        ledger.SNAPSHOT = d / "snapshot.json"

        selected = []
        original_get = runtimes.get

        class LocalStub:
            @staticmethod
            def run(*args, **kwargs):
                return RunResult(ok=True, text="ECHO_OK", runtime="ollama")

        runtimes.get = lambda name: selected.append(name) or LocalStub
        jid = ledger.create("echo.check", {"path": "VAULT/Confidential/x.md"},
                            runtime="claude", sensitivity="internal")
        try:
            claimed = ledger.claim("t1")
            status = dispatch.run_one(claimed, dry_run=False)
            st = ledger.get(jid)
        finally:
            runtimes.get = original_get
        check("run_one completes a private job locally",
              status == "completed" and st["status"] == "completed",
              f"{status}/{st['status']}")
        check("run_one never selects the requested cloud runtime",
              selected == ["ollama"], str(selected))


def test_unknown_kind_fails_cleanly():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        ledger.LEDGER_DIR = d
        ledger.EVENTS = d / "events.jsonl"
        ledger.SNAPSHOT = d / "snapshot.json"
        jid = ledger.create("no.such.kind", {"x": 1}, sensitivity="internal")
        claimed = ledger.claim("t1")
        dispatch.run_one(claimed)
        st = ledger.get(jid)
        check("an unregistered job kind fails non-retryably",
              st["status"] == "failed" and st.get("retryable") is False)


def test_running_cancellation_wins_over_completion():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        ledger.LEDGER_DIR = d
        ledger.EVENTS = d / "events.jsonl"
        ledger.SNAPSHOT = d / "snapshot.json"

        original_get = runtimes.get

        class CancellingStub:
            @staticmethod
            def run(*args, **kwargs):
                ledger.cancel(jid, by="tester", reason="not needed")
                check("runtime receives a cancellation callback",
                      callable(kwargs.get("cancel_check")))
                return RunResult(ok=True, text="too late", runtime="ollama")

        jid = ledger.create("echo.check", {}, sensitivity="internal")
        claimed = ledger.claim("t1")
        runtimes.get = lambda name: CancellingStub
        try:
            status = dispatch.run_one(claimed)
        finally:
            runtimes.get = original_get
        check("dispatcher reports a cancelled run", status == "cancelled")
        check("cancelled output cannot complete the job",
              ledger.get(jid)["status"] == "cancelled")


def test_provider_failure_can_fail_over_for_internal_jobs():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        ledger.LEDGER_DIR = d
        ledger.EVENTS = d / "events.jsonl"
        ledger.SNAPSHOT = d / "snapshot.json"

        selected = []
        original_runtime_get = runtimes.get
        original_job_get = dispatch.job_registry.get

        class Module:
            DEFAULT_RUNTIME = "claude"
            MODEL = "sonnet"
            CODEX_MODEL = None
            REVIEW_REQUIRED = False
            SCHEMA = None

            @staticmethod
            def build_prompt(payload):
                return "summarize public research"

            @staticmethod
            def fallback_runtime(runtime, error):
                return (
                    "codex"
                    if runtime == "claude" and "unable to connect to api" in error.lower()
                    else None
                )

        class ClaudeStub:
            @staticmethod
            def run(*args, **kwargs):
                selected.append(("claude-model", kwargs.get("model")))
                return RunResult(
                    ok=False,
                    error="API Error: Unable to connect to API (ConnectionRefused)",
                    runtime="claude",
                )

        class CodexStub:
            @staticmethod
            def run(*args, **kwargs):
                selected.append(("codex-model", kwargs.get("model")))
                return RunResult(ok=True, text="OK", runtime="codex")

        adapters = {"claude": ClaudeStub, "codex": CodexStub}
        runtimes.get = lambda name: selected.append(name) or adapters[name]
        dispatch.job_registry.get = lambda kind: Module
        jid = ledger.create(
            "test.failover",
            {"source": "public"},
            runtime="claude",
            sensitivity="internal",
        )
        try:
            claimed = ledger.claim("t1")
            status = dispatch.run_one(claimed)
            state = ledger.get(jid)
        finally:
            runtimes.get = original_runtime_get
            dispatch.job_registry.get = original_job_get

        check(
            "explicit provider failure fails over and completes",
            status == "completed" and state["status"] == "completed",
            f"{status}/{state['status']}",
        )
        check(
            "provider failure tries only the declared primary and fallback",
            selected == [
                "claude",
                ("claude-model", "sonnet"),
                "codex",
                ("codex-model", None),
            ],
            str(selected),
        )


def main() -> int:
    test_path_derived_sensitivity()
    test_guard_blocks_cloud_for_private()
    test_nested_payload_paths_are_seen()
    test_prose_that_mentions_a_private_path_is_not_a_path()
    test_private_jobs_auto_route_local()
    test_local_runtimes_allowlist()
    test_run_one_autoroutes_private_job()
    test_unknown_kind_fails_cleanly()
    test_running_cancellation_wins_over_completion()
    test_provider_failure_can_fail_over_for_internal_jobs()

    print()
    if FAIL:
        print(f"{len(FAIL)} FAILED: {', '.join(FAIL)}")
        return 1
    print(f"All {len(PASS)} dispatcher tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
