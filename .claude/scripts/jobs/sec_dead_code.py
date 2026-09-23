"""Find code and state that nothing references any more.

The "keep the codebase tidy" half of the IT/Security team. It reports; it never
removes. The never-delete rule has no tidiness exception, and this repo has
already lost files to unattended cleanup once - sequence files went missing from
`archive/` on their own (MEMORY.md, Lessons Learned 2026-07-25), which is
exactly why an agent proposing deletions must never perform them.

Be conservative. A false positive here invites them to delete something load-
bearing, so the cost of a wrong finding is much higher than the cost of a missed
one. Dynamic dispatch makes this genuinely hard in both languages used here:
the job registry imports modules by pkgutil scan, and integrations resolve
through registry.py, so "no static reference" does not mean unused.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jobs._sec_common import (FINDINGS_SCHEMA, SHARED_RULES,  # noqa: E402
                              needs_human, write_report)

KIND = "sec.dead_code"
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


def build_prompt(payload) -> str:
    return f"""Find dead code and stale state in the owner's Second Brain.
Return only the JSON object matching the schema.

WHAT COUNTS
- Modules, functions, or exported symbols with no reference anywhere.
- React components and routes under src/ that nothing renders or links to.
- Python scripts in .claude/scripts/ that no hook, job, scheduler task, API
  route, or doc invokes.
- State files under .claude/data/state/ written by code that no longer exists.
- Config keys, env vars, and package.json dependencies nothing reads.
- Superseded duplicates: two implementations where only one is wired up.

BEFORE YOU FLAG ANYTHING - dynamic references are everywhere in this repo
- `.claude/scripts/jobs/` modules are loaded by a pkgutil scan in jobs/__init__.py.
  NO module there is dead just because nothing imports it by name. Check whether
  its KIND appears in a team manifest under .claude/agents/teams/ instead.
- `.claude/scripts/integrations/` resolve through registry.py and query.py
  subcommand dispatch, not direct imports.
- `.claude/scripts/runtimes/` are selected by string name in runtimes.get().
- Hooks are wired by path in .claude/settings.json and .codex/hooks.json -
  grep both before calling a hook script unused.
- Next.js App Router files (page.tsx, route.ts, layout.tsx) are routed by
  filesystem convention and are never referenced by an import.
- Skills in .claude/skills/ are invoked by name from chat.
- A script named only in CLAUDE.md or docs/ is still in use - it is documented
  for them to run by hand.

If you cannot rule out a dynamic reference, either do not report it, or report
it with confidence below 0.5 and say explicitly what you could not verify.

EXPLICITLY OUT OF SCOPE - do not flag these as dead
- Anything under archive/, AppDev/, or node_modules/. These are gitignored on
  purpose.
- .env.example.
- Historical sections of CLAUDE.md describing removed features.

For each finding: title, severity (dead code is `low` or `info` - it is tidiness,
not risk, unless it is a stale security control), file, line, detail (including
HOW you verified nothing references it), evidence, proposed_fix (say "remove
after confirming" - never "removed"), confidence.

You are proposing a review list, not a deletion plan. Nothing you report will be
acted on without the owner reading it first, and they have asked that nothing ever
be deleted without their explicit say-so.
{SHARED_RULES}"""


def apply(job, result) -> None:
    write_report(job, result, "dead-code", "Dead code and stale state")
