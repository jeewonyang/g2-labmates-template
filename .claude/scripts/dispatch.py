"""Dispatcher: claim jobs from the ledger and run them on the right runtime.

This is where the confidentiality boundary stops being documentation and
becomes enforcement. A job marked `private` may only run on a local runtime;
attempting otherwise fails the job loudly and is never retried.

Sensitivity is *derived from the payload path*, not trusted from the producer.
A job that claims `internal` but points at VAULT/Confidential/ or
VAULT/Finance/ is treated as private anyway. Finance source content is handled
locally; only sanitized triage decisions may reach a cloud verifier.

Usage:
  python .claude/scripts/dispatch.py --once                # drain what is ready
  python .claude/scripts/dispatch.py --watch --interval 30 # keep going
  python .claude/scripts/dispatch.py --once --kinds triage.classify
  python .claude/scripts/dispatch.py --once --runtimes ollama --max 200
  python .claude/scripts/dispatch.py --reap                # re-enqueue dead claims
  python .claude/scripts/dispatch.py --dry-run             # plan only, no calls
  python .claude/scripts/dispatch.py --capacity            # breakers + usage windows
  python .claude/scripts/dispatch.py --clear-breaker [claude|codex]

A spent subscription window is not a job failure (2026-09-16). When a cloud
runtime answers with a rate limit the dispatcher trips a per-runtime breaker
(runtimes/capacity.py), tries the counterpart, and if nothing is left *defers*
the job in the ledger until the reset the provider named; the next scheduled
drain after that time runs it. Jobs behind it skip the tripped runtime without
calling it. Missing CLIs, expired logins, refusals, parse failures, and
timeouts still fail loudly - a reset fixes none of those.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jobs as job_registry  # noqa: E402
import ledger  # noqa: E402
import runtimes  # noqa: E402
from runtimes import capacity, failover, model_policy, structured  # noqa: E402
from shared import REPO_ROOT, log_line, now  # noqa: E402

# Paths whose content must never reach a cloud model, whatever a job claims.
PRIVATE_PREFIXES = (
    "VAULT/Confidential/", "VAULT/Research-Private/", "VAULT/Finance/",
)
PRIVATE_SUBSTRINGS = ("/_private/",)
# Reserved for future absolute prohibitions. Finance was changed from forbidden
# to local-only by the owner on 2026-07-27.
FORBIDDEN_PREFIXES = ()

# ollama is capped at 1: the 4070 has 12 GB VRAM and qwen3:14b (9.3 GB) will not
# co-reside with the bge-m3 embedding model without spilling to CPU.
CONCURRENCY = {"ollama": 1, "claude": 2, "codex": 2}
DEFAULT_TIMEOUT = {"ollama": 300, "claude": 900, "codex": 900}

# A job that keeps meeting a spent window is deferred, not failed - but not
# forever. Eight deferrals is over a day of five-hour windows, or one weekly
# reset plus slack; past that the job fails with the last error so it shows
# up on /ops instead of silently circling.
MAX_DEFERRALS = 8


class SensitivityViolation(RuntimeError):
    """A private job was routed to a cloud runtime. Never retried."""


class ForbiddenPath(RuntimeError):
    """A job payload referenced an off-limits path."""


_PATH_FIELD_NAMES = {
    "path", "paths", "file", "files", "source_path", "source_paths",
    "destination", "destination_path", "recent_files", "changed_files", "docs",
}


def _path_field(name: str) -> bool:
    normalized = str(name or "").lower()
    return (
        normalized in _PATH_FIELD_NAMES
        or normalized.endswith(("_path", "_paths", "_file", "_files"))
    )


def _payload_paths(payload) -> list[str]:
    """Strings carried by path-bearing payload fields, normalized.

    Treating every payload string as a path caused ordinary prose such as
    "financial records belong in VAULT/Finance/" to become private source
    content. That false positive blocked the public Markets watchlist. The
    security boundary belongs on fields that actually identify files.
    """
    found = []

    def walk(v, *, path_context: bool = False):
        if isinstance(v, str):
            if path_context:
                found.append(v.strip().strip('"').replace("\\", "/"))
        elif isinstance(v, dict):
            for key, value in v.items():
                walk(value, path_context=path_context or _path_field(key))
        elif isinstance(v, (list, tuple)):
            for x in v:
                walk(x, path_context=path_context)

    walk(payload)
    return found


def derive_sensitivity(job: dict) -> str:
    """Path-derived sensitivity. Fails closed; never trusts the producer alone."""
    for p in _payload_paths(job.get("payload")):
        if any(p.startswith(f) or f in p for f in FORBIDDEN_PREFIXES):
            raise ForbiddenPath(f"payload references an off-limits path: {p}")
        if any(p.startswith(pre) or pre in p for pre in PRIVATE_PREFIXES):
            return "private"
        if any(s in p for s in PRIVATE_SUBSTRINGS):
            return "private"
    declared = job.get("sensitivity")
    return "internal" if declared == "internal" else "private"


def resolve_runtime(job: dict, mod) -> str:
    requested = job.get("runtime") or getattr(mod, "DEFAULT_RUNTIME", "ollama")
    # Producers may prefer a cloud reasoner for internal work, but the payload
    # is authoritative. Private paths are automatically downgraded to the local
    # runtime instead of being claimed and then failed. guard() still rejects a
    # cloud/private pairing if a caller bypasses this resolver.
    if derive_sensitivity(job) == "private" and not runtimes.is_local(requested):
        return "ollama"
    return requested


def guard(job: dict, runtime: str) -> str:
    """Raise if this job may not run on this runtime. Returns the sensitivity."""
    sensitivity = derive_sensitivity(job)
    if sensitivity == "private" and not runtimes.is_local(runtime):
        raise SensitivityViolation(
            f"job {job['job']} is sensitivity=private and may not run on "
            f"cloud runtime {runtime!r}; local runtimes are "
            f"{sorted(runtimes.LOCAL_RUNTIMES)}")
    return sensitivity


def record_usage(job: dict, res) -> None:
    """Append to the shared ledger, including $0 local rows.

    Recording zero-cost local rows is the point: it is how the local-vs-cloud
    routing ratio stays visible in the ledger (surfaced on /ops).
    """
    try:
        from usage_ledger import record_usage
        record_usage(
            model=res.model or "-",
            input_tokens=res.tokens_in,
            output_tokens=res.tokens_out,
            cost_usd=res.cost_usd,
            source=f"dispatch:{job.get('kind')}",
            # Pass provider explicitly: _provider_for() maps by model-name prefix
            # and would bucket "qwen3:8b" as "other". The runtime is the truth.
            provider=res.runtime,
            # Subscription CLI runs bill $0; the reported figure is notional.
            subscription=getattr(res, "subscription", False),
        )
    except Exception as e:            # accounting must never fail a job
        log_line("dispatch", f"usage accounting failed: {e!r}")


def next_runtime(mod, runtime: str, error: str, attempted: set) -> str | None:
    """The next runtime to try after a failure, or None to fail the job.

    Two sources, most specific first. A job kind's own `fallback_runtime()`
    knows things the dispatcher cannot - research.lit_review uses it for a
    provider-specific content refusal on a public abstract. Only if that hook
    declines does the generic rule apply: a spent or unreachable subscription
    earns the counterpart provider (runtimes/failover.py). Everything else
    fails, which is the behaviour every kind had before.
    """
    if hasattr(mod, "fallback_runtime"):
        try:
            candidate = mod.fallback_runtime(runtime, error)
        except Exception as e:
            log_line("dispatch", f"fallback_runtime() raised: {e!r}")
            candidate = None
        if candidate and candidate not in attempted:
            return candidate
    # A kind whose effect happens through the model's own tools cannot be moved
    # to a runtime with different tools - it would report success and write
    # nothing. Those kinds set ALLOW_RUNTIME_FAILOVER = False and say why.
    if not getattr(mod, "ALLOW_RUNTIME_FAILOVER", True):
        return None
    return failover.counterpart(runtime, error=error, exclude=attempted)


def run_one(job: dict, *, dry_run: bool = False) -> str:
    """Execute a claimed job. Returns the terminal status it moved to."""
    jid = job["job"]

    def cancelled() -> bool:
        current = ledger.get(jid)
        return bool(current and current.get("status") == "cancelled")

    def transition(fn, *args, **kwargs) -> str | None:
        """Let an atomic cancellation win cleanly over a terminal write."""
        try:
            fn(*args, **kwargs)
            return None
        except ledger.LedgerError:
            if cancelled():
                log_line("dispatch", f"CANCELLED {jid}")
                return "cancelled"
            raise

    mod = job_registry.get(job.get("kind"))
    if mod is None:
        status = transition(
            ledger.fail,
            jid,
            f"no job module registered for kind {job.get('kind')!r}",
            retryable=False,
        )
        return status or "failed"

    requested_runtime = (
        job.get("runtime") or getattr(mod, "DEFAULT_RUNTIME", "ollama")
    )
    runtime = resolve_runtime(job, mod)
    if runtime != requested_runtime:
        log_line(
            "dispatch",
            f"REROUTED {jid}: private payload {requested_runtime} -> {runtime}",
        )
    try:
        sensitivity = guard(job, runtime)
    except (SensitivityViolation, ForbiddenPath) as e:
        log_line("dispatch", f"BLOCKED {jid}: {e}")
        status = transition(ledger.fail, jid, str(e), retryable=False)
        return status or "failed"

    if dry_run:
        print(f"  would run {jid} kind={job.get('kind')} runtime={runtime} "
              f"sensitivity={sensitivity}")
        ledger.release(jid, why="dry run")
        return "dry-run"

    try:
        prompt = mod.build_prompt(job.get("payload"))
    except Exception as e:
        status = transition(
            ledger.fail, jid, f"build_prompt failed: {e!r}", retryable=False,
        )
        return status or "failed"

    if cancelled():
        return "cancelled"

    timeout = getattr(mod, "TIMEOUT", DEFAULT_TIMEOUT.get(runtime, 600))

    def defer_until(until, reason: str) -> str:
        """Park the job until a window resets, or fail it if it has circled enough."""
        deferrals = int(job.get("deferrals") or 0)
        if deferrals >= MAX_DEFERRALS:
            status = transition(
                ledger.fail, jid,
                f"{reason} [deferred {deferrals} times; giving up]")
            return status or "failed"
        log_line("dispatch", f"DEFERRED {jid} until {until.isoformat(timespec='minutes')}: "
                             f"{reason[:120]}")
        status = transition(ledger.defer, jid, until, reason)
        return status or "deferred"

    # Pre-flight (2026-09-16). If this runtime's breaker is tripped, or the
    # usage snapshot already shows its window spent, do not call it: route to
    # the counterpart now when the kind allows it and the guard agrees, else
    # wait for the reset. This is what stops one spent window from failing
    # the forty jobs behind it one at a time.
    attempted = set()
    # Cloud runtimes this job found spent, with when each comes back. Filled by
    # the pre-flight below and by rate-limit failures during the run; a
    # deferral waits for the soonest of them.
    spent: dict[str, object] = {}
    blocked_until, blocked_why = capacity.unavailable_until(runtime)
    if blocked_until:
        alternate = None
        if getattr(mod, "ALLOW_RUNTIME_FAILOVER", True):
            alternate = failover.counterpart(runtime, exclude={runtime})
            alternate_until = (capacity.unavailable_until(alternate)[0]
                               if alternate else None)
            if alternate_until:
                # Both out. Wait for whichever comes back first.
                blocked_until = min(blocked_until, alternate_until)
                alternate = None
            if alternate:
                try:
                    guard(job, alternate)
                except (SensitivityViolation, ForbiddenPath) as e:
                    log_line("dispatch", f"PREFLIGHT FAILOVER BLOCKED {jid}: {e}")
                    alternate = None
        if alternate:
            log_line("dispatch",
                     f"PREFLIGHT {jid}: {runtime} -> {alternate} ({blocked_why})")
            attempted.add(runtime)
            spent[runtime] = blocked_until
            runtime = alternate
        else:
            return defer_until(blocked_until, blocked_why or f"{runtime} is spent")

    def run_with(selected_runtime: str):
        adapter = runtimes.get(selected_runtime)
        kwargs = {}
        if selected_runtime == "claude":
            tools = (list(mod.ALLOWED_TOOLS) if hasattr(mod, "ALLOWED_TOOLS")
                     else None)
            # A web-search job that failed over from codex has to keep its
            # sources. The markets kinds declare ALLOWED_TOOLS = [] because
            # codex gets the web through --search; handed to Claude with no
            # tools at all, the same prompt still demands a source_url per
            # item and the only ways to satisfy it are to fabricate or to
            # fail. Read-only web tools, nothing else.
            if getattr(mod, "WEB_SEARCH", False):
                tools = (tools or []) + [
                    t for t in ("WebSearch", "WebFetch") if t not in (tools or [])
                ]
            if tools is not None:
                kwargs["allowed_tools"] = tools
        if selected_runtime == "codex" and getattr(mod, "WEB_SEARCH", False):
            kwargs["web_search"] = True

        module_default_runtime = getattr(mod, "DEFAULT_RUNTIME", "ollama")
        model = (
            getattr(mod, "MODEL", None)
            if selected_runtime == module_default_runtime
            else getattr(mod, f"{selected_runtime.upper()}_MODEL", None)
        )
        # The /teams model picker (2026-09-18) overrides the module's own
        # MODEL per kind and runtime. Asked per runtime so a failover hop to
        # codex does not carry a claude model name across. The stepdown
        # inside claude_rt still applies to whatever is picked.
        picked = model_policy.model_for(job.get("kind"), selected_runtime)
        if picked and picked != model:
            log_line("dispatch", f"MODEL POLICY {jid}: {selected_runtime} {model or 'default'} -> {picked}")
            model = picked
        return adapter.run(
            prompt,
            schema=getattr(mod, "SCHEMA", None),
            cwd=REPO_ROOT,
            timeout=timeout,
            model=model,
            cancel_check=cancelled,
            **kwargs,
        )

    res = run_with(runtime)
    if cancelled():
        log_line("dispatch", f"CANCELLED {jid} while {runtime} was running")
        return "cancelled"
    record_usage(job, res)

    # Two reasons to try a second provider: a job kind's own narrow hook (a
    # public abstract that tripped a provider-specific content refusal), and a
    # spent subscription - when the owner's Claude or ChatGPT capacity runs out,
    # every job routed to that runtime fails, and the other provider's window
    # is independent. The same sensitivity guard runs before each hop, so
    # private material can never escape to a second cloud provider; ollama has
    # no counterpart at all, so a local job stays local.
    attempted.add(runtime)

    # Tripping the breaker here is what the pre-flight above reads.
    def note_rate_limit(selected_runtime: str, error: str) -> None:
        if selected_runtime not in capacity.CLOUD_RUNTIMES:
            return
        if not failover.is_rate_limited(error):
            return
        until = capacity.reset_time_for(selected_runtime, error)
        capacity.trip(selected_runtime, until, error)
        spent[selected_runtime] = until

    note_rate_limit(runtime, res.error or "")
    while not res.ok:
        fallback = next_runtime(mod, runtime, res.error or "", attempted)
        if not fallback:
            break
        if capacity.unavailable_until(fallback)[0]:
            # The other provider is known to be out too. Do not spend a call
            # confirming it; the deferral below waits for whichever resets first.
            log_line("dispatch", f"FAILOVER SKIPPED {jid}: {fallback} is cooling down")
            spent.setdefault(fallback, capacity.unavailable_until(fallback)[0])
            break
        try:
            guard(job, fallback)
        except (SensitivityViolation, ForbiddenPath) as e:
            log_line("dispatch", f"FAILOVER BLOCKED {jid}: {e}")
            break
        log_line(
            "dispatch",
            f"FAILOVER {jid}: {runtime} -> {fallback} after "
            f"{(res.error or 'runtime failure')[:120]}",
        )
        runtime = fallback
        attempted.add(fallback)
        res = run_with(runtime)
        if cancelled():
            log_line(
                "dispatch",
                f"CANCELLED {jid} while {runtime} fallback was running",
            )
            return "cancelled"
        record_usage(job, res)
        note_rate_limit(runtime, res.error or "")

    if not res.ok:
        error = res.error or "runtime returned not-ok"
        if error.startswith("structured output did not parse") and res.text:
            # The ledger keeps one line; the message that failed to parse is
            # the only evidence, so it goes to a file the error names.
            error = structured.keep_raw(runtime, res.text, error, job_id=jid)
        if len(attempted) > 1:
            # /ops shows this string. "sonnet said X" with no mention of the
            # two subscriptions that were already spent sends their debugging
            # the wrong provider.
            error = f"{error} [tried {', '.join(sorted(attempted))}]"
        # A spent window is not a defect in the job. When the last word was a
        # rate limit and backup routing is on, wait for the soonest reset
        # instead of failing: the next scheduled drain after that time picks
        # the job up. An unavailable provider (missing CLI, expired login), a
        # refusal, a parse failure, or a timeout still fail loudly - time
        # fixes none of those.
        if (failover.enabled() and spent
                and runtime in capacity.CLOUD_RUNTIMES
                and failover.is_rate_limited(res.error or "")):
            return defer_until(min(spent.values()), error)
        status = transition(ledger.fail, jid, error)
        if status:
            return status
        if hasattr(mod, "on_failure"):
            try:
                mod.on_failure(job, error)
            except Exception as hook_error:
                log_line("dispatch", f"on_failure() raised for {jid}: {hook_error!r}")
        return "failed"

    result = res.data if res.data is not None else {"text": res.text}

    # Optional lifecycle hook for cross-store provenance. It runs after a valid
    # model result but before the ledger transition, and cannot change the
    # review policy. Hook failures are logged while the ledger remains the
    # authoritative job state.
    if hasattr(mod, "on_result"):
        try:
            mod.on_result(job, result)
        except Exception as e:
            log_line("dispatch", f"on_result() raised for {jid}: {e!r}")

    # A job kind may refine REVIEW_REQUIRED per result (e.g. auto-approve only
    # above a confidence threshold). Absent needs_human(), REVIEW_REQUIRED alone
    # decides. Errors here fail safe - toward review, never past it.
    review = getattr(mod, "REVIEW_REQUIRED", True)
    if review and hasattr(mod, "needs_human"):
        try:
            review = bool(mod.needs_human(result))
        except Exception as e:
            log_line("dispatch", f"needs_human() raised for {jid}: {e!r}; forcing review")
            review = True

    if review:
        status = transition(ledger.needs_review, jid, result)
        return status or "needs_review"
    status = transition(ledger.complete, jid, result)
    return status or "completed"


def drain(*, worker: str, kinds=None, runtimes_filter=None, max_jobs=None,
          dry_run: bool = False) -> dict:
    counts = {}
    done = 0
    while max_jobs is None or done < max_jobs:
        job = ledger.claim(worker, kinds=kinds, runtimes=runtimes_filter)
        if job is None:
            break
        status = run_one(job, dry_run=dry_run)
        counts[status] = counts.get(status, 0) + 1
        done += 1
        if dry_run:      # released back to the queue; stop or we spin forever
            break
    return counts


def _arg(name, default=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def _csv(name):
    v = _arg(name)
    return [s.strip() for s in v.split(",") if s.strip()] if v else None


def main() -> int:
    import os
    worker = _arg("--worker-id", f"dispatch-{os.getpid()}")
    kinds = _csv("--kinds")
    rts = _csv("--runtimes")
    max_jobs = int(_arg("--max")) if _arg("--max") else None
    dry_run = "--dry-run" in sys.argv

    if "--reap" in sys.argv:
        got = ledger.reap()
        print(f"reaped {len(got)} stale claims")
        return 0

    if "--capacity" in sys.argv:
        # What the dispatcher believes about each subscription right now:
        # tripped breakers, then the trusted usage windows. Percentages only.
        tripped = capacity.breaker_status()
        for rt in capacity.CLOUD_RUNTIMES:
            entry = tripped.get(rt)
            line = (f"  {rt:<7} cooling down until {entry['until']} "
                    f"({(entry.get('reason') or '')[:80]})" if entry
                    else f"  {rt:<7} open")
            print(line)
            for w in capacity.windows(rt):
                resets = (w["resets_at"].isoformat(timespec="minutes")
                          if w["resets_at"] else "unknown")
                print(f"          {w['label']:<16} {w['remaining_percent']:>5g}% left"
                      f"  resets {resets}")
        waiting = [j for j in ledger.query(status="created") if ledger.is_waiting(j)]
        print(f"  {len(waiting)} job(s) waiting for a reset")
        return 0

    if "--clear-breaker" in sys.argv:
        # For when they know the window is back before the breaker's `until`
        # (a plan upgrade, a reset the message named wrongly). Deferred jobs
        # keep their own not_before; this only lets new claims call again.
        target = _arg("--clear-breaker")
        target = target if target in capacity.CLOUD_RUNTIMES else None
        capacity.clear(target)
        print(f"cleared breaker for {target or 'every runtime'}")
        return 0

    if "--watch" in sys.argv:
        interval = int(_arg("--interval", "30"))
        print(f"watching (interval {interval}s, worker {worker}) - Ctrl-C to stop")
        try:
            while True:
                ledger.reap()          # recover anything a dead worker left claimed
                counts = drain(worker=worker, kinds=kinds, runtimes_filter=rts,
                               max_jobs=max_jobs, dry_run=dry_run)
                if counts:
                    print(f"{now():%H:%M:%S} {json.dumps(counts)}")
                time.sleep(interval)
        except KeyboardInterrupt:
            print("\nstopped")
        return 0

    counts = drain(worker=worker, kinds=kinds, runtimes_filter=rts,
                   max_jobs=max_jobs, dry_run=dry_run)
    print(json.dumps(counts) if counts else "nothing ready")
    return 0


if __name__ == "__main__":
    sys.exit(main())
