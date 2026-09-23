"""LLM Wiki toolkit (Karpathy llm-wiki pattern) - deterministic, no LLM calls.

This script spends ZERO API tokens. All wiki *synthesis* (reading a source,
writing/updating pages, cross-linking) happens inside interactive Claude Code
sessions via the `wiki` skill, on the owner's subscription. This toolkit only does
the free bookkeeping around that:

  init           scaffold VAULT/Memory/wiki/ (WIKI.md schema, catalog.md, log.md, pages/)
  status         pending vs. ingested source counts + page counts by type
  plan           print the next batch of source paths to ingest (for the skill)
  mark-ingested  record sources as ingested in the state file (the skill calls this)
  lint           deterministic health check (broken links, orphans, catalog drift...)
  daily          scheduled nightly pass: scan + lint + reindex + toast reminder (no LLM)

Source enumeration mirrors memory_index.py's filters (Finance excluded, junk
dirs, data-dump heuristic). We replicate the ~15 lines rather than import
memory_index, because importing it pulls in the FastEmbed/onnx stack - far too
heavy for a tool run on every `status`. The nightly reindex shells out to
memory_index.py as a subprocess instead.

Advisor mode: writes only under VAULT/Memory/wiki/ (+ the daily log). Never
reads/indexes/references VAULT/Finance/. Never deletes pages - lint flags them.

Usage:
  python .claude/scripts/wiki_build.py init
  python .claude/scripts/wiki_build.py status [--json]
  python .claude/scripts/wiki_build.py plan [--batch-size 20] [--path-prefix Memory/] [--json]
  python .claude/scripts/wiki_build.py mark-ingested --paths <rel> [<rel> ...]
  python .claude/scripts/wiki_build.py lint [--json]
  python .claude/scripts/wiki_build.py daily
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shared import (STATE_DIR, VAULT, append_to_daily_log,  # noqa: E402
                    atomic_write_json, atomic_write_text, file_lock, log_line,
                    now, read_json)

# --- wiki layout ---
WIKI_DIR = VAULT / "Memory" / "wiki"
PAGES_DIR = WIKI_DIR / "pages"
SCHEMA_FILE = WIKI_DIR / "WIKI.md"
CATALOG_FILE = WIKI_DIR / "catalog.md"
LOG_FILE = WIKI_DIR / "log.md"
STATE_FILE = STATE_DIR / "wiki-state.json"

RESERVED_SLUGS = {"wiki", "catalog", "log", "index"}
PAGE_TYPES = {"entity", "person", "project", "concept", "overview", "summary", "meta"}

# --- source enumeration (mirrors memory_index.py filters; keep in sync) ---
#
# These drifted out of sync once already and it mattered: memory_index.py added
# "Confidential" and the 00_Inbox subdir exclusion during the 2026-07-25 vault
# reorg, and this file kept excluding only Finance. That is a real exposure
# path, not a tidiness issue - `plan` hands a list of source paths to an agent,
# which then READS them and writes wiki pages that are surfaced in the
# dashboard. Confidential/ holds immigration, medical, and third-party family
# records, and 00_Inbox demonstrably mixed in immigration paperwork.
#
# If you change these, change memory_index.py in the same commit.
_WALK_ROOT = Path("\\\\?\\" + str(VAULT)) if os.name == "nt" else VAULT
EXCLUDED_TOP = {"Finance", "Confidential"}
# Untriaged intake. Raw dumps that have not been sorted, at the second level
# (e.g. G2OS-Staging/00_Inbox).
EXCLUDED_SUBDIRS = {"00_Inbox"}
# Local-models-only vaults. Ingestion is performed by an agent session (the
# `wiki` skill) or the wiki.ingest job on codex - both cloud runtimes - and
# CLAUDE.md forbids bulk automated processing of these trees anywhere but a
# local model.
#
# This is a real capability gap, stated rather than papered over: their core
# research is exactly what a wiki should cover, and today it cannot. Closing it
# means a local-runtime ingestion path (an ollama wiki.ingest variant), not an
# opt-in flag on this walk - a flag would just move the violation to whoever
# passes it.
PRIVATE_TOP = {"Research-Private"}
JUNK_DIRS = {".git", ".ipynb_checkpoints", "__pycache__", "node_modules",
             ".venv", "venv", ".obsidian", "$RECYCLE.BIN"}
JUNK_DIR_SUFFIXES = ("_results", "_per_base_data")
TEXT_EXTENSIONS = {".md", ".txt"}
SKIP_NAMES = {"index.md"}
MAX_FILE_BYTES = 2_000_000
MIN_FILE_BYTES = 40  # empty/near-empty files carry no knowledge
# Wiki output + high-churn folders are never ingested as sources.
#
# The second group is agent-GENERATED dated output, added 2026-07-27 when the
# team producers started writing into Memory/ daily. Without it the wiki fills
# with one page per daily digest within weeks - a lit-review digest or a market
# brief is a dated artifact, not durable knowledge, and a wiki full of
# "2026-07-26 news" pages is worse than no wiki. The vault producer's job is to
# ingest what they and their sources wrote, not what the agent wrote yesterday.
#
# Memory/meetings/ IS ingested (real meeting notes are knowledge); only the
# generated actions/ subfolder under it is skipped.
EXCLUDED_PREFIXES = (
    "Memory/wiki/", "Memory/daily/", "Memory/drafts/",
    "Memory/markets/",            # dated news + watchlist brief, plus config
    "Memory/security/",           # audit reports
    "Memory/admin/",              # commitments ledger, calendar-write log
    "Memory/research/digests/",   # dated lit-review digests
    "Memory/projects/",           # dated project pulses
    "Memory/meetings/actions/",   # generated action lists
    "Memory/hr/",                 # lab-search packets, derived from their CV
    "Memory/design/",             # design reviews + style tokens: working notes
)
# Operational config files that live in Memory/ but carry no knowledge.
EXCLUDED_FILES = ("Memory/AGENT_PRIMARY.md",)
# Vendored third-party code (Arduino libs, packages) - not the owner's knowledge.
VENDORED_DIRS = {"libraries", "node_modules", "site-packages", "dist-packages",
                 "vendor", "third_party", "bower_components"}
# Never enumerate credential/secret files as wiki sources (block-secrets also
# blocks reads, but these must not even be listed or counted).
SECRET_NAME_RE = re.compile(
    r"(recovery.?code|password|secret|credential|\.env|token|api.?key|private.?key)",
    re.IGNORECASE)

# Batching for `plan`.
BATCH_SOURCES = 20
BATCH_BYTES = 250_000


def is_data_dump(text: str) -> bool:
    """True if mostly numbers/whitespace (a data table, not prose)."""
    sample = text[:4000]
    if not sample.strip():
        return True
    numeric = sum(c.isdigit() or c in ".\t ,-+eE\n" for c in sample)
    return numeric / len(sample) > 0.7


def rel_path(p: Path) -> str:
    r"""Path relative to VAULT with forward slashes. Tolerates the \\?\ long-path
    prefix on either the input (from os.walk) or the plain VAULT constant."""
    s = str(p)
    if s.startswith("\\\\?\\"):
        s = s[4:]
    base = str(VAULT)
    if base.startswith("\\\\?\\"):
        base = base[4:]
    return str(Path(s).relative_to(base)).replace("\\", "/")


def iter_source_files():
    """Yield candidate source files as (rel_path, mtime, size), applying the
    same exclusions as memory_index plus the wiki/daily/drafts prefixes."""
    blocked_top = EXCLUDED_TOP | PRIVATE_TOP
    for dirpath, dirnames, filenames in os.walk(_WALK_ROOT):
        rel_parts = Path(dirpath).relative_to(_WALK_ROOT).parts
        if rel_parts and rel_parts[0] in blocked_top:
            dirnames.clear()
            continue
        # Second-level intake folders (G2OS-Staging/00_Inbox and friends).
        if len(rel_parts) >= 2 and rel_parts[1] in EXCLUDED_SUBDIRS:
            dirnames.clear()
            continue
        dirnames[:] = [d for d in dirnames if d not in JUNK_DIRS
                       and d not in VENDORED_DIRS
                       and not d.endswith(JUNK_DIR_SUFFIXES)]
        for fn in filenames:
            if fn in SKIP_NAMES:
                continue
            if fn.startswith("._"):  # macOS AppleDouble resource forks (binary junk)
                continue
            if SECRET_NAME_RE.search(fn):
                continue
            p = Path(dirpath) / fn
            if p.suffix.lower() not in TEXT_EXTENSIONS:
                continue
            rel = rel_path(p)
            if rel.startswith(EXCLUDED_PREFIXES) or rel in EXCLUDED_FILES:
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            if not (MIN_FILE_BYTES <= st.st_size <= MAX_FILE_BYTES):
                continue
            yield rel, st.st_mtime, st.st_size


def load_state() -> dict:
    return read_json(STATE_FILE, {}) or {}


def save_state(state: dict) -> None:
    with file_lock(STATE_FILE):
        atomic_write_json(STATE_FILE, state)


def pending_sources(state: dict, path_prefix: str = "") -> list[tuple[str, float, int]]:
    """Sources whose (mtime, size) differ from the recorded state, or are new."""
    known = state.get("sources", {})
    out = []
    for rel, mtime, size in iter_source_files():
        if path_prefix and not rel.startswith(path_prefix):
            continue
        rec = known.get(rel)
        if rec is None or rec.get("mtime") != mtime or rec.get("size") != size:
            out.append((rel, mtime, size))
    return sorted(out)  # sort by rel path: folder-adjacent files cluster topically


def slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


# ---------- frontmatter + page parsing (flat single-line, matches dashboard) ----------

def parse_page(text: str) -> tuple[dict, str]:
    fm, body = {}, text
    m = re.match(r"^---\s*\r?\n(.*?)\r?\n---\s*\r?\n?(.*)$", text, re.DOTALL)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                fm[k.strip()] = v.strip()
        body = m.group(2)
    return fm, body


def read_pages() -> dict:
    """slug -> {fm, body} for every real page (skips generated index.md)."""
    pages = {}
    if not PAGES_DIR.exists():
        return pages
    for p in sorted(PAGES_DIR.glob("*.md")):
        if p.name in SKIP_NAMES:
            continue
        try:
            fm, body = parse_page(p.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        pages[p.stem] = {"fm": fm, "body": body}
    return pages


WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


def outbound_links(body: str) -> set[str]:
    """Slugs referenced by [[target]] / [[target|label]] in a page body."""
    out = set()
    for m in WIKILINK_RE.finditer(body):
        target = m.group(1).split("|", 1)[0].strip()
        out.add(slugify(target))
    return out


# ---------- subcommands ----------

def cmd_init(_args) -> int:
    PAGES_DIR.mkdir(parents=True, exist_ok=True)
    created = []
    if not SCHEMA_FILE.exists():
        atomic_write_text(SCHEMA_FILE, SCHEMA_TEMPLATE)
        created.append("WIKI.md")
    if not CATALOG_FILE.exists():
        atomic_write_text(CATALOG_FILE, CATALOG_TEMPLATE)
        created.append("catalog.md")
    if not LOG_FILE.exists():
        atomic_write_text(LOG_FILE, LOG_TEMPLATE.format(ts=f"{now():%Y-%m-%d %H:%M}"))
        created.append("log.md")
    if created:
        print(f"created: {', '.join(created)} in {rel_path(WIKI_DIR)}")
    else:
        print(f"already initialized at {rel_path(WIKI_DIR)}")
    return 0


def _counts(state: dict) -> dict:
    all_src = list(iter_source_files())
    pend = pending_sources(state)
    pages = read_pages()
    by_type = {}
    for pg in pages.values():
        t = pg["fm"].get("type", "untyped")
        by_type[t] = by_type.get(t, 0) + 1
    return {
        "sources_total": len(all_src),
        "sources_ingested": len(all_src) - len(pend),
        "sources_pending": len(pend),
        "pages_total": len(pages),
        "pages_by_type": by_type,
        "last_lint": state.get("last_lint"),
        "last_run": state.get("last_run"),
        "initialized": SCHEMA_FILE.exists(),
    }


def cmd_status(args) -> int:
    c = _counts(load_state())
    if args.json:
        import json
        print(json.dumps(c, ensure_ascii=False))
        return 0
    if not c["initialized"]:
        print("wiki not initialized - run: wiki_build.py init")
    print(f"sources: {c['sources_ingested']}/{c['sources_total']} ingested, "
          f"{c['sources_pending']} pending")
    print(f"pages: {c['pages_total']}"
          + (f" ({', '.join(f'{t}:{n}' for t, n in sorted(c['pages_by_type'].items()))})"
             if c["pages_by_type"] else ""))
    print(f"last lint: {c['last_lint'] or 'never'} | last run: {c['last_run'] or 'never'}")
    return 0


def _plan_batch(state: dict, batch_size: int, path_prefix: str):
    pend = pending_sources(state, path_prefix)
    batch, total_bytes = [], 0
    for rel, mtime, size in pend:
        if batch and (len(batch) >= batch_size or total_bytes + size > BATCH_BYTES):
            break
        batch.append((rel, mtime, size))
        total_bytes += size
    return batch, len(pend), total_bytes


def cmd_plan(args) -> int:
    state = load_state()
    batch, n_pending, total_bytes = _plan_batch(state, args.batch_size, args.path_prefix)
    if args.json:
        import json
        print(json.dumps({"batch": [b[0] for b in batch], "pending_total": n_pending,
                          "batch_bytes": total_bytes}, ensure_ascii=False))
        return 0
    if not batch:
        print("no pending sources - wiki is up to date"
              + (f" for prefix '{args.path_prefix}'" if args.path_prefix else ""))
        return 0
    print(f"next batch: {len(batch)} of {n_pending} pending source(s), "
          f"{total_bytes / 1000:.0f} KB")
    for rel, _, size in batch:
        print(f"  {rel}  ({size / 1000:.0f} KB)")
    print("\nIngest these per WIKI.md, then record them with:")
    print("  python .claude/scripts/wiki_build.py mark-ingested --paths "
          + " ".join(b[0] for b in batch))
    return 0


def cmd_mark_ingested(args) -> int:
    known_now = {rel: (mtime, size) for rel, mtime, size in iter_source_files()}
    state = load_state()
    sources = state.setdefault("sources", {})
    ts = f"{now():%Y-%m-%d %H:%M}"
    marked, missing = 0, []
    for rel in args.paths:
        rel = rel.replace("\\", "/")
        if rel not in known_now:
            missing.append(rel)
            continue
        mtime, size = known_now[rel]
        sources[rel] = {"mtime": mtime, "size": size, "ingested_at": ts}
        marked += 1
    state["last_run"] = ts
    save_state(state)
    print(f"marked {marked} source(s) ingested")
    if missing:
        print(f"WARNING: {len(missing)} path(s) not found as valid sources: {missing}")
    log_line("wiki", f"mark-ingested: {marked} marked, {len(missing)} missing")
    return 0


def mark_source_ingested(rel: str) -> bool:
    """Record one source as ingested. Called by jobs/wiki_ingest.py's apply().

    Without this the loop never closes: apply() wrote the page but left the
    source `pending`, so the vault producer re-enqueued the same files every
    day forever. wiki-state.json is the single owner of "what has been
    ingested" - the producer must not keep a second copy.

    Read-modify-write inside ONE lock. apply_jobs.py applies a whole batch of
    approved jobs in a single run, and a lock covering only the write would let
    every mark but the last be lost.
    """
    rel = rel.replace("\\", "/")
    try:
        st = (VAULT / rel).stat()
    except OSError:
        return False
    ts = f"{now():%Y-%m-%d %H:%M}"
    with file_lock(STATE_FILE):
        state = read_json(STATE_FILE, {}) or {}
        state.setdefault("sources", {})[rel] = {
            "mtime": st.st_mtime, "size": st.st_size, "ingested_at": ts}
        state["last_run"] = ts
        atomic_write_json(STATE_FILE, state)
    return True


def run_lint() -> dict:
    """Deterministic health check. Returns a findings dict (no LLM)."""
    pages = read_pages()
    slugs = set(pages)
    findings = {"broken_links": [], "orphans": [], "catalog_missing": [],
                "catalog_stale": [], "bad_frontmatter": [], "vanished_sources": []}

    inbound = {s: 0 for s in slugs}
    for slug, pg in pages.items():
        fm = pg["fm"]
        # frontmatter checks
        problems = []
        if not fm.get("title"):
            problems.append("missing title")
        t = fm.get("type")
        if not t:
            problems.append("missing type")
        elif t not in PAGE_TYPES:
            problems.append(f"unknown type '{t}'")
        if problems:
            findings["bad_frontmatter"].append(f"{slug}: {'; '.join(problems)}")
        # links
        for target in outbound_links(pg["body"]):
            if target in RESERVED_SLUGS:
                continue
            if target in slugs:
                inbound[target] += 1
            else:
                findings["broken_links"].append(f"{slug} -> [[{target}]] (no such page)")
        # source existence
        for src in (fm.get("sources", "") or "").split(";"):
            src = src.strip()
            if src and not (VAULT / src).exists():
                findings["vanished_sources"].append(f"{slug}: {src}")

    for slug, n in inbound.items():
        if n == 0 and pages[slug]["fm"].get("type") != "overview":
            findings["orphans"].append(slug)

    # catalog drift
    catalog_slugs = set()
    if CATALOG_FILE.exists():
        ctext = CATALOG_FILE.read_text(encoding="utf-8", errors="replace")
        for m in WIKILINK_RE.finditer(ctext):
            catalog_slugs.add(slugify(m.group(1).split("|", 1)[0]))
    findings["catalog_missing"] = sorted(slugs - catalog_slugs)
    findings["catalog_stale"] = sorted(catalog_slugs - slugs - RESERVED_SLUGS)
    return findings


def _lint_summary(f: dict) -> str:
    return (f"{len(f['broken_links'])} broken link(s), {len(f['orphans'])} orphan(s), "
            f"{len(f['catalog_missing'])} uncataloged, {len(f['catalog_stale'])} stale "
            f"catalog entr(ies), {len(f['bad_frontmatter'])} frontmatter issue(s), "
            f"{len(f['vanished_sources'])} vanished source(s)")


def cmd_lint(args) -> int:
    findings = run_lint()
    if args.json:
        import json
        print(json.dumps(findings, ensure_ascii=False, indent=2))
    else:
        print("wiki lint:", _lint_summary(findings))
        for key, label in [("broken_links", "Broken links"), ("orphans", "Orphan pages"),
                           ("catalog_missing", "Pages missing from catalog"),
                           ("catalog_stale", "Catalog entries with no page"),
                           ("bad_frontmatter", "Frontmatter issues"),
                           ("vanished_sources", "Source paths that no longer exist")]:
            items = findings[key]
            if items:
                print(f"\n{label} ({len(items)}):")
                for it in items[:50]:
                    print(f"  - {it}")
                if len(items) > 50:
                    print(f"  ... and {len(items) - 50} more")
    state = load_state()
    state["last_lint"] = f"{now():%Y-%m-%d %H:%M}"
    save_state(state)
    total = sum(len(v) for v in findings.values())
    if total:
        append_to_daily_log("Wiki lint", _lint_summary(findings)
                            + "\n\nRun `/wiki` health mode to review. "
                            "Deletions are never automatic - flag only.")
    log_line("wiki", f"lint: {_lint_summary(findings)}")
    return 0


def cmd_daily(_args) -> int:
    """Nightly scheduled pass - pure Python, zero API tokens."""
    log_line("wiki", "daily run started")
    if not SCHEMA_FILE.exists():
        cmd_init(None)
    state = load_state()
    pend = pending_sources(state)
    findings = run_lint()
    state = load_state()  # cmd via run_lint didn't persist; reload then stamp
    state["last_lint"] = f"{now():%Y-%m-%d %H:%M}"
    state["last_run"] = f"{now():%Y-%m-%d %H:%M}"
    save_state(state)

    # Refresh the search index so any pages written today become searchable.
    reindex_note = ""
    try:
        r = subprocess.run([sys.executable, str(Path(__file__).with_name("memory_index.py"))],
                           cwd=str(Path(__file__).resolve().parents[2]),
                           capture_output=True, text=True, timeout=600)
        reindex_note = "reindex ok" if r.returncode == 0 else f"reindex rc={r.returncode}"
    except Exception as e:
        reindex_note = f"reindex failed: {e!r}"

    lint_total = sum(len(v) for v in findings.values())
    summary = (f"{len(pend)} source(s) pending ingest; lint: {_lint_summary(findings)}; "
               f"{reindex_note}")
    append_to_daily_log("Wiki daily", summary
                        + ("\n\nRun `/wiki` to ingest pending sources." if pend else ""))
    log_line("wiki", f"daily complete: {summary}")

    # Toast reminder (best-effort; interactive session may not be present).
    if pend or lint_total:
        try:
            import notify
            title = "Second Brain - Wiki"
            body = (f"{len(pend)} source(s) awaiting wiki ingest. Run /wiki."
                    if pend else f"Wiki lint: {lint_total} issue(s) to review.")
            notify.toast(title, body)
        except Exception as e:
            log_line("wiki", f"toast failed: {e!r}")
    print(summary)
    return 0


# ---------- embedded templates ----------

SCHEMA_TEMPLATE = """\
---
title: Wiki Schema and Maintainer Contract
type: meta
updated: 2026-07-07
---

