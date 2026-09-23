# LLM Memory Integration

This repository uses separate files for separate kinds of memory:

- `CLAUDE.md` is the project operating manual: architecture, commands, boundaries,
  and implementation history.
- `AGENTS.md` points Codex and other agent runners to `CLAUDE.md`.
- `VAULT/Memory/USER.md` (with `SOUL.md` and `MEMORY.md`) is the portable
  personal context, injected into every session by the SessionStart hook.
- Dated notes under the active vault are the event log. They are not all loaded into
  every session.

This separation prevents a research biography from bloating the engineering manual
and prevents repository details from becoming part of the owner's identity everywhere.

## Claude Code in this repository

The SessionStart hook (`.claude/hooks/session-start-context.py`) injects
`SOUL.md`, `USER.md`, `MEMORY.md`, and the recent daily logs alongside the
project `CLAUDE.md`, so Claude Code loads both the project manual and the
owner's context automatically.

## Claude Code across all projects

For global personal context:

1. Export a condensed copy of `VAULT/Memory/USER.md` to a private location
   such as `~/.claude/OWNER_CONTEXT.md`.
2. Add this line to `~/.claude/CLAUDE.md`:

   ```text
   @~/.claude/OWNER_CONTEXT.md
   ```

3. Keep repository-specific commands in each repository's own `CLAUDE.md`.

Do not commit the global copy to a public repository.

## Claude.ai or another chat service

Upload the exported context file as project knowledge or attach it at the start of a
long-running research workspace. Use this bootstrap instruction:

> Read this context file as durable background about the owner. Current messages
> and primary sources override it. Preserve its identity correction, source hierarchy,
> uncertainty labels, scientific caveats, and privacy boundaries. Do not claim to
> remember conversations that are not represented in the file.

For a one-off task, attach only the relevant project note plus the exported
context file; do not upload the entire vault.

## Codex

`AGENTS.md` already routes Codex to the canonical project `CLAUDE.md`, and
the hooks inject the memory files for both runtimes. Keep the pointer chain rather than
maintaining a divergent Codex-only biography.

## Update workflow

Use a two-stage memory process:

1. Record a dated event in the daily note.
2. Promote it to `MEMORY.md` (or `USER.md` for identity facts) only if it should alter future behavior or
   understanding.

For important conversations, capture:

```markdown
## YYYY-MM-DD — Topic

- **Question:**
- **Decision:**
- **Reasoning:**
- **Remaining uncertainty:**
- **Next action:**
- **Source links:**
```

Good promotion candidates:

- A durable personal preference or explicit correction.
- A research milestone, changed manuscript status, or new appointment.
- A decision with reasoning that will matter later.
- A stable collaboration relationship or drafting preference.
- A hard safety or privacy boundary.

Do not promote:

- Raw transcripts.
- Temporary debugging detail.
- Unverified model inference.
- Credentials, secrets, tokens, or private keys.
- Sensitive records that are unnecessary for future assistance.

## Identity-contamination check

Before importing memory from another model or chat export:

1. Search for terms tied to the professions, credentials, and employers of the
   people close to you (a partner's or sibling's field, certifications, or
   company names) — the terms most likely to be mis-attributed to you.
2. Treat any match associating those terms with the owner as cross-user contamination.
3. Do not copy the claim into a new memory file.
4. If identity ownership is unclear, quarantine the excerpt and ask the owner.

Also check names, institutions, employment dates, and research topics against the
source hierarchy in `USER.md`.

## Quarterly audit

- Verify current role and career-search status.
- Verify publication and manuscript statuses against ORCID or the current CV.
- Confirm active versus paused research projects.
- Remove stale operational details from the portable context.
- Check that no secrets or unrelated identities entered the file.
- Review whether the context remains concise enough to load routinely.
