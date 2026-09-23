"""What each subscription has left, and when a spent one comes back.

runtimes/failover.py answers "where else can this job run right now?". This
module answers the two questions around it:

  1. BEFORE a run - is it worth asking this provider at all, and with which
     model? Both cloud CLIs authenticate with a subscription whose windows
     `usage_limits.py` already reads for the header usage board. Reading that
     same snapshot here lets the dispatcher route around a spent window, and
     lets `claude_rt` start on sonnet when the Opus allowance is nearly gone,
     instead of discovering both by failing.
  2. AFTER a rate-limit failure - when will this provider answer again? The
     CLI says so in its own error ("resets 10pm (America/Los_Angeles)"), the
     snapshot says so in `resets_at`, and failing that a short default
     cooldown is better than 40 jobs each rediscovering the same fact.

Two pieces of state, both under .claude/data/state/ and both advisory:

  runtime-capacity.json  the circuit breaker: {runtime: {until, reason}}. Set
                         by the dispatcher on the first rate-limit failure so
                         the rest of the drain stops calling that provider.
  usage-limits.json      the usage board's cache, written by usage_limits.py
                         and refreshed here when older than SNAPSHOT_MAX_AGE.
                         `usage_limits.py` stays the only file that touches the
                         OAuth token - this module only reads percentages.

Everything here degrades to "no opinion". A missing or stale snapshot, an
unreadable state file, or a network failure never fails a job; the reactive
failover path in dispatch.py still runs behind every decision made here.

Boundaries that hold: only cloud runtimes are ever tripped or pre-empted -
ollama has no window and never appears here; a deferred job is still gated by
the same `guard()` when it is claimed again; and the Max planner passes
`model_fallback=False`, so `preferred_model()` never touches a pinned model.

Kill switches: SECONDBRAIN_DISABLE_FAILOVER=1 turns this off together with
backup routing; SECONDBRAIN_DISABLE_PREFLIGHT=1 turns off only the snapshot
pre-flight (the breaker and deferral still work off real errors).
"""

from __future__ import annotations

import os
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared import (  # noqa: E402
    STATE_DIR, TIMEZONE, atomic_write_json, log_line, now, read_json,
)

from . import failover  # noqa: E402

STATE_FILE = STATE_DIR / "runtime-capacity.json"
# The same file usage_limits.py writes. Imported lazily in _snapshot_file() so
# a test can point this module at a temp copy without importing the reader.
SNAPSHOT_FILE: Path | None = None

CLOUD_RUNTIMES = ("claude", "codex")

# Refresh the usage snapshot when older than this (matches limits.ts).
SNAPSHOT_MAX_AGE = timedelta(seconds=120)
# Never make a routing decision on numbers older than this. Codex's figures
# are only as fresh as their last Codex turn, and a day-old "5% left" is noise.
TRUST_MAX_AGE = timedelta(minutes=30)
# One refresh attempt per process per SNAPSHOT_MAX_AGE, whatever the outcome.
_last_refresh = 0.0
# Tests set this False so a dispatch never reaches the network.
REFRESH_ENABLED = True

# When a rate-limit error names no reset time and the snapshot has none, wait
# this long. The heartbeat cadence is 30 minutes, so the next scheduled drain
# picks the job up on its first pass after this.
DEFAULT_COOLDOWN = timedelta(minutes=30)
# A parsed reset further out than this is a parse error, not a plan.
MAX_COOLDOWN = timedelta(days=8)

# Below this much remaining in an overall window, the provider counts as spent
# and the dispatcher routes around it before calling it.
RUNTIME_FLOOR_PERCENT = float(os.environ.get("SECONDBRAIN_RUNTIME_FLOOR_PERCENT", "5"))
# Below this much remaining in the Opus window, claude runs start on sonnet.
OPUS_FLOOR_PERCENT = float(os.environ.get("SECONDBRAIN_OPUS_FLOOR_PERCENT", "10"))

# Which snapshot windows mean "this runtime is spent" (None = every window).
# Claude's seven_day_opus is a *model* window, handled by preferred_model().
OVERALL_WINDOWS = {
    "claude": {"five_hour", "seven_day", "monthly"},
    "codex": None,
}
OPUS_WINDOW = "seven_day_opus"
# Every model with a rung below it in MODEL_BACKUP is an Opus-tier model.
OPUS_TIER = frozenset(failover.MODEL_BACKUP.get("claude", {}))


