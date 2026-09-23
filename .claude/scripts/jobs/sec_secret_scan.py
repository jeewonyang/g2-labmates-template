"""Scan the working tree for credentials that are about to be committed.

The highest-value check in the system. block-secrets.py already blocks an agent
from *reading* secret files, and .gitignore is an allowlist so only Memory
markdown is versioned - but neither catches a token pasted into a tracked source
file, which is exactly how leaks actually happen. A leak in git history is
permanent.

Deliberately scoped to tracked and staged files, not the whole disk: the risk
being managed is "this reaches a commit", not "a secret exists on the machine".

Never quotes a secret value into its report - see SHARED_RULES.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jobs._sec_common import (FINDINGS_SCHEMA, SHARED_RULES,  # noqa: E402
                              needs_human, write_report)

KIND = "sec.secret_scan"
DEFAULT_RUNTIME = "codex"       # read-only sandbox + schema-validated output
SENSITIVITY = "internal"
REVIEW_REQUIRED = True
# Whole-repo read-only scans, weekly and off-hours: nothing waits on them.
# 900s stopped being enough on 2026-09-21 (stale_docs and dead_code both
# timed out once CLAUDE.md's detail moved into docs/), so give them room.
TIMEOUT = 1_800

SCHEMA = FINDINGS_SCHEMA

__all__ = ["KIND", "DEFAULT_RUNTIME", "SENSITIVITY", "REVIEW_REQUIRED",
           "TIMEOUT", "SCHEMA", "build_prompt", "apply", "needs_human"]


def build_prompt(payload) -> str:
    p = payload or {}
    changed = p.get("changed_files") or []
    listing = "\n".join(f"  {f}" for f in changed[:200]) or "  (none reported)"

    return f"""Audit the owner's Second Brain repository for credentials that
could reach a commit. Return only the JSON object matching the schema.

WHAT TO LOOK FOR
- API keys, tokens, and secrets hardcoded in tracked source: Anthropic
  (sk-ant-), OpenAI (sk-), Slack (xoxb-/xoxp-/xapp-), GitHub (ghp_/github_pat_),
  Google OAuth client secrets, AWS access keys, generic long hex/base64 blobs
  assigned to names like KEY, TOKEN, SECRET, PASSWORD.
- Credentials in files that are TRACKED by git when they should be ignored.
  Check .gitignore: this repo uses an allowlist, so only VAULT/Memory markdown
  should be versioned under VAULT/.
- Secrets echoed into logs, printed, or written into vault notes.
- Connection strings or URLs with embedded credentials.

WHAT IS NOT A FINDING
- Values in .env.example or documentation placeholders.
- The literal strings "sk-ant-...", "<your-token-here>", "xoxb-xxxx".
- Reading os.environ / process.env - that is correct practice, not a leak. A
  previous version of the block-secrets hook flagged every process.env read and
  it was a bug; do not recreate it here.
- Files under .claude/data/secrets/ existing at all. That is where secrets are
  SUPPOSED to live and the directory is gitignored. Only flag it if something
  makes those files reachable by git.

HOW TO WORK
Inspect the repository yourself - you have read-only access. Focus on tracked
files. Start with the changed files listed below if any, then sweep
.claude/scripts/, src/, and repo-root config.

CHANGED FILES SINCE LAST AUDIT
{listing}

For each finding set: title, severity, file, line, detail, evidence (the
surrounding line with the secret value REDACTED), proposed_fix, confidence.
Severity: a live credential in a tracked file is critical; a gitignore gap that
could expose one is high; a secret in a log path is medium.
{SHARED_RULES}"""


def apply(job, result) -> None:
    write_report(job, result, "secret-scan", "Secret scan")
