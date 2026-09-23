"""The /teams model picker's policy file and the dispatcher's use of it.

  python .claude/scripts/tests/test_model_policy.py
"""

import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import dispatch  # noqa: E402
import ledger  # noqa: E402
import runtimes  # noqa: E402
from runtimes import RunResult, capacity, failover, model_policy  # noqa: E402

PASS, FAIL = [], []


def check(label, cond, detail=""):
    (PASS if cond else FAIL).append(label)
    print(f"{'PASS' if cond else 'FAIL'} {label}{'' if cond or not detail else '  -> ' + detail}")


def test_policy_file():
    with tempfile.TemporaryDirectory() as d:
        saved = model_policy.POLICY_FILE
        model_policy.POLICY_FILE = Path(d) / "model-policy.json"
        try:
            check("empty policy answers None", model_policy.model_for("hr.packet_review", "claude") is None)
            model_policy.set_model("*", "claude", "fable")
            check("a runtime default applies to every kind",
                  model_policy.model_for("hr.packet_review", "claude") == "fable"
                  and model_policy.model_for("draft.reply", "claude") == "fable")
            check("the default is per runtime", model_policy.model_for("draft.reply", "codex") is None)
            model_policy.set_model("hr.packet_review", "claude", "opus")
            check("a kind pin beats the default",
                  model_policy.model_for("hr.packet_review", "claude") == "opus"
                  and model_policy.model_for("draft.reply", "claude") == "fable")
            model_policy.set_model("hr.packet_review", "claude", None)
            check("clearing a pin falls back to the default",
                  model_policy.model_for("hr.packet_review", "claude") == "fable"
                  and "hr.packet_review" not in model_policy.load()["kinds"])
            model_policy.set_model("*", "claude", "")
            check("clearing the default restores as-coded", model_policy.model_for("draft.reply", "claude") is None)
            for bad in ("opus; ls", "a b", "-x"):
                try:
                    model_policy.set_model("draft.reply", "claude", bad)
                    check(f"rejects {bad!r} as a model name", False)
                except model_policy.PolicyError:
                    check(f"rejects {bad!r} as a model name", True)
            try:
                model_policy.set_model("draft.reply", "gemini", "x")
                check("rejects an unknown runtime", False)
            except model_policy.PolicyError:
                check("rejects an unknown runtime", True)
            check("every claude choice has a stepdown rung or is the bottom",
                  all(m in failover.MODEL_BACKUP["claude"] or m in ("sonnet", "haiku")
                      for m in model_policy.CHOICES["claude"]))
        finally:
            model_policy.POLICY_FILE = saved


def test_dispatch_uses_policy():
    """The override reaches the runtime call, per runtime, and is asked again on failover."""
    with tempfile.TemporaryDirectory() as d:
        saved_policy = model_policy.POLICY_FILE
        model_policy.POLICY_FILE = Path(d) / "model-policy.json"
        ledger.LEDGER_DIR = Path(d) / "ledger"
        ledger.EVENTS = ledger.LEDGER_DIR / "events.jsonl"
        ledger.SNAPSHOT = ledger.LEDGER_DIR / "snapshot.json"
        capacity.STATE_FILE = Path(d) / "runtime-capacity.json"
        capacity.SNAPSHOT_FILE = Path(d) / "usage-limits.json"
        capacity.REFRESH_ENABLED = False
        seen = []

        class Stub:
            def __init__(self, name, ok=True):
                self.name, self.ok = name, ok

            def run(self, prompt, **kw):
                seen.append((self.name, kw.get("model")))
                return RunResult(ok=self.ok, runtime=self.name, model=kw.get("model") or "",
                                 text="{}", data={} if self.ok else None,
                                 error="" if self.ok else "usage limit reached")

        saved_get = runtimes.get
        # The counterpart hop checks that the codex CLI is installed; this
        # machine may not have it, and the policy lookup is what is under test.
        saved_available = failover.runtime_available
        failover.runtime_available = lambda name: True
        try:
            model_policy.set_model("*", "claude", "fable")
            model_policy.set_model("echo.check", "codex", "gpt-5")
            runtimes.get = lambda name: Stub(name)
            jid = ledger.create("echo.check", {"text": "hi"}, runtime="claude", sensitivity="internal")
            job = ledger.claim_job(jid, "t")
            dispatch.run_one(job)
            check("the claude call carries the policy model", bool(seen) and seen[-1] == ("claude", "fable"),
                  str(seen))

            seen.clear()
            runtimes.get = lambda name: Stub(name, ok=(name != "claude"))
            jid = ledger.create("echo.check", {"text": "hi"}, runtime="claude", sensitivity="internal")
            job = ledger.claim_job(jid, "t")
            dispatch.run_one(job)
            check("a failover hop asks the policy for the new runtime",
                  seen[0][0] == "claude" and seen[-1] == ("codex", "gpt-5"), str(seen))
        finally:
            runtimes.get = saved_get
            failover.runtime_available = saved_available
            model_policy.POLICY_FILE = saved_policy


def main():
    for fn in (test_policy_file, test_dispatch_uses_policy):
        fn()
    total = len(PASS) + len(FAIL)
    print(f"\n{len(PASS)}/{total} model-policy tests passed." if not FAIL
          else f"\n{len(FAIL)} of {total} model-policy tests FAILED.")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
