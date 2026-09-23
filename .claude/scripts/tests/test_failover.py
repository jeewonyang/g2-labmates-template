"""Backup routing: does a spent subscription move work, and only work it may move?

Two properties matter more than the convenience:
  - a private job never reaches a second cloud provider when the first is out
  - only a capacity/availability failure reroutes; a refusal, a bad schema, or
    a timeout still fails loudly

Run: python .claude/scripts/tests/test_failover.py
"""

import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import json
import os
from datetime import timedelta

import dispatch  # noqa: E402
import ledger  # noqa: E402
import runtimes  # noqa: E402
from runtimes import RunResult, capacity, failover  # noqa: E402
from shared import now  # noqa: E402

PASS, FAIL = [], []

CAPACITY_ERROR = ("claude CLI exit 1: Claude usage limit reached. Your limit "
                  "will reset at 3pm.")
# Verbatim from the daily logs (2026-08-10, 08-19): what the CLI actually says
# when the five-hour window is spent. Until 2026-09-16 nothing matched it.
SESSION_LIMIT_ERROR = ("claude CLI exit 1: You've hit your session limit · "
                       "resets 10pm (America/Los_Angeles)")
SPEND_LIMIT_ERROR = ("claude CLI exit 1: You've hit your org's monthly spend "
                     "limit · run /usage-credits to ask your admin for a higher limit")
UNAVAILABLE_ERROR = "claude runtime unavailable: the `claude` CLI is not on PATH"


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"{'PASS' if cond else 'FAIL'} {name}{'' if cond else '  -> ' + detail}")


def test_capacity_errors_are_recognized():
    for error in (
        CAPACITY_ERROR,
        SESSION_LIMIT_ERROR,
        SPEND_LIMIT_ERROR,
        "You've hit your weekly limit · resets Sep 20, 3pm",
        "codex exit 1: 429 Too Many Requests",
        "You've hit your weekly limit for Opus. Try again later.",
        "API Error: 529 overloaded_error",
        "claude runtime unavailable: the `claude` CLI is not on PATH",
        "codex CLI not found on PATH",
        "API Error: Unable to connect to API (ConnectionRefused)",
        # the exact text a stale headless login produced on 2026-08-23/24;
        # neither "authentication" nor "not logged in" is a substring of it
        "claude CLI exit 1: Failed to authenticate: OAuth session expired "
        "and could not be refreshed",
    ):
        check(f"capacity: {error[:44]!r}", failover.is_capacity_error(error), error)

    for error in (
        "structured output did not parse: Expecting value: line 1 column 1",
        "claude CLI timed out after 900s",
        "codex timed out after 429s",          # the number is not a status code
        "build_prompt failed: KeyError('source')",
        "I can't help with this request",
        "",
    ):
        check(f"not capacity: {error[:44]!r}",
              not failover.is_capacity_error(error), error)

    # The split the dispatcher defers on: time fixes a spent window, not a
    # missing CLI or an expired login.
    for error in (CAPACITY_ERROR, SESSION_LIMIT_ERROR, SPEND_LIMIT_ERROR,
                  "codex exit 1: 429 Too Many Requests",
                  "Your workspace is out of credits."):
        check(f"rate-limited: {error[:40]!r}",
              failover.is_rate_limited(error) and not failover.is_unavailable(error),
              error)
    for error in (UNAVAILABLE_ERROR,
                  "claude CLI exit 1: Failed to authenticate: OAuth session expired",
                  "codex CLI not found on PATH"):
        check(f"unavailable, not rate-limited: {error[:32]!r}",
              failover.is_unavailable(error) and not failover.is_rate_limited(error),
              error)


def test_ollama_has_no_cloud_counterpart():
    check("a local job never fails over to the cloud",
          failover.counterpart("ollama", error=CAPACITY_ERROR) is None)
    check("claude's counterpart is codex",
          failover.counterpart("claude", error=CAPACITY_ERROR,
                               check_available=False) == "codex")
    check("codex's counterpart is claude",
          failover.counterpart("codex", error=CAPACITY_ERROR,
                               check_available=False) == "claude")
    check("a non-capacity failure earns no counterpart",
          failover.counterpart("claude", error="structured output did not parse",
                               check_available=False) is None)
    check("an already-tried runtime is not offered again",
          failover.counterpart("claude", error=CAPACITY_ERROR,
                               exclude={"codex"}, check_available=False) is None)


