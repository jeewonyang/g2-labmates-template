"""Check documentation claims against what is actually on disk.

The most repo-specific check in the security team, and the one most likely to
pay for itself. This project has documented paths that do not exist more than
once: CLAUDE.md carries an explicit warning that an earlier revision described a
`VAULT/01_Projects/...` tree which was never on disk, and tells the reader to
run `ls VAULT/` before trusting any path in it.

Stale docs are a security problem here, not just an annoyance. CLAUDE.md is
injected into every session and is the source of truth for the confidentiality
routing rules. A CLAUDE.md that names the wrong directory teaches every future
agent the wrong boundary.

Verification is mechanical: a claim about a path either resolves or it does not.
That makes this a high-precision check, so findings should be trustworthy.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jobs._sec_common import (FINDINGS_SCHEMA, SHARED_RULES,  # noqa: E402
                              needs_human, write_report)

KIND = "sec.stale_docs"
DEFAULT_RUNTIME = "codex"
SENSITIVITY = "internal"
REVIEW_REQUIRED = True
# Whole-repo read-only scans, weekly and off-hours: nothing waits on them.
# 900s stopped being enough on 2026-09-21 (stale_docs and dead_code both
# timed out once CLAUDE.md's detail moved into docs/), so give them room.
TIMEOUT = 1_800

SCHEMA = FINDINGS_SCHEMA

__all__ = ["KIND", "DEFAULT_RUNTIME", "SENSITIVITY", "REVIEW_REQUIRED",
           "TIMEOUT", "SCHEMA", "build_prompt", "apply", "needs_human"]

DOCS = [
    "CLAUDE.md",
    "AGENTS.md",
    "README.md",
    "docs/",
    ".agent/plans/agent-os/",
    "VAULT/Memory/README.md",
]


def build_prompt(payload) -> str:
    targets = (payload or {}).get("docs") or DOCS
    listing = "\n".join(f"  {d}" for d in targets)

    return f"""Audit the owner's Second Brain documentation for claims that no
longer match the repository. Return only the JSON object matching the schema.

WHY THIS MATTERS
CLAUDE.md is injected into every agent session and defines the confidentiality
routing rules. When it names a path that does not exist, every future agent
inherits a wrong mental model of where sensitive material lives. This repo has
had exactly that bug before.

WHAT TO CHECK - in priority order
1. **Paths that do not exist.** Every file or directory path named in the docs:
   does it resolve? Flag the ones that do not. This is the single most valuable
   check - be thorough and literal about it.
2. **Commands that would fail.** Script paths, CLI subcommands, and npm scripts
   referenced in docs: does the script exist, and does it actually accept the
   documented subcommand or flag? Check argument parsing in the source.
3. **Capabilities described that are gone.** Docs describing removed features as
   present. (Note: text explicitly marked as historical - "REMOVED", "retired",
   "was built then removed", a dated changelog entry - is NOT stale. This repo
   deliberately keeps history in CLAUDE.md. Only flag it if it reads as a
   description of current behavior.)
4. **Contradictions between docs**, especially between CLAUDE.md and AGENTS.md
   or README.md, and most especially about security rules or vault layout.
5. **Stale counts and versions** - file counts, phase numbers, model names,
   dependency versions stated in prose that no longer hold.

HOW TO VERIFY
Check the filesystem. Do not reason from memory about whether a path exists -
look. A claim is stale only if you confirmed it does not resolve.

DOCUMENTS IN SCOPE
{listing}

For each finding: title, severity, file (the DOC file making the false claim),
line, detail (what it claims vs what is true), evidence (the quoted claim),
proposed_fix (the corrected wording), confidence.
Severity: a wrong security or vault-routing rule is high; a broken command is
medium; a stale count is low.
{SHARED_RULES}"""


def apply(job, result) -> None:
    write_report(job, result, "stale-docs", "Documentation drift audit")