def enabled() -> bool:
    return failover.enabled()


def preflight_enabled() -> bool:
    return enabled() and os.environ.get("SECONDBRAIN_DISABLE_PREFLIGHT") != "1"


def _iso(dt: datetime) -> str:
    return dt.astimezone(TIMEZONE).isoformat(timespec="seconds")


def _parse_dt(value) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TIMEZONE)
    return dt


# --------------------------------------------------------------------------
# Reset-time parsing
# --------------------------------------------------------------------------

_EPOCH_RE = re.compile(r"\|(\d{10})\b")
_ISO_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?")
_CLOCK_RE = re.compile(
    r"reset\w*\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?"
    r"(?:\s*\(([A-Za-z_]+/[A-Za-z_]+)\))?",
    re.IGNORECASE)
# A weekly window names a date: "resets Sep 20, 3pm" / "resets Sep 20 at 3:30pm".
_DATED_RE = re.compile(
    r"reset\w*\s+(?:on\s+)?(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
    r"\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?"
    r"(?:\s*\(([A-Za-z_]+/[A-Za-z_]+)\))?",
    re.IGNORECASE)
_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
_RELATIVE_RE = re.compile(
    r"(?:in|after)\s+(\d+)\s*(minutes?|mins?|m|hours?|hrs?|h|seconds?|secs?|s)\b",
    re.IGNORECASE)


def parse_reset(error: str, *, reference: datetime | None = None) -> datetime | None:
    """The reset time an error message names, or None.

    Handles the shapes the two CLIs have actually produced: an epoch after a
    pipe (`usage limit reached|1755500000`), an ISO timestamp, a clock time
    with an optional zone (`resets 10pm (America/Los_Angeles)`, `reset at
    3pm`), and a relative delay (`try again in 45 minutes`). A clock time that
    has already passed today means tomorrow.
    """
    text = error or ""
    if not text:
        return None
    ref = reference or now()

    m = _EPOCH_RE.search(text)
    if m:
        return datetime.fromtimestamp(int(m.group(1)), tz=TIMEZONE)

    m = _ISO_RE.search(text)
    if m:
        parsed = _parse_dt(m.group(0))
        if parsed:
            return parsed

    def _zone(name):
        if not name:
            return TIMEZONE
        try:
            return ZoneInfo(name)
        except Exception:  # noqa: BLE001 - unknown zone: keep Pacific
            return TIMEZONE

    def _clock(hour, minute, meridiem):
        if meridiem == "pm" and hour < 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0
        return (hour, minute) if 0 <= hour <= 23 and 0 <= minute <= 59 else None

    m = _DATED_RE.search(text)
    if m:
        clock = _clock(int(m.group(3)), int(m.group(4) or 0), (m.group(5) or "").lower())
        if clock:
            local_ref = ref.astimezone(_zone(m.group(6)))
            try:
                candidate = local_ref.replace(
                    month=_MONTHS[m.group(1).lower()], day=int(m.group(2)),
                    hour=clock[0], minute=clock[1], second=0, microsecond=0)
            except ValueError:
                candidate = None
            if candidate is not None:
                if candidate <= local_ref:
                    candidate = candidate.replace(year=candidate.year + 1)
                return candidate

    m = _CLOCK_RE.search(text)
    if m:
        clock = _clock(int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower())
        if clock:
            local_ref = ref.astimezone(_zone(m.group(4)))
            candidate = local_ref.replace(hour=clock[0], minute=clock[1], second=0,
                                          microsecond=0)
            if candidate <= local_ref:
                candidate += timedelta(days=1)
            return candidate

    m = _RELATIVE_RE.search(text)
    if m:
        amount = int(m.group(1))
        unit = m.group(2).lower()
        if unit.startswith("h"):
            delta = timedelta(hours=amount)
        elif unit.startswith("s"):
            delta = timedelta(seconds=amount)
        else:
            delta = timedelta(minutes=amount)
        return ref + delta
    return None


# --------------------------------------------------------------------------
# Circuit breaker
# --------------------------------------------------------------------------

def _load_state() -> dict:
    data = read_json(STATE_FILE, {})
    return data if isinstance(data, dict) else {}