def test_model_stepdown_stays_inside_the_provider():
    check("opus steps down to sonnet",
          failover.model_backup("claude", "opus") == "sonnet")
    check("the pinned ids step down too",
          failover.model_backup("claude", "claude-opus-5") == "claude-sonnet-5")
    check("sonnet has no rung below it",
          failover.model_backup("claude", "sonnet") is None)
    check("codex model choice stays with their CLI config",
          failover.model_backup("codex", "gpt-5.6-sol") is None)


def _ledger_in(tmp: Path):
    ledger.LEDGER_DIR = tmp
    ledger.EVENTS = tmp / "events.jsonl"
    ledger.SNAPSHOT = tmp / "snapshot.json"


def _capacity_in(tmp: Path):
    """Point the breaker and the usage snapshot at a temp dir, no network."""
    capacity.STATE_FILE = tmp / "runtime-capacity.json"
    capacity.SNAPSHOT_FILE = tmp / "usage-limits.json"
    capacity.REFRESH_ENABLED = False


def _write_snapshot(tmp: Path, provider_windows: dict, *, age=timedelta(0)):
    """A usage-limits.json in the shape usage_limits.py writes."""
    stamp = (now() - age).isoformat(timespec="seconds")
    providers = []
    for key, windows in provider_windows.items():
        providers.append({
            "key": key, "label": key.title(), "ok": True, "error": None,
            "freshness": "live", "observed_at": stamp,
            "windows": [
                {"id": wid, "label": wid, "used_percent": 100 - rem,
                 "remaining_percent": rem,
                 "resets_at": resets.isoformat(timespec="seconds") if resets else None}
                for wid, rem, resets in windows
            ],
        })
    (tmp / "usage-limits.json").write_text(
        json.dumps({"generated_at": stamp, "providers": providers}), encoding="utf-8")


class _Module:
    KIND = "test.capacity"
    DEFAULT_RUNTIME = "claude"
    SENSITIVITY = "internal"
    REVIEW_REQUIRED = False
    SCHEMA = None
    MODEL = "opus"

    @staticmethod
    def build_prompt(payload):
        return "do the internal thing"


def _dispatch_once(module, payload, sensitivity, adapters, *,
                   counterpart_available=True, state_dir: Path | None = None,
                   setup=None):
    """Run one job through the real dispatcher against stubbed adapters.

    `state_dir` shares the ledger and breaker state across calls, so a test
    can show what the *second* job sees after the first tripped the breaker.
    `setup(tmp)` runs before the job is created (to write a usage snapshot).
    """
    order = []
    originals = (runtimes.get, dispatch.job_registry.get,
                 failover.runtime_available)

    def go(tmp: Path):
        _ledger_in(tmp)
        _capacity_in(tmp)
        if setup:
            setup(tmp)
        runtimes.get = lambda name: order.append(name) or adapters[name]
        dispatch.job_registry.get = lambda kind: module
        failover.runtime_available = lambda name: counterpart_available
        jid = ledger.create(module.KIND, payload,
                            runtime=module.DEFAULT_RUNTIME,
                            sensitivity=sensitivity)
        try:
            status = dispatch.run_one(ledger.claim("t"))
            state = ledger.get(jid)
        finally:
            (runtimes.get, dispatch.job_registry.get,
             failover.runtime_available) = originals
        return status, state, order

    if state_dir is not None:
        return go(state_dir)
    with tempfile.TemporaryDirectory() as td:
        return go(Path(td))


def _stub(ok, error="", runtime=""):
    class Stub:
        @staticmethod
        def run(*args, **kwargs):
            return RunResult(ok=ok, text="OK" if ok else "", error=error,
                             runtime=runtime)
    return Stub


def test_spent_subscription_fails_over_to_the_other_provider():
    status, state, order = _dispatch_once(
        _Module, {"source": "public"}, "internal",
        {"claude": _stub(False, CAPACITY_ERROR, "claude"),
         "codex": _stub(True, runtime="codex")})
    check("an internal job survives a spent Claude subscription",
          status == "completed" and state["status"] == "completed",
          f"{status}/{state['status']}")
    check("it tried claude and then codex, in that order",
          order == ["claude", "codex"], str(order))


