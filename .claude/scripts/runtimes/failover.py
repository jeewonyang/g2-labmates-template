"""Backup routing: what runs when the primary provider has nothing left to give.

Both cloud runtimes authenticate with a *subscription*, so the thing that stops
them is not money or a bad key - it is a rate window. When the owner runs out of
Claude capacity every claude-routed job fails; when they run out of ChatGPT
capacity every codex-routed job fails. The two limits are independent and reset
on different clocks, which is exactly what makes each a usable backup for the
other.

Two tiers, cheapest first:

  1. MODEL STEPDOWN, inside one provider. Claude's Opus allowance runs out
     before the overall allowance does, so opus -> sonnet keeps the same
     runtime, the same tools, and the same voice. There is deliberately no
     sonnet -> haiku rung: once the *overall* subscription window is exhausted
     no Claude model will answer, and pretending otherwise just burns a second
     failing call. See MODEL_BACKUP.
  2. PROVIDER COUNTERPART, across runtimes. claude <-> codex.

`ollama` has no counterpart and never appears as one. That is the
confidentiality boundary, not an oversight: a job lands on ollama either
because it is private (dispatch.derive_sensitivity forced it there) or because
a local model is enough for it. Promoting it to a cloud runtime on failure
would turn a capacity blip into a leak. Local runs cannot hit a usage limit
anyway - they hit VRAM, which a different provider does not fix.

Failover only fires for errors that mean *this provider cannot serve the
request*. A schema that did not parse, a prompt the model refused on content
grounds, or a job that timed out are all reasons to fail loudly - re-running
them elsewhere would hide a real defect and, for the timeout, double an already
long wall clock. Job kinds may still declare their own `fallback_runtime()` for
a narrow case (research_lit_review does, for provider-specific content
refusals); the dispatcher asks that hook first and only then falls back to the
generic capacity rule here.

Kill switch: SECONDBRAIN_DISABLE_FAILOVER=1 restores the old fail-fast
behaviour for every caller in one place.
"""

import os
import re

# Backup for a tool-free reasoning turn (guardrail, memory flush). Local, so it
# cannot hit a usage limit at all, and it holds a property those two callers
# depend on: ollama has no tools whatsoever, while `codex exec` is an agent
# with read access even under -s read-only. The guardrail exists to inspect
# text that may be a prompt injection and must not be able to act on it.
TEXT_BACKUP_RUNTIME = "ollama"

# Substrings that mean "the subscription window is spent". Matched only against
# error text this repo generated (RunResult.error), never against model output
# or file content, so a phrase appearing in a document cannot reroute a job.
CAPACITY_MARKERS = (
    "usage limit",
    "usage_limit",
    "limit reached",
    "limit exceeded",
    # The Claude CLI's own wording for a spent window, verbatim from the daily
    # logs: "You've hit your session limit · resets 10pm (America/Los_Angeles)"
    # and "You've hit your org's monthly spend limit". Neither contains
    # "usage limit" or "resets at", so until 2026-09-16 a spent *session*
    # window matched nothing here and failed every claude-routed job outright,
    # with neither the model stepdown nor the codex counterpart firing.
    "session limit",
    "spend limit",
    "weekly limit",
    "monthly limit",
    "hit your",
    "resets ",
    "rate limit",
    "rate_limit",
    "ratelimit",
    "too many requests",
    "quota",
    "insufficient_quota",
    "credit balance",
    "out of credits",
    "overloaded",
    "capacity",
    "try again later",
    "resets at",
    "upgrade to increase",
)

# Substrings that mean "this provider is not answering at all". A different
# provider is a genuine answer to these: the CLI is missing on this machine,
# the login went stale, or the API is unreachable.
UNAVAILABLE_MARKERS = (
    "runtime unavailable",
    "not found on path",
    "not on path",
    "failed to start",
    "unable to connect",
    "connectionrefused",
    "connection refused",
    "econnrefused",
    "unauthorized",
    "authentication",
    "failed to authenticate",
    "oauth session expired",
    "not logged in",
    "please run `claude login`",
    "service unavailable",
    "bad gateway",
)

# HTTP status codes worth failing over on, matched on word boundaries so that
# "timed out after 429s" cannot be mistaken for a 429. 500 is deliberately
# absent: it is too easy to hit inside an unrelated number.
_STATUS_RE = re.compile(r"\b(429|502|503|529)\b")