def trip(runtime: str, until: datetime, reason: str = "") -> datetime | None:
    """Record that `runtime` is spent until `until`. Cloud runtimes only.

    Returns the recorded time, or None when nothing was recorded (a local
    runtime, failover disabled, or a time already in the past).
    """
    if runtime not in CLOUD_RUNTIMES or not enabled():
        return None
    current = now()
    if until <= current:
        return None
    until = min(until, current + MAX_COOLDOWN)
    state = _load_state()
    existing = _parse_dt((state.get(runtime) or {}).get("until"))
    # A later reset already on record wins: two windows can be spent at once
    # and the further one is the binding constraint.
    if existing and existing > until:
        return existing
    state[runtime] = {
        "until": _iso(until),
        "tripped_at": _iso(current),
        "reason": (reason or "")[:300],
    }
    try:
        atomic_write_json(STATE_FILE, state)
    except OSError as e:
        log_line("capacity", f"could not record breaker for {runtime}: {e!r}")
        return until
    log_line("capacity", f"TRIPPED {runtime} until {_iso(until)}: {reason[:120]}")
    return until


def cooling_until(runtime: str) -> datetime | None:
    """The breaker's reset time for `runtime`, or None when it may be called."""
    if runtime not in CLOUD_RUNTIMES or not enabled():
        return None
    entry = _load_state().get(runtime) or {}
    until = _parse_dt(entry.get("until"))
    if until and until > now():
        return until
    return None


def clear(runtime: str | None = None) -> None:
    """Reset the breaker for one runtime, or for all of them."""
    state = _load_state()
    if runtime is None:
        state = {}
    else:
        state.pop(runtime, None)
    try:
        atomic_write_json(STATE_FILE, state)
    except OSError:
        pass


def breaker_status() -> dict:
    """Diagnostic view: {runtime: {until, reason, tripped_at}} for live trips."""
    out = {}
    current = now()
    for runtime, entry in _load_state().items():
        until = _parse_dt((entry or {}).get("until"))
        if until and until > current:
            out[runtime] = dict(entry)
    return out


# --------------------------------------------------------------------------
# Usage snapshot
# --------------------------------------------------------------------------

def _snapshot_file() -> Path:
    if SNAPSHOT_FILE is not None:
        return SNAPSHOT_FILE
    import usage_limits
    return usage_limits.STATE_FILE


def _refresh() -> dict | None:
    """Re-run the usage reader when the cache is stale. Never raises."""
    global _last_refresh
    if not REFRESH_ENABLED:
        return None
    if time.monotonic() - _last_refresh < SNAPSHOT_MAX_AGE.total_seconds():
        return None
    _last_refresh = time.monotonic()
    try:
        import usage_limits
        snap = usage_limits.collect()
        atomic_write_json(_snapshot_file(), snap)
        return snap
    except Exception as e:  # noqa: BLE001 - the snapshot is advisory
        log_line("capacity", f"usage snapshot refresh failed: {e!r}")
        return None


def snapshot(*, refresh: bool = True) -> dict | None:
    """The usage-limits snapshot, refreshed when older than SNAPSHOT_MAX_AGE."""
    data = read_json(_snapshot_file(), None)
    if not isinstance(data, dict):
        data = None
    generated = _parse_dt((data or {}).get("generated_at"))
    stale = generated is None or now() - generated > SNAPSHOT_MAX_AGE
    if stale and refresh:
        fresh = _refresh()
        if fresh:
            return fresh
    return data


def _provider(snap: dict | None, runtime: str) -> dict | None:
    for provider in (snap or {}).get("providers") or []:
        if isinstance(provider, dict) and provider.get("key") == runtime:
            return provider if provider.get("ok") else None
    return None


def windows(runtime: str, *, refresh: bool = True) -> list[dict]:
    """Trusted limit windows for `runtime`: [] when unknown or too old."""
    snap = snapshot(refresh=refresh)
    provider = _provider(snap, runtime)
    if not provider:
        return []
    observed = _parse_dt(provider.get("observed_at")) or _parse_dt(
        (snap or {}).get("generated_at"))
    if observed is None or now() - observed > TRUST_MAX_AGE:
        return []
    out = []
    for w in provider.get("windows") or []:
        if not isinstance(w, dict):
            continue
        remaining = w.get("remaining_percent")
        if not isinstance(remaining, (int, float)):
            continue
        out.append({
            "id": str(w.get("id") or ""),
            "label": str(w.get("label") or w.get("id") or ""),
            "remaining_percent": float(remaining),
            "resets_at": _parse_dt(w.get("resets_at")),
        })
    return out


