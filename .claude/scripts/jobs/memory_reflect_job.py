"""Consolidate one day's daily log into MEMORY.md.

The ledger-native form of memory_reflect.py. Same contract, but it runs through
the dispatcher on the Claude CLI runtime instead of making its own SDK call, so
it needs no API key and shows up on /ops like everything else.

This is a TOOL-USING job, not a structured-extraction one: it edits MEMORY.md in
place. So no SCHEMA - the runtime returns the agent's final text, and the
dispatcher completes the job with it.

REVIEW_REQUIRED is False. The effect is confined to VAULT/Memory/, which is
agent-owned state, and this ran unattended daily before the ledger existed.
Two guards keep that safe:
  - protect-soul.py denies SOUL.md writes whenever CLAUDE_INVOKED_BY is set,
    which claude_rt always sets. Identity changes become suggestions in the
    daily log instead.
  - allowed_tools withholds Bash, so the job cannot run commands.
"""

import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared import DAILY, now  # noqa: E402

KIND = "memory.reflect"
DEFAULT_RUNTIME = "claude"
SENSITIVITY = "internal"
REVIEW_REQUIRED = False         # confined to agent-owned Memory/
TIMEOUT = 900
MODEL = "opus"                  # curation judgment
ALLOWED_TOOLS = ["Read", "Edit", "Write", "Glob", "Grep"]   # no Bash

SCHEMA = None                   # tool-using; the final message is the result

# The one kind that must not fail over to another provider. Every other
# claude-routed kind returns a structured result and lets Python write the
# file, so codex can stand in for it. This one edits MEMORY.md with its own
# Edit/Write tools, and codex runs under -s read-only: the run would look
# successful and change nothing. A reflection that silently skipped a day is
# worse than one that failed loudly and can be retried. Model stepdown inside
# Claude (opus -> sonnet) still applies - that keeps the tools.
ALLOW_RUNTIME_FAILOVER = False

MAX_LOG_CHARS = 20_000


def default_date() -> str:
    return f"{(now() - timedelta(days=1)):%Y-%m-%d}"


def build_prompt(payload) -> str:
    target = (payload or {}).get("date") or default_date()
    log_path = DAILY / f"{target}.md"
    try:
        log_text = log_path.read_text(encoding="utf-8", errors="replace")[:MAX_LOG_CHARS]
    except OSError:
        log_text = ""

    if not log_text.strip():
        return (f"There is no daily log for {target} at {log_path}. "
                f"Do nothing and reply with exactly: REFLECT_SKIP no log for {target}")

    today = f"{now():%Y-%m-%d}"
    return f"""You are the daily reflection of The Owner's Second Brain. Curate
long-term memory from yesterday's log.

1. Read VAULT/Memory/MEMORY.md first.
2. Promote genuinely important items from the log into the right MEMORY.md
   sections (Key Decisions / Lessons Learned / Important Facts / Active Work /
   Preferences Confirmed) using the Edit tool.
   - MEMORY.md MUST stay concise: it loads into every conversation. Merge with
     existing entries rather than duplicating, and drop transient noise.
   - Convert relative dates to absolute. Today is {today}.
   - Promote a fact only if it will still matter in a month.
3. You may NOT edit SOUL.md - a hook blocks it. If the log suggests the agent's
   identity or rules should change, append that suggestion to
   VAULT/Memory/daily/{today}.md under
   "### Reflection suggestions for SOUL.md" instead.
4. Do not delete anything. Do not touch anything outside VAULT/Memory/.
5. End your final message with exactly one line:
   REFLECT_OK <n> items promoted
   or
   REFLECT_SKIP <reason>

Daily log for {target}:

{log_text}
"""


def apply(job, result) -> None:
    """No-op: REVIEW_REQUIRED is False, so the edits already happened in-run."""
    return None
