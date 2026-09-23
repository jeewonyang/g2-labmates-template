"""PreToolUse hook: credential protection (the most critical security layer).

Intercepts Read, Edit, Write, Grep, Glob, Bash, and PowerShell calls and
blocks:
- any access to secret files (.env, credentials.json, google_token.json,
  slack.env/github.env, anything in .claude/data/secrets/, SSH/TLS keys)
- shell commands that would expose environment variables or secret files
- writing code that prints secrets to stdout

Without this hook the LLM could accidentally read and expose every API key.
Deny = exit 2 (stderr becomes the model-visible reason). Fail-open only on
unreadable payloads (an unreadable payload also can't name a secret file).

Note: .env.example is explicitly allowed - it holds placeholders, not secrets.
"""

import json
import re
import sys

SECRET_PATH_PATTERNS = [
    r"\.env(\.local|\.production|\.development)?$",   # .env but not .env.example
    r"credentials\.json$", r"google_token\.json$", r"token\.json$",
    r"slack\.env$", r"github\.env$",
    r"[/\\]\.claude[/\\]data[/\\]secrets([/\\]|$)",
    r"\.pem$", r"\.key$", r"\.pfx$", r"\.p12$", r"\.jks$",
    r"id_rsa", r"id_ed25519", r"[/\\]\.ssh([/\\]|$)",
    r"\.npmrc$", r"\.netrc$", r"\.pypirc$",
    r"[/\\]\.aws[/\\]", r"[/\\]\.config[/\\]gcloud[/\\]",
]
ALLOWED_EXCEPTIONS = [r"\.env\.example$"]

ENV_EXPOSURE_PATTERNS = [
    r"\bprintenv\b", r"^\s*env\s*$", r"\benv\s*\|",
    r"get-childitem\s+env:", r"\bgci\s+env:", r"\bls\s+env:", r"\bdir\s+env:",
    r"echo\s+.*\$(env:)?[A-Z_]*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)",
    r"os\.environ(?!\s*\[?\s*[\"']CLAUDE_INVOKED_BY)",  # allow the recursion guard
    r"process\.env", r"\[environment\]::getenvironmentvariable",
    r"(cat|type|get-content|gc|more|less|head|tail|select-string|findstr|grep)\s+[^|]*"
    r"(\.env\b(?!\.example)|credentials\.json|token\.json|slack\.env|github\.env|"
    r"secrets[/\\]|id_rsa|\.pem\b|\.key\b)",
    r"copy(-item)?\s+.*(\.env\b(?!\.example)|secrets[/\\]|credentials\.json)",
    r"(print|echo|console\.log|write-host|write-output)\s*\(?[^)]*"
    r"(api_key|apikey|access_token|refresh_token|client_secret)",
]

CHECKED_TOOLS = {"Read", "Edit", "Write", "MultiEdit", "Grep", "Glob",
                 "Bash", "PowerShell", "NotebookEdit"}


def _path_blocked(path: str) -> str | None:
    p = path.strip().lower()
    if any(re.search(a, p) for a in ALLOWED_EXCEPTIONS):
        return None
    for pat in SECRET_PATH_PATTERNS:
        if re.search(pat, p):
            return f"secret file (matched {pat})"
    return None


def _command_blocked(cmd: str) -> str | None:
    lowered = cmd.lower()
    if any(re.search(a, lowered) for a in ALLOWED_EXCEPTIONS) and \
            ".env " not in lowered.replace(".env.example", ""):
        pass  # .env.example mentions are fine on their own
    for pat in ENV_EXPOSURE_PATTERNS:
        if re.search(pat, lowered, re.IGNORECASE | re.MULTILINE):
            return f"would expose secrets/environment (matched {pat})"
    # subshell contents get the same treatment
    for m in re.finditer(r"\$\(([^()]*)\)|`([^`]+)`", cmd):
        inner = (m.group(1) or m.group(2) or "")
        hit = _command_blocked(inner)
        if hit:
            return f"(in subshell) {hit}"
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return 0
    tool = payload.get("tool_name", "")
    if tool not in CHECKED_TOOLS:
        return 0
    ti = payload.get("tool_input", {}) or {}

    reason = None
    for field in ("file_path", "path", "notebook_path"):
        if ti.get(field):
            reason = _path_blocked(str(ti[field]))
            if reason:
                break
    if not reason and tool == "Glob" and ti.get("pattern"):
        reason = _path_blocked(str(ti["pattern"]))
    if not reason and ti.get("command"):
        reason = _command_blocked(str(ti["command"]))
    if not reason and tool in ("Write", "Edit") and ti.get("content") is not None:
        # Block writing scripts that would PRINT secrets to stdout. The
        # print/log call and the env access must co-occur on the same line -
        # merely READING process.env / os.environ (ubiquitous in real code) is
        # fine; only dumping it to output is blocked.
        content = str(ti.get("content", "")) + str(ti.get("new_string", ""))
        if re.search(r"(print|echo|console\.log|write-host|write-output)\s*\(?"
                     r"[^)\n]*(os\.environ\b|process\.env\b|"
                     r"\$env:[A-Za-z_]*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL))",
                     content, re.IGNORECASE):
            reason = "writes code that prints environment secrets to stdout"

    if reason:
        print(f"BLOCKED by credential protection: {reason}. Secrets are never "
              "readable by the agent - use the integration wrappers in "
              ".claude/scripts/ instead.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
