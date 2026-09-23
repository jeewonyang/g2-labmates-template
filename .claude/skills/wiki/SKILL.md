---
name: wiki
description: Maintain and query the LLM Wiki at VAULT/Memory/wiki/ - an agent-curated, cross-linked knowledge layer over the owner's vault (Karpathy's llm-wiki pattern). Use when they say "add this to the wiki", "ingest this", "build the wiki", "ask the wiki", "what does the wiki know about X", "wiki health", or "lint the wiki".
---

# Wiki

An agent-maintained wiki of markdown pages synthesized from the owner's vault:
raw sources stay immutable, the wiki is derived cross-linked views, and
`VAULT/Memory/wiki/WIKI.md` is the schema that governs how it's built. All
synthesis happens here in an interactive session (on their subscription) - the
`wiki_build.py` toolkit only does free bookkeeping and never calls an LLM.

**Before anything: read `VAULT/Memory/wiki/WIKI.md` in full.** It is the contract
(page types, slugs, frontmatter, linking, catalog/log duties, hard rules). If it
doesn't exist yet, run `python .claude/scripts/wiki_build.py init` first.

Pick the mode that matches the request.

## Mode A - Ingest (build/grow the wiki)

1. Get the next batch of source paths:
   `python .claude/scripts/wiki_build.py plan` (add `--path-prefix Memory/` or
   `--batch-size N` to scope). This prints the source paths and the exact
   `mark-ingested` command to run afterward.
   - To ingest a specific file instead: skip `plan` and use that path directly.
   - For content the owner pasted (not yet a file): save it to the right vault
     folder first (see the `vault-structure` skill), then ingest that file.
2. **Read each source.**
3. Find where it belongs in the existing wiki:
   `python .claude/scripts/memory_search.py "<topic>" --path-prefix Memory/wiki --k 5`
4. For each source, integrate into **3-8 pages** under `VAULT/Memory/wiki/pages/`
   (create or update, per WIKI.md). Cross-link with `[[slug]]` in both
   directions. Prefer updating an existing page over making a near-duplicate.
5. Update `VAULT/Memory/wiki/catalog.md` and append one entry to
   `VAULT/Memory/wiki/log.md` (same session as the page changes).
6. Record the batch as ingested:
   `python .claude/scripts/wiki_build.py mark-ingested --paths <the source paths>`
7. Tell the owner what you added/updated and how many sources remain
   (`wiki_build.py status`).

## Mode B - Query (ask the wiki)

1. `python .claude/scripts/memory_search.py "<question>" --path-prefix Memory/wiki --k 8`
2. Read the hit pages **and the pages they `[[link]]` to**.
3. Answer grounded in those pages, citing them by title/slug. If the wiki
   doesn't cover it, say so (and offer to ingest the relevant sources).
4. If the synthesis is substantial and reusable, file it as a `type: summary`
   page, add it to the catalog, and log it (WIKI.md §9).

## Mode C - Health (lint)

1. `python .claude/scripts/wiki_build.py lint` (add `--json` for the raw report).
2. Summarize: broken links, orphans, catalog drift, frontmatter issues, vanished
   sources. Fix cross-links and catalog entries directly when clear.
3. If a page looks like it should be removed or merged, **list it for the owner's
   approval and note it in `log.md` - never delete a page yourself.**

## Page content

**The rules between the `shared:page-content` markers are shared with the scheduled
`wiki.ingest` job** - `.claude/scripts/skill_rules.py` splices that block verbatim into
the job's prompt, so this skill and the job follow one text. Edit them only
there, and keep the block free of chat-only instructions (commands, tools).

<!-- shared:page-content -->
- Summaries are dense and factual. No hype, no filler.
- Preserve caveats: if the source says a result is preliminary or n=1, say so.
  Do not upgrade a hypothesis into a finding, or a manuscript in preparation
  into a publication.
- Link only to wiki pages that exist. Do not invent pages to link to.
- If a source does not contain enough substance for a page, say so honestly
  rather than padding it.
<!-- /shared:page-content -->

## Rules

- **Read WIKI.md and follow it.** It overrides anything ambiguous here.
- **VAULT/Finance/**: never read, index, link, or reference.
- Write **only** inside `VAULT/Memory/wiki/`. Raw sources are read-only.
- **Never delete a page** without the owner's explicit approval in the conversation.
- Advisor mode: the wiki never sends, posts, or publishes anything.
