"""Summarize one vault source into a wiki page draft.

Routed to **codex** rather than claude: this is structured extraction, and
`codex exec --output-schema` gives JSON-Schema-validated output instead of
prompt-and-hope. It is also the only cloud runtime currently working without an
API key (ChatGPT login), so this is the job kind that proves the cloud path end
to end while the Claude CLI is still uninstalled.

The wiki itself stays owned by wiki_build.py; this job produces the *content*
for a page and hands it to review. Nothing is written until approved, because a
wiki page is a file outside VAULT/Memory/... - actually it is inside Memory/,
but it is human-facing curated knowledge, so it keeps the review gate.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared import REPO_ROOT  # noqa: E402
import skill_rules  # noqa: E402
from triage import extract as extractor  # noqa: E402

KIND = "wiki.ingest"
DEFAULT_RUNTIME = "codex"
SENSITIVITY = "internal"        # only ever pointed at non-private sources
REVIEW_REQUIRED = True
TIMEOUT = 600

SCHEMA = {
    "type": "object",
    "required": ["title", "slug", "type", "summary", "key_points", "links"],
    "properties": {
        "title": {"type": "string"},
        "slug": {"type": "string"},
        "type": {"type": "string",
                 "enum": ["concept", "project", "person", "method", "overview"]},
        "summary": {"type": "string"},
        "key_points": {"type": "array", "items": {"type": "string"}},
        "links": {"type": "array", "items": {"type": "string"},
                  "description": "slugs of related wiki pages, for [[wikilinks]]"},
    },
}


def _existing_slugs(limit: int = 60) -> list[str]:
    pages = REPO_ROOT / "VAULT" / "Memory" / "wiki" / "pages"
    try:
        return sorted(p.stem for p in pages.glob("*.md"))[:limit]
    except OSError:
        return []


def build_prompt(payload) -> str:
    rel = (payload or {}).get("path", "")
    info = extractor.describe(REPO_ROOT / rel, REPO_ROOT)
    body = info["text"] or "(no extractable text)"
    slugs = ", ".join(_existing_slugs()) or "(none yet)"
    # Content rules are the wiki skill's, shared (skill_rules.py).
    rules = skill_rules.for_kind(KIND)
    return f"""Summarize this source into a wiki page for the owner's research
knowledge base. Their field, methods, and active projects are described in
VAULT/Memory/USER.md - read it rather than assuming a specialty.

Return only the JSON object.

RULES
{rules}
- `slug` is lowercase kebab-case, stable, and derived from the title.
- `summary` is 2-4 sentences. `key_points` are 3-6 concrete claims.
- `links` may only contain slugs from the existing list below. An empty list
  is fine.
- A source too thin for a page still returns the object, with an honest short
  summary saying so.

EXISTING PAGES (valid link targets)
{slugs}

SOURCE
  path: {info['path']}
  name: {info['name']}

CONTENT
\"\"\"
{body}
\"\"\"
"""


def apply(job, result) -> None:
    """Write the approved page into the wiki. Never overwrites silently."""
    from datetime import date
    slug = str(result.get("slug") or "").strip().lower().replace(" ", "-")
    if not slug or "/" in slug or ".." in slug:
        raise ValueError(f"unsafe slug: {slug!r}")

    pages = REPO_ROOT / "VAULT" / "Memory" / "wiki" / "pages"
    pages.mkdir(parents=True, exist_ok=True)
    dest = pages / f"{slug}.md"

    src = (job.get("payload") or {}).get("path", "")
    links = [f"[[{s}]]" for s in (result.get("links") or [])
             if isinstance(s, str) and s]
    points = "\n".join(f"- {p}" for p in (result.get("key_points") or []))

    front = (f"---\ntitle: {result.get('title', slug)}\n"
             f"type: {result.get('type', 'concept')}\n"
             f"sources: {src}\nupdated: {date.today().isoformat()}\n"
             f"generated_by: wiki.ingest ({job['job']})\n---\n\n")
    body = (f"# {result.get('title', slug)}\n\n{result.get('summary', '')}\n\n"
            f"## Key points\n\n{points}\n")
    if links:
        body += f"\n## Related\n\n{' '.join(links)}\n"

    if dest.exists():
        # Never clobber a curated page - park the new draft beside it.
        dest = pages / f"{slug}__{job['job'][-8:]}.md"
    dest.write_text(front + body, encoding="utf-8")

    # Close the loop: record the source as ingested in wiki-state.json, which
    # is the single owner of that fact. Without this the source stays `pending`
    # and the vault producer re-enqueues it on the next daily run, forever.
    # Marked only here, after approval - an unapproved draft has not ingested
    # anything.
    if src:
        import wiki_build
        # Payload paths are REPO_ROOT-relative; wiki-state.json keys are
        # VAULT-relative. Strip the prefix rather than storing both forms.
        wiki_build.mark_source_ingested(
            src[len("VAULT/"):] if src.startswith("VAULT/") else src)