def _overall(runtime: str, ws: list[dict]) -> list[dict]:
    allowed = OVERALL_WINDOWS.get(runtime)
    if allowed is None:
        return ws
    return [w for w in ws if w["id"] in allowed]


def spent_until(runtime: str, *, refresh: bool = True) -> tuple[datetime | None, str | None]:
    """From the snapshot alone: (reset time, why) if `runtime` reads as spent.

    A window at or under RUNTIME_FLOOR_PERCENT remaining with a reset time in
    the future makes the runtime spent until that time. With several such
    windows the furthest reset binds.
    """
    if runtime not in CLOUD_RUNTIMES or not preflight_enabled():
        return None, None
    binding, why = None, None
    for w in _overall(runtime, windows(runtime, refresh=refresh)):
        if w["remaining_percent"] > RUNTIME_FLOOR_PERCENT:
            continue
        resets = w["resets_at"]
        if not resets or resets <= now():
            continue
        if binding is None or resets > binding:
            binding = resets
            why = (f"{runtime} {w['label']} window at "
                   f"{w['remaining_percent']:g}% remaining, resets {_iso(resets)}")
    return binding, why


def unavailable_until(runtime: str) -> tuple[datetime | None, str | None]:
    """Should the dispatcher skip `runtime` right now? Breaker first, then snapshot."""
    until = cooling_until(runtime)
    if until:
        reason = (_load_state().get(runtime) or {}).get("reason") or "rate limited"
        return until, f"{runtime} is cooling down until {_iso(until)} ({reason[:80]})"
    return spent_until(runtime)


def reset_time_for(runtime: str, error: str) -> datetime:
    """When to try `runtime` again after a rate-limit `error`.

    The error's own reset time wins; then the snapshot's reset for its most
    depleted overall window; then DEFAULT_COOLDOWN. Always in the future and
    never more than MAX_COOLDOWN out.
    """
    current = now()
    parsed = parse_reset(error, reference=current)
    if parsed and current < parsed <= current + MAX_COOLDOWN:
        return parsed
    lowest = None
    for w in _overall(runtime, windows(runtime, refresh=False)):
        if not w["resets_at"] or w["resets_at"] <= current:
            continue
        if lowest is None or w["remaining_percent"] < lowest["remaining_percent"]:
            lowest = w
    # Only trust a snapshot reset when the window really does read as spent;
    # a 60%-remaining window resetting in six days is not the reason we failed.
    if lowest and lowest["remaining_percent"] <= RUNTIME_FLOOR_PERCENT * 4:
        return min(lowest["resets_at"], current + MAX_COOLDOWN)
    return current + DEFAULT_COOLDOWN


# --------------------------------------------------------------------------
# Model pre-flight
# --------------------------------------------------------------------------

def preferred_model(runtime: str, model: str | None) -> tuple[str | None, str | None]:
    """The model to start on, given what the Opus window has left.

    Returns (model, reason). The reason is None when nothing changed. Only
    Claude has a per-model window, and only Opus-tier models step down; the
    step follows failover.MODEL_BACKUP so the two never disagree about what
    "one rung down" means.
    """
    if not model or runtime != "claude" or not preflight_enabled():
        return model, None
    key = str(model).strip().lower()
    if key not in OPUS_TIER:
        return model, None
    opus = next((w for w in windows(runtime) if w["id"] == OPUS_WINDOW), None)
    if opus is None or opus["remaining_percent"] > OPUS_FLOOR_PERCENT:
        return model, None
    picked = key
    seen = set()
    while picked in OPUS_TIER and picked not in seen:
        seen.add(picked)
        picked = failover.MODEL_BACKUP["claude"].get(picked, picked)
    if picked == key:
        return model, None
    resets = f", resets {_iso(opus['resets_at'])}" if opus["resets_at"] else ""
    return picked, (f"Opus window at {opus['remaining_percent']:g}% remaining"
                    f"{resets}; starting on {picked}")
