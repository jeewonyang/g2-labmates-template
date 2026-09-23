"""PreToolUse hook: dangerous-command guard (Bash/PowerShell).

Checks every shell command against shared.DANGEROUS_BASH_PATTERNS -
destructive operations, exfiltration, package installs, privilege
escalation, and outbound calls to non-allowlisted hosts. Subshell contents
($(...) and backticks) are recursively extracted and re-checked; binary path
prefixes are stripped before matching.

Distinct from block-secrets.py (credential files). Both run on every shell
tool call. Deny = exit 2.

Interactive sessions (CLAUDE_INVOKED_BY unset) get a softer policy: the
permission system already prompts the owner there, so we only hard-block the
never-delete/exfil classes; background agents get the full list.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from shared import check_dangerous_command  # noqa: E402

# Pattern fragments that are ALWAYS blocked, even interactively (the owner's
# never-delete boundary + exfiltration). Everything else is hard-blocked only
# for background agents.
ALWAYS_BLOCK_FRAGMENTS = (
    "rm\\s+", "del\\s+", "rmdir", "rd\\s+", "remove-item", "mkfs", "dd\\s+if=",
    "format", "diskpart", "truncate", "exfil", "non-allowlisted",
    "\\|\\s*(sh|bash)", "invoke-expression", "iex", "nc\\s+", "scp", "ftp",
    "base64",
)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return 0
    if payload.get("tool_name", "") not in ("Bash", "PowerShell"):
        return 0
    command = str((payload.get("tool_input") or {}).get("command", ""))
    if not command:
        return 0

    reasons = check_dangerous_command(command)
    if not reasons:
        return 0

    background = bool(os.environ.get("CLAUDE_INVOKED_BY"))
    if not background:
        reasons = [r for r in reasons
                   if any(f in r for f in ALWAYS_BLOCK_FRAGMENTS)]
    if not reasons:
        return 0

    print("BLOCKED by command guard: matched dangerous pattern(s): "
          + "; ".join(reasons[:4])
          + ". Destructive/exfiltrating commands are not allowed"
          + (" for background agents." if background else
             " (never-delete boundary). Ask the owner to run this themselves if "
             "it is genuinely needed."), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