def test_private_job_never_reaches_a_second_cloud():
    class Private(_Module):
        KIND = "test.private"
        DEFAULT_RUNTIME = "ollama"
        SENSITIVITY = "private"

    reached = []

    class Cloud:
        @staticmethod
        def run(*args, **kwargs):
            reached.append("cloud")
            return RunResult(ok=True, text="leaked", runtime="codex")

    status, state, order = _dispatch_once(
        Private, {"path": "VAULT/Confidential/20_Areas/Immigration/notes.md"},
        "private",
        {"ollama": _stub(False, CAPACITY_ERROR, "ollama"),
         "codex": Cloud, "claude": Cloud})
    check("a private job fails rather than borrowing a cloud provider",
          status == "failed" and not reached, f"{status}/{reached}")
    check("only the local runtime was ever asked",
          order == ["ollama"], str(order))


def test_non_capacity_failure_does_not_reroute():
    status, _, order = _dispatch_once(
        _Module, {"source": "public"}, "internal",
        {"claude": _stub(False, "structured output did not parse: line 1",
                         "claude"),
         "codex": _stub(True, runtime="codex")})
    check("a parse failure fails the job instead of spending a second provider",
          status == "failed" and order == ["claude"], f"{status}/{order}")


def test_both_providers_out_defers_until_the_soonest_reset():
    with tempfile.TemporaryDirectory() as td:
        status, state, order = _dispatch_once(
            _Module, {"source": "public"}, "internal",
            {"claude": _stub(False, CAPACITY_ERROR, "claude"),
             "codex": _stub(False, "codex exit 1: 429 Too Many Requests", "codex")},
            state_dir=Path(td))
        check("exhausting both providers defers the job instead of failing it",
              status == "deferred" and state["status"] == "created"
              and order == ["claude", "codex"],
              f"{status}/{state['status']}/{order}")
        check("the deferred job carries a not_before in the future",
              ledger.is_waiting(state), str(state.get("not_before")))
        check("the recorded reason names every runtime tried",
              "claude" in (state.get("defer_reason") or "")
              and "codex" in (state.get("defer_reason") or ""),
              str(state.get("defer_reason")))
        check("the breaker is tripped for both providers",
              set(capacity.breaker_status()) == {"claude", "codex"},
              str(capacity.breaker_status()))


def test_unavailable_provider_still_fails_loudly():
    status, state, order = _dispatch_once(
        _Module, {"source": "public"}, "internal",
        {"claude": _stub(False, UNAVAILABLE_ERROR, "claude"),
         "codex": _stub(False, "codex CLI not found on PATH", "codex")})
    check("a missing CLI is not something a reset fixes: the job fails",
          status == "failed" and order == ["claude", "codex"],
          f"{status}/{order}")
    check("and nothing is tripped for it",
          capacity.breaker_status() == {}, str(capacity.breaker_status()))


def test_session_limit_wording_reroutes_and_trips():
    with tempfile.TemporaryDirectory() as td:
        status, state, order = _dispatch_once(
            _Module, {"source": "public"}, "internal",
            {"claude": _stub(False, SESSION_LIMIT_ERROR, "claude"),
             "codex": _stub(True, runtime="codex")}, state_dir=Path(td))
        check("the CLI's real session-limit text now earns the counterpart",
              status == "completed" and order == ["claude", "codex"],
              f"{status}/{order}")
        tripped = capacity.breaker_status().get("claude") or {}
        until = capacity._parse_dt(tripped.get("until"))
        check("and trips claude until the 10pm reset the message names",
              until is not None and until.hour == 22 and until.minute == 0,
              str(tripped))


def test_a_tool_writing_kind_opts_out():
    class ToolWriter(_Module):
        KIND = "test.toolwriter"
        ALLOW_RUNTIME_FAILOVER = False

    status, state, order = _dispatch_once(
        ToolWriter, {"source": "public"}, "internal",
        {"claude": _stub(False, CAPACITY_ERROR, "claude"),
         "codex": _stub(True, runtime="codex")})
    check("a kind that writes through its own tools is not moved",
          status == "deferred" and order == ["claude"], f"{status}/{order}")
    check("it waits for the reset rather than skipping the day",
          ledger.is_waiting(state), str(state.get("not_before")))


