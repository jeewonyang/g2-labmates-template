# G2 - research dashboard (labmates template)

A personal research dashboard: a Next.js/Prisma PARA planner (Today, Planner,
Research desk with a lab notebook) plus an AI agent layer (Claude Code / Codex
CLI / local Ollama) that reviews papers, runs LabSerf analyses, files captures
into a knowledge vault, and drafts or proposes - never performs - outbound
actions. This file is the operating manual for agents working in this repo.

**This repository is a shared template.** It carries code and blank templates
only. The owner's data - `VAULT/`, `prisma/*.db`, `.env`, `.claude/data/`,
LabSerf results - is gitignored and must never be committed or pushed. If the
owner asks to version their vault, it goes in a separate private repository.

The setup walkthrough for humans is `SETUP_GUIDE.md`. Per-feature docs live in
`docs/`: `LAB_NOTEBOOK`, `COMMANDS`, `DEPLOYMENT`, `INTEGRATIONS_SETUP`,
`CAPTURE_API`, `QUICK_CAPTURE_MOBILE`, `LLM_MEMORY_INTEGRATION`. Read the
relevant doc before changing a subsystem. When you add a feature, put the
narrative in a doc and at most 2-3 lines here.

## Personal context

The owner's context lives in `VAULT/Memory/` and is injected by the
SessionStart hook: `SOUL.md` (who the agent is), `USER.md` (who the owner is,
their projects, people, paper watchlist, source folders), `MEMORY.md`
(decisions and lessons), and the last two daily logs. `PLAYBOOK.md`,
`AI_WORKFLOW.md`, `ACTIVE_PROJECTS.md`, `CAREER.md`, `COLLABORATORS.md`,
`LAB_PROTOCOLS.md` are read on demand.

**First run:** a fresh clone has no `VAULT/`. The hook then injects
`vault-template/Memory/BOOTSTRAP.md`; follow it (it starts with
`python .claude/scripts/init_vault.py`, which creates the vault and copies the
templates in without overwriting anything). Never write the owner's details
into `vault-template/` - those files are the blank starting point for everyone.

## The vault: split by sensitivity

| Path | Holds | Agent routing |
|---|---|---|
| `VAULT/G2OS-Staging/` | Published work, career, technical learning | cloud OK; indexed |
| `VAULT/Research-Private/` | Unpublished research, data, manuscripts, the lab notebook | source content local models only in bulk automation; indexed locally; never in the wiki |
| `VAULT/Confidential/` | Legal, housing, medical, other people's records (`40_People/<name>/`) | local only; never indexed |
| `VAULT/Finance/` | Tax and financial records | local only; never indexed |
| `VAULT/Memory/` | The agent's own state | internal |

Each tier uses `00_Inbox / 10_Projects / 20_Areas / 30_Resources / 90_Archive`
(`Confidential/` has `40_People` instead of `10_Projects`/`30_Resources`).
Files dropped into a tier's `00_Inbox/` are triaged by the vault team
(`triage.classify` on Ollama, then a sanitized audit); new project folders
always wait for approval on `/ops`.

- **Index/wiki exclusions exist in two copies that must move together:**
  `memory_index.py` (`EXCLUDED_TOP`, `EXCLUDED_SUBDIRS`) and `wiki_build.py`.
  `test_security.py::test_wiki_exclusions_match_index` asserts the wiki is never
  less restrictive. `block-secrets.py` also blocks `Confidential/` and
  `Finance/`.
- **Sensitivity is a property of content, not of the folder.** Audit before
  anything leaves the machine.
- `**/_private/` is gitignored everywhere.

## Hard rules (never relax these)

- **Advisor mode: draft, never send.** No code path may send email or post to
  any external platform. Exactly two outbound writes exist, each only after the
  owner approves that specific item: creating a Gmail **draft** from an
  approved vault draft (`gmail.compose`; never add `gmail.send`), and
  **inserting** a Google Calendar event from an approved
  `admin.schedule_proposal` (insert only - no update, move, or delete
  function). Adding a third requires the owner's decision in a live
  conversation.
