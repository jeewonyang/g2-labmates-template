"""Append-only usage ledger for API/token spend across providers and models.

One JSON object per line at .claude/data/usage.jsonl:

    {"ts":"2026-07-15T09:12:03-07:00","provider":"claude",
     "model":"claude-sonnet-5","input_tokens":1234,"output_tokens":567,
     "cache_read_tokens":0,"cost_usd":0.0123,"source":"heartbeat"}

This is the shared contract: the Second Brain's own SDK calls append via
`record_from_sdk_result()`, and ANY other tool of the owner's
(a companion app, etc.) can append cross-provider usage by writing one line in this shape - provider
"claude" | "openai" | ..., cost_usd already computed by the caller. The dashboard's
usage panel (src/lib/services/usage.ts) reads and aggregates this file. No secrets
live here - only counts and dollars.

CLI:
    python .claude/scripts/usage_ledger.py summary   # month-to-date totals
    python .claude/scripts/usage_ledger.py seed       # write demo rows (clearable)
    python .claude/scripts/usage_ledger.py clear       # truncate the ledger
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

try:
    from shared import DATA, file_lock  # type: ignore
except ImportError:  # allow running from repo root
    from pathlib import Path
    DATA = Path(__file__).resolve().parents[2] / ".claude" / "data"

    class file_lock:  # minimal fallback: no cross-process locking
        def __init__(self, *a, **k): ...
        def __enter__(self): return self
        def __exit__(self, *a): return False

LEDGER = DATA / "usage.jsonl"


def _provider_for(model: str) -> str:
    m = (model or "").lower()
    # SECONDBRAIN_MODEL is set to a bare alias ("sonnet", "opus", "haiku", "fable"),
    # not a full model id, so prefix-matching on "claude" alone bucketed every
    # heartbeat and memory-flush row as "other" in the dashboard. Found 2026-07-26.
    if m in {"sonnet", "opus", "haiku", "fable"}:
        return "claude"
    if m.startswith("claude") or m.startswith("anthropic"):
        return "claude"
    if m.startswith("gpt") or m.startswith("o1") or m.startswith("o3") or m.startswith("openai"):
        return "openai"
    if m.startswith("gemini"):
        return "google"
    return "other"


def record_usage(model: str, input_tokens: int, output_tokens: int,
                 cost_usd: float, source: str, *, provider: str | None = None,
                 cache_read_tokens: int = 0, subscription: bool = False) -> None:
    """Append one usage row. Never raises - metering must not break the caller.

    `subscription=True` means the call authenticated with a subscription CLI
    (`claude -p`, `codex exec`) rather than a metered API key. The CLI still
    reports a dollar figure, but it is what the same tokens would have cost via
    API - not money spent. Those rows bill $0 and keep the figure under
    `notional_cost_usd`, so the panel shows what the owner actually pays while
    the API-equivalent value stays available.
    """
    try:
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        billed = 0.0 if subscription else float(cost_usd or 0.0)
        row = {
            "ts": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "provider": provider or _provider_for(model),
            "model": model or "unknown",
            "input_tokens": int(input_tokens or 0),
            "output_tokens": int(output_tokens or 0),
            "cache_read_tokens": int(cache_read_tokens or 0),
            "cost_usd": round(billed, 6),
            "source": source,
        }
        if subscription:
            row["billing"] = "subscription"
            row["notional_cost_usd"] = round(float(cost_usd or 0.0), 6)
        with file_lock(LEDGER):
            with open(LEDGER, "a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
    except Exception:
        pass


def record_from_sdk_result(result, source: str, model: str) -> None:
    """Extract tokens + cost from a claude_agent_sdk ResultMessage and record it.
    Tolerant of shape drift: reads .usage dict + .total_cost_usd defensively."""
    try:
        usage = getattr(result, "usage", None) or {}
        get = usage.get if isinstance(usage, dict) else (lambda k, d=0: getattr(usage, k, d))
        record_usage(
            model=model,
            input_tokens=get("input_tokens", 0),
            output_tokens=get("output_tokens", 0),
            cache_read_tokens=get("cache_read_input_tokens", 0),
            cost_usd=getattr(result, "total_cost_usd", 0.0) or 0.0,
            source=source,
        )
    except Exception:
        pass


def _summary() -> None:
    if not LEDGER.exists():
        print("No usage recorded yet.")
        return
    month = datetime.now().strftime("%Y-%m")
    by_model: dict[str, list[float]] = {}
    total = 0.0
    with open(LEDGER, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            if not str(r.get("ts", "")).startswith(month):
                continue
            c = float(r.get("cost_usd", 0))
            total += c
            by_model.setdefault(r.get("model", "unknown"), [0, 0.0])
            by_model[r["model"]][0] += 1
            by_model[r["model"]][1] += c
    print(f"Month-to-date ({month}): ${total:.2f}")
    for model, (n, cost) in sorted(by_model.items(), key=lambda kv: -kv[1][1]):
        print(f"  {model:<24} {n:>4} calls  ${cost:.2f}")


def _seed() -> None:
    """Write representative rows so the panel is populated for verification.
    Clearable with `clear` - .claude/data/ is gitignored, so this never commits."""
    demo = [
        ("claude-fable-5", 42000, 5200, 0.63, "interactive"),
        ("claude-fable-5", 38000, 4800, 0.58, "interactive"),
        ("claude-opus-4-8", 51000, 6100, 0.42, "interactive"),
        ("claude-sonnet-5", 12000, 1500, 0.06, "heartbeat"),
        ("claude-sonnet-5", 11000, 1400, 0.05, "memory-flush"),
        ("gpt-5.4", 8000, 900, 0.12, "other-app"),
    ]
    for model, i, o, cost, src in demo:
        record_usage(model=model, input_tokens=i, output_tokens=o, cost_usd=cost, source=src)
    print(f"Seeded {len(demo)} demo rows to {LEDGER}")


def _clear() -> None:
    if LEDGER.exists():
        LEDGER.unlink()
    print("Ledger cleared.")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "summary"
    {"summary": _summary, "seed": _seed, "clear": _clear}.get(cmd, _summary)()
