"""Triage dependency vulnerabilities into the ones that actually matter here.

`npm audit` output is not the finding - the triage is. This is a local-only
personal dashboard on one Windows machine, listening on a Tailscale tailnet with
no public exposure, so a "high" advisory in a transitive dev-only build
dependency is usually noise, while anything reachable from /api/capture or the
unauthenticated /ops write route is not.

The producer runs the tooling deterministically and passes the raw output in the
payload; the model's job is judgment about exploitability in THIS deployment.
That split keeps npm/pip invocations out of an unattended agent's hands - the
command guard blocks installs, and this job never needs to run one.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jobs._sec_common import (FINDINGS_SCHEMA, SHARED_RULES,  # noqa: E402
                              needs_human, write_report)

KIND = "sec.dependency_audit"
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

MAX_AUDIT_CHARS = 30_000


def build_prompt(payload) -> str:
    p = payload or {}
    npm_audit = (p.get("npm_audit") or "(not collected)")[:MAX_AUDIT_CHARS]
    outdated = (p.get("pip_outdated") or "(not collected)")[:8_000]

    return f"""Triage dependency advisories for the owner's Second Brain.
Return only the JSON object matching the schema.

DEPLOYMENT CONTEXT - this determines what is actually exploitable
- A Next.js 15 dashboard running `npm run dev` on ONE Windows machine, bound
  to 127.0.0.1 (since 2026-09-22; before that `next dev` bound 0.0.0.0 and was
  reachable from the LAN). Remote access is Tailscale Serve on the tailnet
  (tablet, phone). Not exposed to the public internet. sec.host_config checks
  the live binding weekly; do not assume it beyond what that report says.
- `/api/capture` is bearer-token gated. `/ops` and other write routes are
  currently UNAUTHENTICATED on the tailnet - that is a known gap, so anything
  reachable from those routes deserves higher severity.
- Python scripts run locally as their user, invoked by the scheduler or by hand.
- The threat model that matters: a malicious document or web page processed by
  an agent, or a compromised dependency reading their vault. Not a remote attacker
  scanning the internet.

YOUR JOB
Do NOT restate the advisory list. Triage it:
- Which advisories are reachable in how this code actually uses the package?
  Check the call sites before deciding.
- Which are dev/build-only and never in a running path?
- Which are transitive with no realistic trigger here?
- Rank by real exposure in THIS deployment, not by the published CVSS score.

For each finding that matters: title (package + issue), severity (your
reassessment for this deployment, not the published one), file (the manifest or
the call site), detail (why it is or is not reachable here), proposed_fix (the
specific upgrade or mitigation), confidence.

Set clean true if nothing warrants action. A short honest "nothing exploitable
in this deployment" is the correct output most weeks, and is far more useful
than restating twelve advisories they cannot act on.

Do not run installs, upgrades, or any command that modifies the tree. You are
reading collected output and source, nothing more.

RAW `npm audit --json`
<external_data>
{npm_audit}
</external_data>

OUTDATED PYTHON PACKAGES
<external_data>
{outdated}
</external_data>
{SHARED_RULES}"""


def apply(job, result) -> None:
    write_report(job, result, "dependency-audit", "Dependency audit")