- **Confidentiality routing is enforced, not advisory.** Source content from
  `VAULT/Confidential/` or `VAULT/Research-Private/` never goes to a cloud model
  in bulk automated processing (`derive_sensitivity()` + `guard()` in the
  dispatcher). Only sanitized decision metadata may be cloud-audited.
- **Identity boundary.** Records about other people (partners, family) are
  theirs, never the owner's, and never reach a CV, application, or biography.
  USER.md's "People who are NOT the owner" lists them; never infer a
  relationship from a name.
- **Never delete anything** without explicit permission in the current
  conversation. Every "delete" in the app is a soft archive.
- **No secrets in the vault.** Tokens live in `.claude/data/secrets/` or
  `.env`; the model never sees them - Python wrappers handle auth.
- **Lab data is read-only.** LabSerf runs write to `<run>/AI_analysis/`; never
  modify raw data.
- Never `git add VAULT`, `.env`, `prisma/*.db`, or `AppDev/`. Never push the
  owner's changes to the template's remote.

## Key paths

- `src/`, `prisma/` - the Next.js 15 dashboard.
- `.claude/scripts/` - Python agent scripts; `jobs/` one module per job kind;
  `producers/` one per team (deterministic, never call a model); `runtimes/`
  the `claude_rt` / `codex_rt` / `ollama` adapters, failover, model policy.
- `.claude/agents/teams/*.json` - team manifests (research, vault, security,
  admin). `python .claude/scripts/teams.py validate`.
- `.claude/agents/day-schedule.json` - the owner's day, written once. Read by
  `setup_scheduler.ps1`, `heartbeat.py` (active hours), and
  `src/lib/services/dayPlan.ts` (whose fallback mirrors the shipped file).
  None carries its own copy of an hour.
- `labserf/.claude/` - the LabSerf bench (agents: labserf, cloner, advisor,
  figure-designer; skills: flow-cytometry, ultrasound-analysis,
  molecular-cloning, scientific-advisor, figure-design). `LABSERF_ROOT`
  overrides the location; `LABSERF_PYTHON` the interpreter
  (`labserf/requirements.txt`). Resolved in two places asserted equal by
  `test_lab_notebook.py`: `lab_run.LABSERF` and `LABSERF_ROOT` in
  `labNotebook.ts`.
- `.claude/skills/` - lab-notebook, paper-digest, wiki, meeting-notes,
  vault-structure, draft-replies (`slack-catchup` is an alias). A skill and its
  scheduled job share one rules text: the `<!-- shared:NAME -->` block is
  spliced into the job prompt by `skill_rules.py`; edit rules only there.
- `vault-template/Memory/` - blank starter files copied by `init_vault.py`.

## Conventions

- Every Agent SDK / CLI entry point sets `CLAUDE_INVOKED_BY=<name>` (recursion
  prevention for SessionEnd/PreCompact hooks).
- **Two copies of one fact drift.** Prefer deriving over duplicating; where
  copies are unavoidable, change them together and keep the test that asserts
  it (exclusions, LabSerf root, notebook assay list, digest template).
- **Web app architecture (enforced):** business logic lives in framework-free
  services under `src/lib/services/`, never in components or route handlers.
  UI -> server action (`src/lib/actions.ts`) or API route -> service -> Prisma.
- **UI: one shared component per idea.** Reuse `SectionCard` /
  `CollapsibleSectionCard`, `EditTrigger`, `StateToggle`, `EmptyState`,
  `Dialog`, `Button`, `TaskEditDialog`, `TaskCreateDialog`,
  `TaskExtractDialog`, `ResearchTargetSelect`. The sidebar is a handful of
  "space" rows; new pages join a space's section nav (`PlannerNav`,
  `ResearchNav`, `AgentCenterNav`, `KnowledgeNav`), never a new sidebar row.