def test_web_search_jobs_keep_web_access_after_failover():
    seen = {}

    class Websearch(_Module):
        KIND = "test.websearch"
        DEFAULT_RUNTIME = "codex"
        WEB_SEARCH = True
        ALLOWED_TOOLS = []

    class ClaudeStub:
        @staticmethod
        def run(*args, **kwargs):
            seen.update(kwargs)
            return RunResult(ok=True, text="OK", runtime="claude")

    status, _, _ = _dispatch_once(
        Websearch, {"source": "public"}, "internal",
        {"codex": _stub(False, CAPACITY_ERROR, "codex"), "claude": ClaudeStub})
    tools = seen.get("allowed_tools") or []
    check("a web-search job that fails over to claude can still cite sources",
          status == "completed" and "WebSearch" in tools and "WebFetch" in tools,
          f"{status}/{tools}")
    check("and gains nothing else",
          set(tools) == {"WebSearch", "WebFetch"}, str(tools))


def test_module_hook_still_wins():
    class Hooked(_Module):
        KIND = "test.hooked"

        @staticmethod
        def fallback_runtime(runtime, error):
            return "codex" if runtime == "claude" else None

    status, _, order = _dispatch_once(
        Hooked, {"source": "public"}, "internal",
        {"claude": _stub(False, "I can't help with this (see /legal/aup)",
                         "claude"),
         "codex": _stub(True, runtime="codex")},
        # The generic rule would decline this error; the kind's own hook is
        # what routes a content refusal, and it must still be consulted.
        counterpart_available=False)
    check("a kind's own fallback_runtime still routes content refusals",
          status == "completed" and order == ["claude", "codex"],
          f"{status}/{order}")


def test_kill_switch_restores_fail_fast():
    import os
    os.environ["SECONDBRAIN_DISABLE_FAILOVER"] = "1"
    try:
        status, _, order = _dispatch_once(
            _Module, {"source": "public"}, "internal",
            {"claude": _stub(False, CAPACITY_ERROR, "claude"),
             "codex": _stub(True, runtime="codex")})
        check("SECONDBRAIN_DISABLE_FAILOVER=1 turns backup routing off",
              status == "failed" and order == ["claude"], f"{status}/{order}")
        check("and deferral and the breaker with it",
              capacity.breaker_status() == {}, str(capacity.breaker_status()))
        check("and turns model stepdown off with it",
              failover.model_backup("claude", "opus") is None)
    finally:
        os.environ.pop("SECONDBRAIN_DISABLE_FAILOVER", None)


def test_claude_runtime_steps_the_model_down_once():
    from runtimes import claude_rt

    tried = []
    original_mode, original_cli = claude_rt.mode, claude_rt._run_cli
    claude_rt.mode = lambda: "cli"

    def fake_cli(prompt, schema, cwd, timeout, model, tools, **kwargs):
        tried.append(model)
        return RunResult(ok=False, runtime="claude", model=model,
                         error=CAPACITY_ERROR)

    claude_rt._run_cli = fake_cli
    try:
        result = claude_rt.run("hi", model="opus", timeout=5)
        check("opus retries once on sonnet and then stops",
              tried == ["opus", "sonnet"], str(tried))
        check("the failure names the model that was actually out",
              "opus" in (result.error or ""), str(result.error))

        tried.clear()
        claude_rt.run("hi", model="opus", timeout=5, model_fallback=False)
        check("model_fallback=False keeps a pinned model pinned",
              tried == ["opus"], str(tried))

        tried.clear()

        def parse_failure(prompt, schema, cwd, timeout, model, tools, **kwargs):
            tried.append(model)
            return RunResult(ok=False, runtime="claude", model=model,
                             error="structured output did not parse")

        claude_rt._run_cli = parse_failure
        claude_rt.run("hi", model="opus", timeout=5)
        check("a parse failure does not burn the sonnet allowance",
              tried == ["opus"], str(tried))
    finally:
        claude_rt.mode, claude_rt._run_cli = original_mode, original_cli


