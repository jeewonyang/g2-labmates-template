# VAULT/Memory - the agent's own state

This folder starts as a copy of `vault-template/Memory/` (made by
`python .claude/scripts/init_vault.py`). It is yours: nothing under `VAULT/` is
committed to the template repository.

Load tiers:

- **Every session (SessionStart hook):** BOOTSTRAP.md (until onboarding is
  done), SOUL.md, USER.md, MEMORY.md, the last two daily logs.
- **On demand (indexed, not injected):** PLAYBOOK.md, AI_WORKFLOW.md,
  ACTIVE_PROJECTS.md, CAREER.md, COLLABORATORS.md, LAB_PROTOCOLS.md.
- **Written by the system:** daily/ (append-only logs), drafts/ (reply drafts),
  meetings/, research/digests/ (paper reviews), projects/ (project pulses),
  wiki/ (the LLM wiki), security/, admin/, TRIAGE_TENDENCIES.md.

Maintenance rhythm: the daily reflection promotes yesterday's daily-log items
into MEMORY.md; keep MEMORY.md concise because it loads every session.
