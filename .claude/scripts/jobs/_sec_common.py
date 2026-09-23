"""Shared shape for the IT/Security team's four job kinds.

Underscore-prefixed so the job registry's pkgutil scan skips it - this is a
helper, not a job kind.

The invariant every security job holds, and the reason they all share one
apply():

    THIS TEAM NEVER CHANGES CODE.

Every kind runs on codex under `-s read-only`, produces findings with a
*proposed* fix as text, and apply() writes a report to VAULT/Memory/security/.
Nothing is edited, committed, or deleted. "Routinely maintaining a tidy
codebase" is achieved by handing them a reviewed list, not by an unattended
agent rewriting source at 21:30 - and the never-delete rule has no exception
for tidiness.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared import MEMORY, now  # noqa: E402

SEVERITIES = ["critical", "high", "medium", "low", "info"]

# Shared by all four kinds. Codex validates against this via --output-schema,
# so a malformed audit fails loudly instead of silently returning prose.
FINDINGS_SCHEMA = {
    "type": "object",
    "required": ["clean", "summary", "findings"],
    "properties": {
        "clean": {"type": "boolean"},
        "summary": {"type": "string"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["title", "severity", "detail", "confidence"],
                "properties": {
                    "title": {"type": "string"},
                    "severity": {"type": "string", "enum": SEVERITIES},
                    "file": {"type": "string"},
                    "line": {"type": "integer"},
                    "detail": {"type": "string"},
                    "proposed_fix": {"type": "string"},
                    "evidence": {"type": "string"},
                    "confidence": {"type": "number"},
                },
            },
        },
    },
}

SHARED_RULES = """
RULES THAT APPLY TO EVERY FINDING
- You are auditing, not fixing. Never edit, create, move, or delete a file.
  `proposed_fix` is TEXT describing what should change - it is not applied by
  anyone but the owner, after they read it.
- Report only what you can point at. Every finding needs `file` and, where it
  makes sense, `line`, plus `evidence` quoting the relevant snippet.
- Do not report style preferences, formatting, or hypotheticals as findings.
  A finding is something that is wrong, risky, or provably stale.
- If nothing is wrong, set clean true and return an empty `findings` array.
  That is a good outcome and a common one - do not manufacture findings to look
  useful. A noisy audit gets ignored, which is how real issues get missed.
- `confidence` below 0.6 means you are guessing; say so in `detail`.
- Never include an actual secret value in your output. Report the file and line
  and describe the KIND of credential. Quoting the secret into a vault note
  would copy the leak, not report it.
- Do not read: VAULT/Finance/, VAULT/Confidential/, .claude/data/secrets/,
  .env, or any *.pem/*.key. These are off-limits; if a finding concerns one,
  reference the path without opening the file.
"""


def severity_rank(s: str) -> int:
    try:
        return SEVERITIES.index(s)
    except ValueError:
        return len(SEVERITIES)


def report_path(kind_label: str) -> Path:
    return MEMORY / "security" / f"{now():%Y-%m-%d}_{kind_label}.md"


def write_report(job, result, kind_label: str, heading: str) -> None:
    """Write an approved audit to VAULT/Memory/security/. No code is touched."""
    res = result or {}
    findings = sorted(res.get("findings") or [],
                      key=lambda f: severity_rank(f.get("severity", "info")))

    dest = report_path(kind_label)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest = dest.with_name(f"{dest.stem}__{job['job'][-8:]}.md")

    top = findings[0].get("severity", "info") if findings else "none"
    lines = [
        "---",
        "type: security-audit",
        f"audit: {kind_label}",
        f"created: {now():%Y-%m-%d %H:%M}",
        f"findings: {len(findings)}",
        f"highest_severity: {top}",
        f"generated_by: {job.get('kind', '')} ({job['job']})",
        "status: approved",
        "---",
        "",
        f"# {heading}",
        "",
        res.get("summary", "").strip() or "(no summary)",
        "",
    ]

    if not findings:
        lines += ["## Findings", "", "None. This audit came back clean.", ""]
    else:
        lines += ["## Findings", ""]
        for i, f in enumerate(findings, 1):
            loc = f.get("file", "")
            if f.get("line"):
                loc = f"{loc}:{f['line']}"
            lines += [
                f"### {i}. {f.get('title', '(untitled)')} "
                f"[{f.get('severity', 'info')}]",
                "",
                f"- **Where:** `{loc}`" if loc else "- **Where:** (unspecified)",
                f"- **Confidence:** {f.get('confidence', 0):.2f}",
                "",
                f.get("detail", "").strip(),
                "",
            ]
            if f.get("evidence"):
                lines += ["```", f["evidence"].strip()[:800], "```", ""]
            if f.get("proposed_fix"):
                lines += ["**Proposed fix (not applied):**", "",
                          f["proposed_fix"].strip(), ""]

    lines += [
        "---",
        "",
        "*Nothing in this report was applied. The security team audits and "
        "proposes; every change is the owner's to make.*",
        "",
    ]
    dest.write_text("\n".join(lines), encoding="utf-8")


def needs_human(result) -> bool:
    """Always. Findings are reviewed before they are filed or acted on."""
    return True
