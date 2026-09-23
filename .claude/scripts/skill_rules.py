"""One text, two readers: the rules a chat skill and its scheduled job share.

A skill (`.claude/skills/<name>/SKILL.md`) is what the interactive session
follows; a job module is what the dispatcher runs at 05:00. Until 2026-09-22
each carried its own copy of the same rules (when to draft, how to judge a
paper's relevance, what never to invent from a meeting), and the copies drifted
- the draft-replies skill still said "every DM gets a draft" a month after they
changed that bar in the job.

Now the skill owns the rules inside a marked block:

    <!-- shared:drafting -->
    ...rules both readers follow...
    <!-- /shared:drafting -->

and the job's build_prompt() splices the block in with `block()`. Only the
block is shared: the rest of a SKILL.md is chat-only (run `query.py`, search
memory, report back), which a no-tools job must never see. Editing the block
changes both readers at once; `tests/test_skill_rules.py` asserts every pairing
below is intact.

A missing block raises. A job that silently ran without its rules is exactly
the drift this module exists to end, so failing the job is the right outcome.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shared import REPO_ROOT  # noqa: E402

SKILLS_DIR = REPO_ROOT / ".claude" / "skills"

# job kind -> (skill, block). The single place a pairing is declared.
PAIRS = {
    "draft.reply": ("draft-replies", "drafting"),
    "research.lit_review": ("paper-digest", "relevance"),
    "admin.meeting_followup": ("meeting-notes", "extraction"),
    "wiki.ingest": ("wiki", "page-content"),
}


class SkillRulesError(RuntimeError):
    pass


def _pattern(name: str) -> re.Pattern:
    n = re.escape(name)
    return re.compile(rf"<!--\s*shared:{n}\s*-->\s*\n(.*?)\n\s*<!--\s*/shared:{n}\s*-->", re.S)


def block(skill: str, name: str) -> str:
    """The text between the shared markers, stripped. Raises if absent."""
    path = SKILLS_DIR / skill / "SKILL.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise SkillRulesError(f"skill {skill!r} not readable at {path}: {e}") from e
    m = _pattern(name).search(text)
    if not m or not m.group(1).strip():
        raise SkillRulesError(f"{path}: no <!-- shared:{name} --> block")
    return m.group(1).strip()


def for_kind(kind: str) -> str:
    """The shared rules a job kind's prompt must carry."""
    skill, name = PAIRS[kind]
    return block(skill, name)