def test_reset_time_parsing():
    ref = now().replace(hour=12, minute=0, second=0, microsecond=0)
    cases = [
        (SESSION_LIMIT_ERROR, (22, 0), 0),
        ("Claude usage limit reached. Your limit will reset at 3pm.", (15, 0), 0),
        ("resets 9:30am (America/Los_Angeles)", (9, 30), 1),   # already passed -> tomorrow
        ("limit reached, resets 14:15", (14, 15), 0),
    ]
    for text, (hh, mm), days in cases:
        got = capacity.parse_reset(text, reference=ref)
        want = (ref + timedelta(days=days)).replace(hour=hh, minute=mm)
        check(f"parses {text[:36]!r}", got == want, f"{got} != {want}")
    epoch = int((ref + timedelta(hours=3)).timestamp())
    got = capacity.parse_reset(f"Claude AI usage limit reached|{epoch}", reference=ref)
    check("parses the pipe-epoch form", got == ref + timedelta(hours=3), str(got))
    got = capacity.parse_reset("You've hit your weekly limit · resets Sep 20, 3pm",
                               reference=ref)
    check("parses a dated weekly reset",
          got is not None and (got.month, got.day, got.hour, got.minute) == (9, 20, 15, 0)
          and got > ref, str(got))
    got = capacity.parse_reset("429 Too Many Requests, try again in 45 minutes",
                               reference=ref)
    check("parses a relative delay", got == ref + timedelta(minutes=45), str(got))
    check("a message with no time yields None",
          capacity.parse_reset("structured output did not parse") is None)
    check("a bare status code yields None",
          capacity.parse_reset("codex exit 1: 429 Too Many Requests") is None)

    with tempfile.TemporaryDirectory() as td:
        _capacity_in(Path(td))
        got = capacity.reset_time_for("claude", "codex exit 1: 429 Too Many Requests")
        check("no time anywhere -> the default cooldown",
              timedelta(minutes=29) < got - now() <= capacity.DEFAULT_COOLDOWN,
              str(got - now()))
        got = capacity.reset_time_for("claude", SESSION_LIMIT_ERROR)
        check("the error's own reset wins over the default",
              got.hour == 22 and got > now(), str(got))


def test_breaker_short_circuits_the_rest_of_the_drain():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        adapters = {"claude": _stub(False, SESSION_LIMIT_ERROR, "claude"),
                    "codex": _stub(True, runtime="codex")}
        status, _, order = _dispatch_once(_Module, {"n": 1}, "internal",
                                          adapters, state_dir=tmp)
        check("first job: claude fails, codex completes it",
              status == "completed" and order == ["claude", "codex"], str(order))
        status, _, order = _dispatch_once(_Module, {"n": 2}, "internal",
                                          adapters, state_dir=tmp)
        check("second job: claude is never called while the breaker is tripped",
              status == "completed" and order == ["codex"], str(order))

        # Both out: the third job is parked without a single model call.
        adapters["codex"] = _stub(False, "codex exit 1: 429 Too Many Requests",
                                  "codex")
        status, state, order = _dispatch_once(_Module, {"n": 3}, "internal",
                                              adapters, state_dir=tmp)
        check("third job: codex trips too and the job is deferred",
              status == "deferred" and order == ["codex"], f"{status}/{order}")
        status, state, order = _dispatch_once(_Module, {"n": 4}, "internal",
                                              adapters, state_dir=tmp)
        check("fourth job: deferred with no call at all",
              status == "deferred" and order == [], f"{status}/{order}")
        check("it waits for the soonest of the two resets (codex's 30 min), "
              "not claude's 10pm",
              ledger.is_waiting(state)
              and capacity._parse_dt(state["not_before"]) - now()
              <= capacity.DEFAULT_COOLDOWN,
              str(state.get("not_before")))
        check("a waiting job is not handed out again",
              ledger.claim("t2") is None)


def test_tripped_breaker_with_no_counterpart_defers_without_a_call():
    class ToolWriter(_Module):
        KIND = "test.toolwriter"
        ALLOW_RUNTIME_FAILOVER = False

    def tripped(tmp):
        capacity.trip("claude", now() + timedelta(hours=2), "test trip")

    status, state, order = _dispatch_once(
        ToolWriter, {"source": "public"}, "internal",
        {"claude": _stub(True, runtime="claude"),
         "codex": _stub(True, runtime="codex")}, setup=tripped)
    check("a tripped runtime with no counterpart parks the job untouched",
          status == "deferred" and order == [], f"{status}/{order}")
    check("until the breaker's reset",
          ledger.is_waiting(state)
          and abs((capacity._parse_dt(state["not_before"]) - now())
                  - timedelta(hours=2)) < timedelta(minutes=1),
          str(state.get("not_before")))
    check("ollama is never tripped",
          capacity.trip("ollama", now() + timedelta(hours=1), "x") is None
          and capacity.unavailable_until("ollama") == (None, None))


