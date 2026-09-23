"""Subscription rate-limit reader for Claude Code and Codex.

This is the deliberate "wrapper handles auth, the LLM never sees the token"
pattern the integrations already use (see integrations/google_auth.py): the
OAuth access token is read here, used for exactly one GET, and never printed,
logged, or returned. Everything this module emits is percentages, window
labels, and reset timestamps.

Two very different sources, because the two CLIs expose different things:

- **Claude** has no usage data on disk at all. `/usage` fetches it live, so we
  do the same call with the local OAuth token from ~/.claude/.credentials.json.
  This endpoint is not part of the public API and can change without notice -
  every failure is reported as an error string rather than raised, so the
  dropdown degrades to "unavailable" instead of breaking the header.
- **Codex** writes an authoritative `rate_limits` snapshot into every session
  rollout log, so no credential and no network call is needed. The trade-off is
  freshness: the numbers are as of the last Codex turn, which is why every
  provider carries an `observed_at` and a `freshness` flag for the UI to show.

Usage:
    python .claude/scripts/usage_limits.py            # refresh + print summary
    python .claude/scripts/usage_limits.py --json     # refresh + emit JSON
    python .claude/scripts/usage_limits.py --no-write # don't touch the cache
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

sys.path.insert(0, str(Path(__file__).resolve().parent))

from shared import STATE_DIR, atomic_write_json, ensure_dirs, log_line  # noqa: E402

STATE_FILE = STATE_DIR / "usage-limits.json"

CLAUDE_CREDENTIALS = Path.home() / ".claude" / ".credentials.json"
CLAUDE_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
CLAUDE_OAUTH_BETA = "oauth-2025-04-20"
HTTP_TIMEOUT = 12

CODEX_SESSIONS = Path.home() / ".codex" / "sessions"
# Only the tail of a rollout log can hold the newest snapshot, and these files
# reach tens of MB in long sessions.
CODEX_TAIL_BYTES = 512 * 1024
CODEX_SCAN_FILES = 6

# Friendly names for the windows each provider reports. Anything unrecognized
# falls back to a generated label, so a new window type still shows up.
CLAUDE_WINDOW_LABELS = {
    "five_hour": "Session (5h)",
    "seven_day": "Weekly",
    "seven_day_opus": "Weekly (Opus)",
    "seven_day_oauth_apps": "Weekly (apps)",
    "monthly": "Monthly",
}
CODEX_WINDOW_LABELS = {60: "Hourly", 300: "Session (5h)", 10080: "Weekly"}


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _window(win_id: str, label: str, used: float, resets_at: str | None) -> dict[str, Any]:
    used = max(0.0, min(100.0, round(float(used), 1)))
    return {
        "id": win_id,
        "label": label,
        "used_percent": used,
        "remaining_percent": round(100.0 - used, 1),
        "resets_at": resets_at,
    }


# --------------------------------------------------------------------------
# Claude
# --------------------------------------------------------------------------

def _claude_token() -> tuple[str | None, str | None]:
    """Return (token, error). The token is never logged or emitted."""
    if not CLAUDE_CREDENTIALS.exists():
        return None, "no local Claude credentials - sign in with `claude` first"
    try:
        blob = json.loads(CLAUDE_CREDENTIALS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"could not read Claude credentials ({type(exc).__name__})"

    oauth = blob.get("claudeAiOauth") or blob.get("claude_ai_oauth") or {}
    if not isinstance(oauth, dict):
        return None, "unexpected credential format"
    token = oauth.get("accessToken") or oauth.get("access_token")
    if not token:
        return None, "no OAuth session found (API-key auth has no usage bars)"

    expires = oauth.get("expiresAt") or oauth.get("expires_at")
    if isinstance(expires, (int, float)) and expires / 1000 < _now().timestamp():
        # Refreshing would mean writing back to the credential file; leave that
        # to Claude Code itself rather than having two writers.
        return None, "session expired - open `claude` once to refresh it"
    return str(token), None


def _harvest_windows(payload: Any, labels: dict[str, str]) -> list[dict[str, Any]]:
    """Pull every {utilization, resets_at} object out of a usage response.

    Written structurally rather than against fixed key names so that a new
    limit window (Anthropic has added them before) appears automatically.
    """
    found: list[dict[str, Any]] = []

    def walk(node: Any, key: str) -> None:
        if not isinstance(node, dict):
            return
        used = node.get("utilization", node.get("used_percent", node.get("percent_used")))
        resets = node.get("resets_at", node.get("reset_at", node.get("resets")))
        if isinstance(used, (int, float)):
            label = labels.get(key) or key.replace("_", " ").capitalize()
            found.append(_window(key, label, used, _normalize_reset(resets)))
            return
        for child_key, child in node.items():
            walk(child, child_key)

    walk(payload, "")
    return found


def _normalize_reset(value: Any) -> str | None:
    if isinstance(value, (int, float)):
        return _iso(datetime.fromtimestamp(float(value), tz=timezone.utc))
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def read_claude() -> dict[str, Any]:
    provider: dict[str, Any] = {
        "key": "claude",
        "label": "Claude",
        "ok": False,
        "error": None,
        "freshness": "live",
        "observed_at": _iso(_now()),
        "windows": [],
    }

    token, error = _claude_token()
    if error or not token:
        provider["error"] = error
        return provider

    request = urllib.request.Request(
        CLAUDE_USAGE_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "anthropic-beta": CLAUDE_OAUTH_BETA,
            "Accept": "application/json",
            "User-Agent": "second-brain-usage-board/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        code = exc.code
        if code in (401, 403):
            provider["error"] = "not authorized - open `claude` once to refresh the session"
        elif code == 429:
            provider["error"] = "usage endpoint rate-limited, try again shortly"
        else:
            provider["error"] = f"usage endpoint returned HTTP {code}"
        return provider
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        provider["error"] = f"usage endpoint unreachable ({type(exc).__name__})"
        return provider

    windows = _harvest_windows(payload, CLAUDE_WINDOW_LABELS)
    if not windows:
        provider["error"] = "usage endpoint returned no recognizable limit windows"
        return provider

    provider["ok"] = True
    provider["windows"] = windows
    return provider


# --------------------------------------------------------------------------
# Codex
# --------------------------------------------------------------------------

def _recent_rollouts(limit: int = CODEX_SCAN_FILES) -> list[Path]:
    if not CODEX_SESSIONS.exists():
        return []
    files = [p for p in CODEX_SESSIONS.rglob("rollout-*.jsonl") if p.is_file()]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:limit]


def _tail_lines(path: Path, size: int = CODEX_TAIL_BYTES) -> Iterator[str]:
    with path.open("rb") as fh:
        fh.seek(0, os.SEEK_END)
        start = max(0, fh.tell() - size)
        fh.seek(start)
        chunk = fh.read()
    text = chunk.decode("utf-8", errors="ignore")
    lines = text.splitlines()
    if start > 0 and lines:
        lines = lines[1:]  # first line is probably truncated mid-record
    return reversed(lines)


def _find_rate_limits(path: Path) -> tuple[dict[str, Any] | None, float | None]:
    """Newest rate_limits object in one rollout log, with its timestamp."""
    for line in _tail_lines(path):
        if '"rate_limits"' not in line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        stack: list[Any] = [record]
        while stack:
            node = stack.pop()
            if not isinstance(node, dict):
                continue
            limits = node.get("rate_limits")
            if isinstance(limits, dict):
                return limits, _record_time(record, path)
            stack.extend(v for v in node.values() if isinstance(v, dict))
    return None, None


def _record_time(record: dict[str, Any], path: Path) -> float:
    stamp = record.get("timestamp") or record.get("ts")
    if isinstance(stamp, str):
        try:
            return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    if isinstance(stamp, (int, float)):
        return float(stamp)
    return path.stat().st_mtime


def read_codex() -> dict[str, Any]:
    provider: dict[str, Any] = {
        "key": "codex",
        "label": "Codex",
        "ok": False,
        "error": None,
        "freshness": "snapshot",
        "observed_at": None,
        "windows": [],
    }

    rollouts = _recent_rollouts()
    if not rollouts:
        provider["error"] = "no Codex session logs found"
        return provider

    limits: dict[str, Any] | None = None
    observed: float | None = None
    for path in rollouts:
        limits, observed = _find_rate_limits(path)
        if limits:
            break
    if not limits:
        provider["error"] = "recent Codex sessions carry no rate-limit snapshot"
        return provider

    windows: list[dict[str, Any]] = []
    for slot in ("primary", "secondary", "tertiary"):
        entry = limits.get(slot)
        if not isinstance(entry, dict):
            continue
        used = entry.get("used_percent", entry.get("utilization"))
        if not isinstance(used, (int, float)):
            continue
        minutes = entry.get("window_minutes")
        label = CODEX_WINDOW_LABELS.get(minutes) or _minutes_label(minutes) or slot.capitalize()
        windows.append(_window(slot, label, used, _normalize_reset(entry.get("resets_at"))))

    if not windows:
        provider["error"] = "Codex snapshot had no usable limit windows"
        return provider

    plan = limits.get("plan_type")
    provider["ok"] = True
    provider["windows"] = windows
    provider["plan"] = plan if isinstance(plan, str) else None
    provider["observed_at"] = _iso(datetime.fromtimestamp(observed or 0, tz=timezone.utc))
    return provider


def _minutes_label(minutes: Any) -> str | None:
    if not isinstance(minutes, (int, float)) or minutes <= 0:
        return None
    if minutes % 10080 == 0:
        weeks = int(minutes // 10080)
        return "Weekly" if weeks == 1 else f"Every {weeks} weeks"
    if minutes % 1440 == 0:
        days = int(minutes // 1440)
        return "Daily" if days == 1 else f"Every {days} days"
    if minutes % 60 == 0:
        return f"Session ({int(minutes // 60)}h)"
    return f"Every {int(minutes)}m"


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def collect() -> dict[str, Any]:
    return {
        "generated_at": _iso(_now()),
        "providers": [read_claude(), read_codex()],
    }


def _summarize(snapshot: dict[str, Any]) -> str:
    lines = [f"usage limits as of {snapshot['generated_at']}"]
    for provider in snapshot["providers"]:
        if not provider["ok"]:
            lines.append(f"  {provider['label']}: unavailable - {provider['error']}")
            continue
        for window in provider["windows"]:
            resets = window["resets_at"] or "unknown"
            lines.append(
                f"  {provider['label']} {window['label']}: "
                f"{window['remaining_percent']}% left (resets {resets})"
            )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Read Claude and Codex subscription limits.")
    parser.add_argument("--json", action="store_true", help="emit the snapshot as JSON")
    parser.add_argument("--no-write", action="store_true", help="skip the state-file cache")
    args = parser.parse_args()

    snapshot = collect()

    if not args.no_write:
        ensure_dirs()
        atomic_write_json(STATE_FILE, snapshot)

    failures = [p["error"] for p in snapshot["providers"] if not p["ok"]]
    if failures:
        log_line("usage_limits", "; ".join(str(f) for f in failures))

    if args.json:
        json.dump(snapshot, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(_summarize(snapshot) + "\n")

    # Non-zero only when nothing at all could be read - a single provider being
    # down should not fail the caller.
    return 0 if any(p["ok"] for p in snapshot["providers"]) else 1


if __name__ == "__main__":
    sys.exit(main())
