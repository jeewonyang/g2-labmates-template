"""The background scripts must run on subscriptions, not on API credit.

Two properties, both of which regressed silently once already:

  1. No script imports claude_agent_sdk directly. Every model call goes through
     runtimes/claude_rt, which prefers `claude -p` and its subscription login.
     A direct SDK import is a call billed to ANTHROPIC_API_KEY.
  2. A subscription run records $0. The CLIs report a `total_cost_usd`, but it
     is the API-equivalent value, not money spent. Recording it as spend made
     the usage panel claim the owner was paying for work their subscription
     already covers - and left no way to see the routing was working.

Plain-python, no pytest - matches test_ledger.py.

  python .claude/scripts/tests/test_subscription_billing.py
"""

import json
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"{'PASS' if cond else 'FAIL'} {name}{'' if cond else '  -> ' + detail}")


# The scripts that used to build their own ClaudeAgentOptions.
BACKGROUND = ("heartbeat.py", "guardrail.py", "memory_reflect.py",
              "memory_flush.py")


def test_no_direct_sdk_imports():
    # runtimes.failover.run_text() is the no-tools entry point (guardrail,
    # memory flush): it calls claude_rt first and only then the local model, so
    # reaching it still means reaching the subscription CLI.
    failover_src = (SCRIPTS / "runtimes" / "failover.py").read_text(
        encoding="utf-8")
    check("the failover helper itself routes through the claude runtime",
          "claude_rt" in failover_src)
    for name in BACKGROUND:
        src = (SCRIPTS / name).read_text(encoding="utf-8")
        check(f"{name} does not import the SDK directly",
              "claude_agent_sdk" not in src)
        check(f"{name} goes through the claude runtime",
              "claude_rt" in src or "failover" in src)


def test_runtime_marks_cli_runs_as_subscription():
    from runtimes import claude_rt
    src = (SCRIPTS / "runtimes" / "claude_rt.py").read_text(encoding="utf-8")
    cli_block = src.split("def _run_cli")[1].split("\ndef ")[0]
    check("the CLI path marks its result as subscription-billed",
          "subscription=True" in cli_block)
    check("the CLI path strips a stale API key so the login is used",
          'env.pop("ANTHROPIC_API_KEY", None)' in cli_block)
    check("the SDK fallback stays opt-in",
          claude_rt.ALLOW_SDK_FALLBACK is False
          or "SECONDBRAIN_ALLOW_SDK_FALLBACK" in src)

    codex = (SCRIPTS / "runtimes" / "codex_rt.py").read_text(encoding="utf-8")
    check("codex runs are marked subscription-billed too",
          "subscription=True" in codex)


def test_subscription_rows_bill_zero():
    import usage_ledger
    with tempfile.TemporaryDirectory() as td:
        usage_ledger.LEDGER = Path(td) / "usage.jsonl"

        usage_ledger.record_usage(
            model="sonnet", input_tokens=10, output_tokens=20,
            cost_usd=0.42, source="test", subscription=True)
        usage_ledger.record_usage(
            model="sonnet", input_tokens=10, output_tokens=20,
            cost_usd=0.42, source="test", subscription=False)

        rows = [json.loads(line) for line
                in usage_ledger.LEDGER.read_text(encoding="utf-8").splitlines()
                if line.strip()]
        check("both rows were written", len(rows) == 2, str(len(rows)))
        sub, api = rows[0], rows[1]

        check("a subscription run bills $0", sub["cost_usd"] == 0.0,
              str(sub.get("cost_usd")))
        check("a subscription run keeps the API-equivalent figure",
              sub.get("notional_cost_usd") == 0.42,
              str(sub.get("notional_cost_usd")))
        check("a subscription run is labelled",
              sub.get("billing") == "subscription")
        check("a subscription run still records tokens",
              sub["input_tokens"] == 10 and sub["output_tokens"] == 20)

        check("a real API run still bills its cost", api["cost_usd"] == 0.42,
              str(api.get("cost_usd")))
        check("a real API run carries no subscription label",
              "billing" not in api and "notional_cost_usd" not in api)


def test_no_tools_callers_replace_the_persona():
    """A classifier layered onto the assistant persona answers its input.

    Handed an email to judge, the guardrail replied to the email instead of
    returning a verdict. `--system-prompt` replaces; `--append-system-prompt`
    layers. No-tools callers need replacement.
    """
    guardrail = (SCRIPTS / "guardrail.py").read_text(encoding="utf-8")
    flush = (SCRIPTS / "memory_flush.py").read_text(encoding="utf-8")
    # Both now call failover.run_text(), which owns the replacement (and the
    # empty tool list) on the Claude path so the two callers cannot drift
    # apart. Assert it where it lives, then that they go through it.
    helper = (SCRIPTS / "runtimes" / "failover.py").read_text(encoding="utf-8")
    run_text = helper.split("def run_text")[1]
    check("the no-tools helper replaces the system prompt",
          'system_mode="replace"' in run_text)
    check("the no-tools helper grants no tools",
          "allowed_tools=[]" in run_text)
    check("the guardrail replaces the system prompt",
          'system_mode="replace"' in guardrail or "failover.run_text" in guardrail)
    check("memory flush replaces the system prompt",
          'system_mode="replace"' in flush or "failover.run_text" in flush)

    rt = (SCRIPTS / "runtimes" / "claude_rt.py").read_text(encoding="utf-8")
    check("replace mode maps to --system-prompt",
          '"--system-prompt" if system_mode == "replace"' in rt)
    check("Advisor mode survives replacement",
          "_system_prompt(schema, system)" in rt)


def main() -> int:
    test_no_direct_sdk_imports()
    test_runtime_marks_cli_runs_as_subscription()
    test_subscription_rows_bill_zero()
    test_no_tools_callers_replace_the_persona()

    print()
    if FAIL:
        print(f"{len(FAIL)} FAILED: {', '.join(FAIL)}")
        return 1
    print(f"All {len(PASS)} subscription-billing tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