def test_private_job_is_not_rerouted_by_a_tripped_breaker():
    class Private(_Module):
        KIND = "test.private"
        DEFAULT_RUNTIME = "ollama"

    reached = []

    class Cloud:
        @staticmethod
        def run(*args, **kwargs):
            reached.append("cloud")
            return RunResult(ok=True, text="leaked", runtime="codex")

    def tripped(tmp):
        capacity.trip("claude", now() + timedelta(hours=2), "test trip")
        capacity.trip("codex", now() + timedelta(hours=2), "test trip")

    status, _, order = _dispatch_once(
        Private, {"path": "VAULT/Confidential/20_Areas/Immigration/notes.md"},
        "private",
        {"ollama": _stub(True, runtime="ollama"), "codex": Cloud, "claude": Cloud},
        setup=tripped)
    check("a private job runs locally regardless of what the cloud breakers say",
          status == "completed" and order == ["ollama"] and not reached,
          f"{status}/{order}/{reached}")


def test_snapshot_marks_a_runtime_spent_before_the_call():
    def low_five_hour(tmp):
        _write_snapshot(tmp, {"claude": [
            ("five_hour", 2.0, now() + timedelta(hours=3)),
            ("seven_day", 60.0, now() + timedelta(days=4)),
        ]})

    status, _, order = _dispatch_once(
        _Module, {"source": "public"}, "internal",
        {"claude": _stub(True, runtime="claude"),
         "codex": _stub(True, runtime="codex")}, setup=low_five_hour)
    check("a five-hour window under the floor routes to codex pre-flight",
          status == "completed" and order == ["codex"], f"{status}/{order}")

    def healthy(tmp):
        _write_snapshot(tmp, {"claude": [
            ("five_hour", 40.0, now() + timedelta(hours=3)),
            ("seven_day_opus", 1.0, now() + timedelta(days=2)),
        ]})

    status, _, order = _dispatch_once(
        _Module, {"source": "public"}, "internal",
        {"claude": _stub(True, runtime="claude"),
         "codex": _stub(True, runtime="codex")}, setup=healthy)
    check("a spent Opus window alone does not move the runtime (model-level)",
          status == "completed" and order == ["claude"], f"{status}/{order}")

    def stale(tmp):
        _write_snapshot(tmp, {"claude": [
            ("five_hour", 0.0, now() + timedelta(hours=3)),
        ]}, age=timedelta(hours=2))

    status, _, order = _dispatch_once(
        _Module, {"source": "public"}, "internal",
        {"claude": _stub(True, runtime="claude"),
         "codex": _stub(True, runtime="codex")}, setup=stale)
    check("a two-hour-old snapshot is not trusted for routing",
          status == "completed" and order == ["claude"], f"{status}/{order}")


def test_preferred_model_reads_the_opus_window():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _capacity_in(tmp)
        _write_snapshot(tmp, {"claude": [
            ("seven_day_opus", 4.0, now() + timedelta(days=2)),
            ("five_hour", 80.0, now() + timedelta(hours=3)),
        ]})
        check("opus steps to sonnet when the Opus window is nearly spent",
              capacity.preferred_model("claude", "opus")[0] == "sonnet")
        check("fable steps all the way past opus to sonnet",
              capacity.preferred_model("claude", "fable")[0] == "sonnet")
        check("the pinned id steps to its pinned counterpart",
              capacity.preferred_model("claude", "claude-opus-5")[0]
              == "claude-sonnet-5")
        check("sonnet is left alone",
              capacity.preferred_model("claude", "sonnet") == ("sonnet", None))
        check("codex models are never touched",
              capacity.preferred_model("codex", "gpt-5.6-sol") == ("gpt-5.6-sol", None))
        reason = capacity.preferred_model("claude", "opus")[1] or ""
        check("the reason states the percentage", "4%" in reason, reason)

        _write_snapshot(tmp, {"claude": [
            ("seven_day_opus", 45.0, now() + timedelta(days=2)),
        ]})
        check("a healthy Opus window keeps opus",
              capacity.preferred_model("claude", "opus") == ("opus", None))

        _write_snapshot(tmp, {"claude": [
            ("seven_day_opus", 1.0, now() + timedelta(days=2)),
        ]}, age=timedelta(hours=1))
        check("a stale snapshot expresses no preference",
              capacity.preferred_model("claude", "opus") == ("opus", None))

        _write_snapshot(tmp, {"claude": [
            ("seven_day_opus", 1.0, now() + timedelta(days=2)),
        ]})
        os.environ["SECONDBRAIN_DISABLE_PREFLIGHT"] = "1"
        try:
            check("SECONDBRAIN_DISABLE_PREFLIGHT=1 turns the pre-flight off",
                  capacity.preferred_model("claude", "opus") == ("opus", None))
        finally:
            os.environ.pop("SECONDBRAIN_DISABLE_PREFLIGHT", None)