# One rung down inside a provider. Keys cover both the CLI aliases the job
# modules use ("opus") and the pinned model ids the portfolio planner uses.
MODEL_BACKUP = {
    "claude": {
        "fable": "opus",
        "claude-fable-5": "claude-opus-5",
        "opus": "sonnet",
        "opusplan": "sonnet",
        "claude-opus-5": "claude-sonnet-5",
    },
}

# The cross-provider pairing. Absence of "ollama" is load-bearing - see module
# docstring.
COUNTERPART = {
    "claude": "codex",
    "codex": "claude",
}


def enabled() -> bool:
    return os.environ.get("SECONDBRAIN_DISABLE_FAILOVER") != "1"


def is_rate_limited(error: str) -> bool:
    """True when the error says the subscription window is spent.

    This is the half of a capacity error that *time* fixes: the window resets
    and the same provider answers again. The dispatcher may defer a job on it
    (see runtimes/capacity.py). It is deliberately separate from
    `is_unavailable()`, because waiting for a reset does nothing for a missing
    CLI or an expired login.
    """
    lowered = (error or "").lower()
    if not lowered:
        return False
    if any(m in lowered for m in CAPACITY_MARKERS):
        return True
    return bool(_STATUS_RE.search(lowered))


def is_unavailable(error: str) -> bool:
    """True when the error says this provider is not answering at all."""
    lowered = (error or "").lower()
    return bool(lowered) and any(m in lowered for m in UNAVAILABLE_MARKERS)


def is_capacity_error(error: str) -> bool:
    """True when the error says this provider is spent or unreachable.

    Deliberately narrow. Everything it does not match fails the job, which is
    the behaviour every caller had before backup routing existed.
    """
    return is_rate_limited(error) or is_unavailable(error)


def model_backup(runtime: str, model: str | None) -> str | None:
    """The next model down inside the same runtime, or None."""
    if not enabled() or not model:
        return None
    return MODEL_BACKUP.get(runtime, {}).get(str(model).strip().lower())


def runtime_available(name: str) -> bool:
    """Ask the adapter whether it could run at all, without spawning it.

    Imports the adapter module directly rather than through `runtimes.get()`:
    a probe must not be observable as a dispatch, and `get()` is the seam the
    dispatcher tests replace.
    """
    try:
        if name == "claude":
            from . import claude_rt as adapter
        elif name == "codex":
            from . import codex_rt as adapter
        elif name == "ollama":
            from . import ollama_rt as adapter
        else:
            return False
    except ImportError:
        return False
    probe = getattr(adapter, "available", None)
    if probe is None:
        return True
    try:
        return bool(probe())
    except Exception:  # noqa: BLE001 - a probe failure is an unavailable runtime
        return False


def counterpart(runtime: str, *, error: str = "", exclude=(),
                check_available: bool = True) -> str | None:
    """The backup runtime for `runtime`, or None if there is not one.

    `error` is checked so that callers can pass a failure straight through:
    only a capacity/availability failure earns a second provider.
    """
    if not enabled():
        return None
    if error and not is_capacity_error(error):
        return None
    other = COUNTERPART.get(runtime)
    if not other or other in set(exclude):
        return None
    if check_available and not runtime_available(other):
        return None
    return other


def run_text(prompt: str, *, system: str, timeout: int = 300,
             model: str | None = None, invoked_by: str = "background",
             usage_source: str | None = None):
    """One tool-free turn on Claude, falling back to the local model.

    For the background callers whose whole job is to read text and return a
    verdict or a summary. They cannot use the cross-provider counterpart:
    `codex_rt.run()` takes no system prompt and codex is an agent with file
    access, which is exactly what a no-tools caller declined. ollama takes
    neither, so the system prompt is folded into the message - a local 8b model
    treats the two the same way regardless.

    Callers still see a normal RunResult and still decide what a failure means;
    both current callers already degrade safely on their own.
    """
    from . import RunResult, claude_rt, ollama_rt

    primary = claude_rt.run(
        prompt, system=system, allowed_tools=[], max_turns=1, model=model,
        timeout=timeout, invoked_by=invoked_by, usage_source=usage_source,
        system_mode="replace")
    if primary.ok or not enabled() or not is_capacity_error(primary.error):
        return primary
    if not runtime_available(TEXT_BACKUP_RUNTIME):
        return primary

    local = ollama_rt.run(f"{system}\n\n---\n\n{prompt}", timeout=timeout)
    if not local.ok:
        return RunResult(
            ok=False, runtime=local.runtime, model=local.model,
            error=f"{local.error} (after {primary.model} was unavailable: "
                  f"{primary.error})")
    local.meta = {**local.meta, "failed_over_from": "claude"}
    return local