- Status/type/priority are plain strings validated by zod
  (`src/lib/validators.ts`, vocab in `src/lib/types.ts`) - no migration to add
  a type.
- Nothing becomes a task without a preview (`taskExtract.ts` + a dialog).
- Checkboxes `- [ ]` / `- [x]`; convert relative dates to absolute in memory
  files; drafts carry YAML frontmatter.
- Drafting tone comes from USER.md's Drafting Criteria: point in the first
  sentence, no stiff formulas, no emojis.

## Web dashboard

- **Spaces:** Now (Today; Planner -> `/inbox` with `PlannerNav`), Desks
  (Research -> `/research/feeds`, `/research`, `/research/digests`,
  `/research/notebook`; Agent Center -> `/teams`, `/ops`, `/drafts`), System
  (Knowledge = wiki + vault; Diagnostics `/settings` with the Setup checklist,
  `src/lib/services/setup.ts`).
- **`/today`:** brief, week strip, Plan & actual board (`dayPlan.ts`,
  `timeLog.ts`; the plan is rule-based, no model call), due & scheduled,
  messages & drafts, projects needing attention, daily note.
- **Lab notebook** (`docs/LAB_NOTEBOOK.md`): `lab_notebook.py` is the only
  writer of `Research-Private/10_Projects/<project>/04_Notebook/`; every entry
  records input and result data paths, written by code. LabSerf runs go through
  `lab_run.py` on the owner's Claude subscription as explicit launches; nothing
  scheduled calls the runner. A project's planner status alone decides whether
  its notebook is active or archived.
- **Research library:** paper reviews via `research.ts` -> `research_review.py`;
  the bibliography is append-only JSONL under `.claude/data/research/`.
- **`/ops`** is the approval queue. The run button spawns `dispatch.py` only and
  can never approve.

## Build commands

- `npm run dev` (binds 127.0.0.1) / `npm run build` / `npm run lint` /
  `npm run typecheck` / `npm test`.
- `npm run db:push` / `db:seed` / `db:reset`; `npx prisma studio`.
- `python .claude/scripts/init_vault.py` - create the vault (idempotent).
- `python .claude/scripts/agent_day.py [--team <id>] [--force] [--dry-run]` -
  run agent teams. Pause everything with `.claude/data/state/PAUSED`.
- `setup_scheduler.ps1` registers nothing without `-EnableDailyRun` (and
  friends); `-Status` / `-Remove`.
- `python .claude/scripts/memory_index.py [--rebuild]` (bge-m3 via Ollama);
  `memory_search.py "<query>"`; `wiki_build.py`.
- `python .claude/scripts/query.py status` - integrations.
- Tests: `.claude/scripts/tests/test_*.py` (run each directly); `npm test`.
  `test_g2_agent_run.py` needs at least one git commit in the checkout.
- Logs: `.claude/data/logs/`.

## Agent teams

A team is a set of job kinds, a producer, and a cadence; all work runs through
`dispatch.py` with an atomic claim, path-derived sensitivity guard, and a
`needs_review` approval gate. `apply()` is called only for approved jobs (by
`apply_jobs.py`), under `APPLY_LOCK`.

| Team | Kinds | Cadence (opt-in) |
|---|---|---|
| `research` (Rho + Argus, the LabSerf bench) | `research.lit_review`, `research.project_pulse` | daily 05:00 |
| `admin` (Ada) | `draft.reply`, `admin.extract_commitments`, `admin.schedule_proposal` | daily 05:00 + every 2h |
| `vault` (Vera) | `triage.classify`, `triage.review`, `memory.reflect`, `wiki.ingest`, `echo.check` | daily 21:30 |
| `security` (Sable) | `sec.*` - read-only codex reviews | weekly |

- **Failover:** inside Claude `fable -> opus -> sonnet`, and `claude <-> codex`;
  `ollama` never fails over to the cloud. Only capacity errors reroute. A spent
  window defers the job.
- **Background scripts run on the subscription CLI**, not API credit.
- **The security team never changes code**; every kind is review-gated.
