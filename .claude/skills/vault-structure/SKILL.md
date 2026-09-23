---
name: vault-structure
description: How the owner's vault and memory system are organized - where every kind of file lives, what's off-limits, and how to find things. Use when navigating the vault, deciding where to save a note, searching for past content, or unsure which folder something belongs in.
---

# Vault Structure

The owner's knowledge base lives in `VAULT/`. Use this map to find and file things.
The folder names below are the defaults shipped with the template - adjust them
to match the vault you actually have.

## Navigation

- **Browse** the tiers directly (`ls VAULT/<tier>/`); every tier uses the same
  `00_Inbox / 10_Projects / 20_Areas / 30_Resources / 90_Archive` buckets.
- **Search** (semantic + keyword) instead of guessing paths:
  `python .claude/scripts/memory_search.py "<query>"`. Add
  `--path-prefix Memory/drafts/sent` to scope. This is the right tool for
  "what did we decide about X" or "where are my notes on Y".

## Top-level folders

- `VAULT/Memory/` - the agent's own memory (see below)
- `VAULT/Work/` - work projects and research (the bulk of the knowledge base)
- `VAULT/Education/` - coursework and study notes
- `VAULT/Personal/` - personal documents
- `VAULT/Other Resources/` - miscellaneous references
- `VAULT/unsorted/` - not yet filed
- `VAULT/Finance/` - **OFF-LIMITS. Never read, list, index, or reference it.**

## Memory folders (`VAULT/Memory/`)

- `SOUL.md` - who the agent is (identity, Advisor-mode rules). Never edit
  without telling the owner first.
- `USER.md` - who the owner is (profile, accounts, paper watchlist, drafting
  criteria). Update when you learn a durable preference or fact.
- `MEMORY.md` - curated long-term memory. Keep concise; it loads every session.
- `HEARTBEAT.md` - proactive checklist.
- `daily/YYYY-MM-DD.md` - append-only daily log. Everything transient goes here
  first; the reflection promotes the important bits to MEMORY.md.
- `meetings/YYYY-MM-DD_<topic>.md` - structured meeting notes (see meeting-notes skill).
- `projects/<project>.md` - per-project status and progress.
- `research/` - paper digests and literature notes (see paper-digest skill).
- `drafts/{active,sent,expired}/` - reply drafts lifecycle (Phase 6).

## Conventions

- Dates absolute (`2026-07-06`), in the timezone set in CLAUDE.md.
- Checkboxes `- [ ]` / `- [x]`.
- Structured notes carry YAML frontmatter.
- No secrets in the vault - tokens live in `.claude/data/secrets/`.

## Advisor mode (hard rule)

Read, organize, draft, and suggest freely. Never send email/messages, never
post, never delete without explicit permission, never touch `Finance/`.
