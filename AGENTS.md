# Agent instructions

The canonical agent guide for this project is **[CLAUDE.md](CLAUDE.md)**. Codex and
Claude Code share it — read that file for project description, key paths, hard rules,
conventions, build commands, and completed-phase history.

Do not maintain a second copy of that content here. This pointer exists only so
Codex-based tools (which look for `AGENTS.md`) land on the same source of truth. If
you need Codex-specific hook wiring, see `.codex/hooks.json`, which references the
shared, tested hook scripts under `.claude/hooks/`.