# WIKI.md - Schema and Maintainer Contract

This document is the law for maintaining the LLM Wiki. Read it fully before any
ingest, query, or lint. It is loaded by the `wiki` skill.

## 1. Purpose and the three layers

The wiki is a compounding, cross-linked knowledge layer over the owner's vault
(Karpathy's llm-wiki pattern). Three layers:

1. **Raw sources** - the vault's own `.md`/`.txt` files. **IMMUTABLE.** Read, never edit.
2. **The wiki** - the pages under `pages/`, plus `catalog.md` and `log.md`. Agent-owned; keep consistent.
3. **This schema** (`WIKI.md`) - defines structure, naming, and workflows.

## 2. Page types

One idea per page. Prefer *updating* an existing page over creating a new one.

- `entity` - an organism, method, reagent, dataset, tool, place.
- `person` - a collaborator, PI, author.
- `project` - an active line of work (often mirrors a `Work/` or `projects/` folder).
- `concept` - a scientific idea, technique, or theme.
- `overview` - a hub page tying a cluster together (exempt from the orphan check).
- `summary` - a filed analysis produced by answering a query.
- `meta` - wiki-internal docs (this file). Not listed as knowledge.

## 3. Naming

- Filenames: `pages/<slug>.md`, slug is lowercase ASCII kebab-case
  (`^[a-z0-9][a-z0-9-]*$`), derived from the title. No dates in slugs.
- The human title lives in frontmatter, not the filename.
- Reserved slugs (do not use for pages): `wiki`, `catalog`, `log`, `index`.

## 4. Frontmatter (flat, single-line values only - the dashboard parser is flat)

```
---
title: Optical Pooled Screening
type: concept
sources: Work/03_IBS/ops/protocol.md; Work/06_Other/2026-03-notes.md
updated: 2026-07-07
---
```

- `sources`: `; `-separated vault-relative paths (forward slashes), the raw files this page draws from.
- `updated`: `YYYY-MM-DD`, set on every edit.
- No YAML lists or multi-line values (they will not parse in the web UI).

## 5. Linking

- Link with `[[slug]]` or `[[slug|display label]]`. Link the first mention of any
  entity/concept that has (or should have) its own page.
- Every page should have >= 2 outbound links.
- Never leave a dead link: either create a stub page for the target or drop the link.
- When you create or rename a page, add reciprocal links from related pages.

## 6. Catalog duties (`catalog.md`)

- Every page appears in `catalog.md` exactly once, grouped by type, as
  `- [[slug]] - one-line summary`.
- Update the catalog in the **same session** as any page create/rename.

## 7. Log duties (`log.md`)

- APPEND-ONLY. Never rewrite history.
- One entry per ingest/query/lint session:
  `## YYYY-MM-DD HH:MM - <op>` then the pages touched and a one-line why.

## 8. Ingest workflow

1. `python .claude/scripts/wiki_build.py plan` to get the next batch of source paths.
2. Read each source.
3. Find where it belongs: `python .claude/scripts/memory_search.py "<topic>" --path-prefix Memory/wiki --k 5`.
4. For each source, integrate into 3-8 pages (create or update). Cross-link both directions.
5. Update `catalog.md`; append one entry to `log.md`.
6. `python .claude/scripts/wiki_build.py mark-ingested --paths <the source paths>`.

## 9. Query workflow

- Answer from the wiki: search `--path-prefix Memory/wiki`, read the hit pages and
  their `[[links]]`, answer with page citations.
- If the synthesis is substantial and reusable, file it as a `type: summary` page,
  add it to the catalog, and log it.

## 10. Lint definitions (`wiki_build.py lint`)

- **broken link** - `[[slug]]` with no matching page.
- **orphan** - a page nothing links to (overviews exempt).
- **catalog drift** - a page missing from the catalog, or a catalog entry with no page.
- **bad frontmatter** - missing title/type or an unknown type.
- **vanished source** - a `sources:` path that no longer exists.

## 11. Hard rules

- **VAULT/Finance/**: NEVER read, index, link, or reference.
- Write **only** inside `VAULT/Memory/wiki/` (and the daily log). Never modify raw sources.
- **Never delete a page.** If a page should go, flag it in `log.md` for the owner's approval.
- UTF-8 markdown only. No binaries.
- Advisor mode: nothing external. This wiki never sends, posts, or publishes anything.
"""

CATALOG_TEMPLATE = """\
---
title: Wiki Catalog
type: meta
updated: 2026-07-07
---

# Catalog

Every wiki page, grouped by type, one line each. Maintained per `WIKI.md` §6.

## Overviews

## Concepts

## Projects

## Entities

## People

## Summaries
"""

LOG_TEMPLATE = """\
---
title: Wiki Maintenance Log
type: meta
updated: 2026-07-07
---

# Log

Append-only record of ingest / query / lint sessions (`WIKI.md` §7).

## {ts} - init

Wiki scaffolded (WIKI.md, catalog.md, log.md, pages/).
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="LLM Wiki toolkit (no LLM calls).")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="scaffold the wiki directory")

    p_status = sub.add_parser("status", help="ingested/pending counts + page stats")
    p_status.add_argument("--json", action="store_true")

    p_plan = sub.add_parser("plan", help="print the next batch of sources to ingest")
    p_plan.add_argument("--batch-size", type=int, default=BATCH_SOURCES)
    p_plan.add_argument("--path-prefix", default="")
    p_plan.add_argument("--json", action="store_true")

    p_mark = sub.add_parser("mark-ingested", help="record sources as ingested")
    p_mark.add_argument("--paths", nargs="+", required=True)

    p_lint = sub.add_parser("lint", help="deterministic health check")
    p_lint.add_argument("--json", action="store_true")

    sub.add_parser("daily", help="scheduled nightly pass (scan + lint + reindex + toast)")

    args = parser.parse_args()
    return {
        "init": cmd_init, "status": cmd_status, "plan": cmd_plan,
        "mark-ingested": cmd_mark_ingested, "lint": cmd_lint, "daily": cmd_daily,
    }[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
