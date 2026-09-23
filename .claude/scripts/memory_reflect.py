"""Daily reflection: promote yesterday's important daily-log items to MEMORY.md.

Mirrors sleep consolidation: daily logs are short-term memory; this curates
them into long-term MEMORY.md once a day (scheduled 8 AM, Phase 9).

SOUL.md write-protection: the protect-soul PreToolUse hook blocks this agent
from editing SOUL.md. If the reflection thinks the agent's identity/rules
should change, it writes the SUGGESTION to the daily log for the owner instead.

Usage: python .claude/scripts/memory_reflect.py [--date YYYY-MM-DD]
"""

import os
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shared import (AGENT_MODEL, DAILY, MEMORY, append_to_daily_log,  # noqa: E402
                    load_env, log_line, now)

os.environ["CLAUDE_INVOKED_BY"] = "reflection"
load_env()


def reflect(target_date: str) -> str:
    """Consolidate a day's log into MEMORY.md, on the subscription CLI.

    Tools and setting-sources are unchanged; only the auth path moved off the
    API key. protect-soul.py still applies because CLAUDE_INVOKED_BY is set.
    """
    from runtimes import claude_rt
    log_path = DAILY / f"{target_date}.md"
    if not log_path.exists():
        return f"NO_LOG ({log_path.name} does not exist)"
    log_text = log_path.read_text(encoding="utf-8", errors="replace")[:20_000]

    system = f"""You are the daily reflection of The Owner's Second Brain.
Review the daily log below and curate long-term memory.

1. Read VAULT/Memory/MEMORY.md first.
2. Promote genuinely important items from the log into the right MEMORY.md
   sections (Key Decisions / Lessons Learned / Important Facts / Active
   Projects / Upcoming Events / Preferences Confirmed) using the Edit tool.
   - MEMORY.md must stay CONCISE - it loads into every session. Merge with
     existing entries, don't duplicate, drop transient noise.
   - Convert relative dates to absolute (today is {now():%Y-%m-%d}).
3. You may NOT edit SOUL.md (a hook blocks you). If the log suggests the
   agent's identity or rules should change, append that suggestion to today's
   daily log (VAULT/Memory/daily/{now():%Y-%m-%d}.md) under
   "### Reflection suggestions for SOUL.md" for the owner to approve.
4. Do not delete any file. Do not touch anything outside VAULT/Memory/.
5. End with one line: REFLECT_OK <n items promoted> or REFLECT_SKIP <reason>."""

    result = claude_rt.run(
        f"Daily log for {target_date}:\n\n{log_text}",
        system=system,
        allowed_tools=["Read", "Edit", "Write", "Glob", "Grep"],
        cwd=MEMORY.parents[1],
        model=AGENT_MODEL,
        max_turns=15,
        timeout=600,
        invoked_by="reflection",
        usage_source="reflection")
    if not result.ok:
        raise RuntimeError(result.error or "reflection failed")
    return result.text


def main() -> int:
    target = f"{(now() - timedelta(days=1)):%Y-%m-%d}"
    if "--date" in sys.argv:
        target = sys.argv[sys.argv.index("--date") + 1]
    log_line("reflection", f"reflecting on {target}")
    try:
        result = reflect(target)
    except Exception as e:
        log_line("reflection", f"failed: {e!r}")
        return 1
    tail = result.strip().splitlines()[-1] if result.strip() else "(empty)"
    log_line("reflection", f"done: {tail[:200]}")
    if not tail.startswith(("NO_LOG", "REFLECT_SKIP")):
        append_to_daily_log("Daily reflection", f"Reviewed {target}: {tail[:300]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
