"""Report what actually moved on one project, and what has stalled.

The producer gathers the evidence deterministically - recently modified vault
files, recent commits, recent meeting notes - and hands it over in the payload.
The model's job is judgment, not collection. That split matters: Bash is
withheld from ALLOWED_TOOLS, so this job cannot shell out, and the
command-guard hook never has to adjudicate a `git log` from an unattended
worker.

Tool-using and REVIEW_REQUIRED=False, same reasoning as research_lit_review:
the only effect is a file under VAULT/Memory/projects/.

Opus rather than sonnet. Noticing that a project has gone quiet for three weeks
is exactly the inference that a cheaper model renders as "progress continues."
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared import MEMORY, atomic_write_text, now  # noqa: E402

KIND = "research.project_pulse"
DEFAULT_RUNTIME = "claude"
SENSITIVITY = "internal"
REVIEW_REQUIRED = False         # on_result writes only to VAULT/Memory/projects/
TIMEOUT = 900
MODEL = "opus"                  # "this stalled" is the whole value; do not downgrade
ALLOWED_TOOLS = []

SCHEMA = {
    "type": "object",
    "required": [
        "momentum", "what_moved", "what_did_not", "open_questions",
        "suggested_focus",
    ],
    "properties": {
        "momentum": {
            "type": "string",
            "enum": ["advancing", "steady", "stalled", "blocked"],
        },
        "what_moved": {"type": "array", "items": {"type": "string"}},
        "what_did_not": {"type": "array", "items": {"type": "string"}},
        "open_questions": {"type": "array", "items": {"type": "string"}},
        "suggested_focus": {"type": "string"},
    },
}

_SAFE = re.compile(r"[^\w.\- ]+")


def pulse_dir() -> Path:
    return MEMORY / "projects"


def _slug(name: str) -> str:
    return (_SAFE.sub("", name or "").strip().replace(" ", "-").lower()[:50]
            or "project")


def _section(lines: list, heading: str, items, limit: int, empty: str) -> None:
    lines.append(heading)
    if items:
        lines.extend(f"  {i}" for i in items[:limit])
    else:
        lines.append(f"  {empty}")


def _render_evidence(p: dict) -> str:
    """Evidence the producer collected. Empty sections are meaningful."""
    lines: list = []
    _section(lines, "Recently modified files in the project's vault folders:",
             p.get("recent_files"), 40,
             "(none in the window - this is a signal, not a gap)")
    _section(lines, "\nRecent commits touching this project:",
             p.get("recent_commits"), 30, "(none)")
    _section(lines, "\nRecent meeting notes mentioning this project:",
             p.get("recent_meetings"), 20, "(none)")
    return "\n".join(lines)


def build_prompt(payload) -> str:
    p = payload or {}
    project = p.get("project", "(unnamed project)")
    window = p.get("window_days", 14)
    last_pulse = p.get("last_pulse") or "(no previous pulse)"

    return f"""Assess progress for one of The Owner's research projects.
Return only the JSON object matching the supplied schema.

PROJECT
{project}

Previous pulse: {last_pulse}

RULES
- Evidence-bound. Every item in what_moved must trace to a listed file,
  commit, or meeting note. If the evidence does not support a claim, drop it.
- An empty evidence list means the project is quiet. Report that. Do not
  manufacture progress to fill the section - a falsely reassuring pulse is
  worse than none, because they will act on it.
- momentum "stalled" is a normal, useful answer. Use it when warranted.
- Never infer experimental results. You can see file names and commit
  subjects, not data.
- Do not read or write files and do not request tools. The evidence below is
  the complete allowed input. A deterministic local hook writes the report.

EVIDENCE (collected deterministically over the last {window} days)
{_render_evidence(p)}
"""


def _section_markdown(title: str, values) -> list[str]:
    items = [str(item).strip() for item in (values or []) if str(item).strip()]
    return [f"## {title}", "", *([f"- {item}" for item in items] or ["- None."]), ""]


def on_result(job, result) -> None:
    """Write the model's structured assessment locally and deterministically."""
    payload = job.get("payload") or {}
    project = str(payload.get("project") or "(unnamed project)")
    dest = pulse_dir() / f"{now():%Y-%m-%d}_pulse_{_slug(project)}.md"
    lines = [
        "---",
        "type: project-pulse",
        f"project: {project}",
        f"window_days: {payload.get('window_days', 14)}",
        f"created: {now():%Y-%m-%d %H:%M}",
        f"momentum: {result.get('momentum', 'steady')}",
        "---",
        "",
    ]
    lines += _section_markdown("What moved", result.get("what_moved"))
    lines += _section_markdown("What did not", result.get("what_did_not"))
    lines += _section_markdown("Open questions", result.get("open_questions"))
    lines += [
        "## Suggested focus",
        "",
        str(result.get("suggested_focus") or "No specific focus proposed.").strip(),
        "",
    ]
    atomic_write_text(dest, "\n".join(lines))


def apply(job, result) -> None:
    """No-op: REVIEW_REQUIRED is False, so this is never called."""
    return None
