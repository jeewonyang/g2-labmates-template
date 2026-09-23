"""PreToolUse hook: SOUL.md write-protection (anti soul-drift).

Background agents (heartbeat, reflection, flush, chat - anything with
CLAUDE_INVOKED_BY set) may not Edit/Write SOUL.md. They must write suggestions
to the daily log instead; only interactive sessions (where the owner is present
and the agent tells them first, per SOUL.md's own rules) may change it.

Deny = exit code 2 with the reason on stderr.
"""

import json
import os
import sys


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return 0
    if not os.environ.get("CLAUDE_INVOKED_BY"):
        return 0  # interactive session - allowed (agent must tell the owner first)

    tool_input = payload.get("tool_input", {}) or {}
    target = str(tool_input.get("file_path", "") or tool_input.get("path", ""))
    if target.replace("\\", "/").lower().endswith("/soul.md") or \
            target.lower() == "soul.md":
        print("SOUL.md is write-protected for background agents. Append your "
              "suggested change to today's daily log under '### Reflection "
              "suggestions for SOUL.md' instead.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
