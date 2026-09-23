"""SessionStart hook: inject the memory vault into every conversation.

Reads SOUL.md + USER.md + MEMORY.md + the two most recent daily logs and
returns them as additionalContext. If BOOTSTRAP.md exists (first run /
unfinished onboarding), it is injected first with instructions to run it.

Also emits a one-line index of the ON_DEMAND files - the deeper research and
career context merged in 2026-07-25. Those are NOT injected (they would blow
the context budget); the index exists so the agent knows they are there and
can Read them when a task actually needs them.

Contract: JSON on stdout with hookSpecificOutput.additionalContext, exit 0.
Must never crash a session - on any error, exit 0 with no output.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from shared import DAILY, MEMORY, STATE_DIR, log_line  # noqa: E402

MAX_FILE_CHARS = 12_000
MAX_LOG_CHARS = 6_000

# Read on demand, never auto-injected. Keep in sync with the "On-demand context
# files" section of USER.md.
ON_DEMAND = {
    "PLAYBOOK.md": "scientific taste, brainstorming, experimental design, publication strategy - read before research discussion",
    "AI_WORKFLOW.md": "how to operate as a research collaborator; coding preferences; session closeout",
    "ACTIVE_PROJECTS.md": "live project state, bottlenecks, next decisions (weekly cadence)",
    "CAREER.md": "career direction and decision criteria",
    "COLLABORATORS.md": "verified people, roles, and working context",
    "LAB_PROTOCOLS.md": "protocol index and capture template",
}


def read_capped(path: Path, cap: int) -> str | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    if not text:
        return None
    if len(text) > cap:
        text = text[:cap] + "\n\n[... truncated ...]"
    return text


def main() -> int:
    try:
        json.load(sys.stdin)  # payload unused; consume so the pipe closes cleanly
    except (json.JSONDecodeError, OSError):
        pass

    parts = []

    bootstrap = read_capped(MEMORY / "BOOTSTRAP.md", MAX_FILE_CHARS)
    if not bootstrap and not (MEMORY / "USER.md").is_file():
        # A fresh clone: the vault does not exist yet (it is never committed),
        # so onboarding runs from the template copy until init_vault.py has
        # created VAULT/Memory/.
        template = MEMORY.parents[1] / "vault-template" / "Memory" / "BOOTSTRAP.md"
        bootstrap = read_capped(template, MAX_FILE_CHARS)
    if bootstrap:
        parts.append(
            "<bootstrap priority=\"first\">\n"
            "Onboarding is not finished. At the START of this session, before "
            "anything else, follow these instructions:\n\n" + bootstrap + "\n</bootstrap>"
        )

    for name in ("SOUL.md", "USER.md", "MEMORY.md"):
        content = read_capped(MEMORY / name, MAX_FILE_CHARS)
        if content:
            parts.append(f"<memory_file name=\"{name}\">\n{content}\n</memory_file>")

    available = []
    for name, blurb in ON_DEMAND.items():
        try:
            if (MEMORY / name).is_file():
                available.append(f"- `VAULT/Memory/{name}` - {blurb}")
        except OSError:
            continue
    if available:
        parts.append(
            "<memory_index note=\"not loaded - Read these when the task needs them\">\n"
            + "\n".join(available)
            + "\n</memory_index>"
        )

    try:
        logs = sorted(DAILY.glob("????-??-??.md"))[-2:]
    except OSError:
        logs = []
    for log in logs:
        content = read_capped(log, MAX_LOG_CHARS)
        if content:
            parts.append(f"<daily_log name=\"{log.name}\">\n{content}\n</daily_log>")

    # Give every interactive Claude/Codex agent the same operational picture
    # as the dashboard. The snapshot contains titles/dates/relationships only,
    # never inbox raw text or note bodies.
    taskflow_path = STATE_DIR / "agent-taskflow.json"
    try:
        from capture_sync import refresh_taskflow_snapshot
        refresh_taskflow_snapshot()
    except Exception as e:
        log_line("hooks", f"taskflow refresh skipped: {e!r}")
    taskflow = read_capped(taskflow_path, 12_000)
    if taskflow:
        parts.append(
            "<current_taskflow source=\"Prisma operational snapshot\">\n"
            + taskflow
            + "\n</current_taskflow>"
        )

    if parts:
        context = (
            "# Second Brain memory (injected by SessionStart hook)\n\n"
            + "\n\n".join(parts)
        )
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": context,
            }
        }))
        log_line("hooks", f"SessionStart: injected {len(parts)} memory sections")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # never break a session
        log_line("hooks", f"SessionStart ERROR: {e!r}")
        sys.exit(0)
