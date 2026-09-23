"""Runtime adapters: one uniform interface over three very different engines.

    run(prompt, *, schema, cwd, timeout, model=None) -> RunResult

  claude - judgment, drafting in their voice, code. Python Agent SDK (the `claude`
           CLI is not on PATH on this machine). Cloud.
  codex  - structured extraction and independent second opinions. `codex exec`
           with --output-schema gives JSON-Schema-validated output. Cloud.
  ollama - bulk classification and anything marked `private`. Local, free.

LOCAL_RUNTIMES is the allowlist the dispatcher's sensitivity guard checks. A job
marked `private` may only run on a runtime named here. Adding a cloud runtime to
this set would silently break the confidentiality boundary - don't.
"""

from dataclasses import dataclass, field

LOCAL_RUNTIMES = frozenset({"ollama"})
ALL_RUNTIMES = ("claude", "codex", "ollama")


@dataclass
class RunResult:
    ok: bool
    data: dict | None = None      # parsed structured output, when a schema was given
    text: str = ""                # raw final message
    error: str = ""
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    model: str = ""
    runtime: str = ""
    # True when the run authenticated with one of the owner's subscriptions
    # (`claude -p`, `codex exec`) rather than a metered API key. Those CLIs
    # still report a `total_cost_usd`, but it is the API-equivalent value, not
    # money leaving their account - so the usage ledger records it as notional
    # and bills $0. Without this the dashboard shows subscription work as
    # spend, and there is no way to see that the routing is working.
    subscription: bool = False
    meta: dict = field(default_factory=dict)


def get(name: str):
    """Return the adapter module for a runtime name."""
    if name == "claude":
        from . import claude_rt
        return claude_rt
    if name == "codex":
        from . import codex_rt
        return codex_rt
    if name == "ollama":
        from . import ollama_rt
        return ollama_rt
    raise ValueError(f"unknown runtime: {name!r} (expected one of {ALL_RUNTIMES})")


def is_local(name: str) -> bool:
    return name in LOCAL_RUNTIMES