def test_claude_runtime_starts_on_the_preferred_model():
    from runtimes import claude_rt

    tried = []
    original_mode, original_cli = claude_rt.mode, claude_rt._run_cli
    claude_rt.mode = lambda: "cli"

    def fake_cli(prompt, schema, cwd, timeout, model, tools, **kwargs):
        tried.append(model)
        return RunResult(ok=True, text="OK", runtime="claude", model=model)

    claude_rt._run_cli = fake_cli
    try:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _capacity_in(tmp)
            _write_snapshot(tmp, {"claude": [
                ("seven_day_opus", 3.0, now() + timedelta(days=2)),
            ]})
            result = claude_rt.run("hi", model="opus", timeout=5)
            check("opus starts on sonnet when the snapshot says Opus is spent",
                  tried == ["sonnet"], str(tried))
            check("the result records where it started from",
                  result.meta.get("preflight_model_from") == "opus",
                  str(result.meta))
            tried.clear()
            claude_rt.run("hi", model="opus", timeout=5, model_fallback=False)
            check("a pinned model ignores the pre-flight",
                  tried == ["opus"], str(tried))
    finally:
        claude_rt.mode, claude_rt._run_cli = original_mode, original_cli


def test_a_job_that_keeps_circling_eventually_fails():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _ledger_in(tmp)
        _capacity_in(tmp)
        jid = ledger.create(_Module.KIND, {"n": 1}, runtime="claude",
                            sensitivity="internal")
        for _ in range(dispatch.MAX_DEFERRALS):
            ledger.claim("t")
            ledger.defer(jid, now() - timedelta(seconds=1), "past reset")
        check("deferrals are counted on the job",
              ledger.get(jid)["deferrals"] == dispatch.MAX_DEFERRALS)
        originals = (runtimes.get, dispatch.job_registry.get,
                     failover.runtime_available)
        runtimes.get = lambda name: _stub(False, SESSION_LIMIT_ERROR, name)
        dispatch.job_registry.get = lambda kind: _Module
        failover.runtime_available = lambda name: False
        try:
            status = dispatch.run_one(ledger.claim("t"))
        finally:
            (runtimes.get, dispatch.job_registry.get,
             failover.runtime_available) = originals
        state = ledger.get(jid)
        check("past MAX_DEFERRALS the job fails instead of circling",
              status == "failed" and "giving up" in (state.get("error") or ""),
              f"{status}/{state.get('error')}")


def main() -> int:
    test_capacity_errors_are_recognized()
    test_ollama_has_no_cloud_counterpart()
    test_model_stepdown_stays_inside_the_provider()
    test_spent_subscription_fails_over_to_the_other_provider()
    test_private_job_never_reaches_a_second_cloud()
    test_non_capacity_failure_does_not_reroute()
    test_both_providers_out_defers_until_the_soonest_reset()
    test_unavailable_provider_still_fails_loudly()
    test_session_limit_wording_reroutes_and_trips()
    test_a_tool_writing_kind_opts_out()
    test_web_search_jobs_keep_web_access_after_failover()
    test_module_hook_still_wins()
    test_kill_switch_restores_fail_fast()
    test_claude_runtime_steps_the_model_down_once()
    test_reset_time_parsing()
    test_breaker_short_circuits_the_rest_of_the_drain()
    test_tripped_breaker_with_no_counterpart_defers_without_a_call()
    test_private_job_is_not_rerouted_by_a_tripped_breaker()
    test_snapshot_marks_a_runtime_spent_before_the_call()
    test_preferred_model_reads_the_opus_window()
    test_claude_runtime_starts_on_the_preferred_model()
    test_a_job_that_keeps_circling_eventually_fails()

    print()
    if FAIL:
        print(f"{len(FAIL)} FAILED: {', '.join(FAIL)}")
        return 1
    print(f"All {len(PASS)} failover tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
