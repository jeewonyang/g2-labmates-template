# USER.md - Who the Owner Is

_Filled in during onboarding (see BOOTSTRAP.md). Every `(TBD)` is a question to
ask. Keep this file current - it loads into every session._

## Identity

- **Name:** (TBD)
- **Role:** (TBD - e.g. graduate student / postdoc, lab, institution)
- **Research field and methods:** (TBD - a few lines; the paper reviewer and
  the filer judge relevance against this)
- **Timezone:** (TBD - also set `timezone` in `.claude/agents/day-schedule.json`)
- **Email accounts:** (TBD - only if they connect Gmail)

## Active Work

- (TBD - the 2-5 projects that matter right now; deeper detail goes in
  ACTIVE_PROJECTS.md. Each should also be a planner project and have a folder
  under VAULT/Research-Private/10_Projects/.)

## Key People

_The drafting jobs read this table to pick a tone. Replace the examples with
real people during onboarding._

| Person | Relationship | Tone |
|---|---|---|
| Dr. Ada Advisor | Mentor/PI | Polite and appreciative |
| Sam Student | Mentee | Casual and warm |

New people are classified from verified context, with Collaborator as the
respectful provisional default.

## People who are NOT the owner

_Family members or partners whose records might land in the vault. Their
professions and documents are theirs - never the owner's, never in a CV or
career path. Filed under `VAULT/Confidential/40_People/<name>/`._

- (none recorded)

## Drafting Criteria (canonical tone spec)

- Mentor/PI: polite and appreciative.
- Mentee: casual and warm.
- Collaborator: formal and warm.
- Colleague: casual and fun.
- Across all groups: get to the point in the first sentence; no stiff formulas
  ("I hope this email finds you well", "Kind regards"); courtesy still counts;
  **no emojis**. Slack is shorter than email.

## Vault Map

| Path | Holds | Sensitivity |
|---|---|---|
| `VAULT/G2OS-Staging/` | Career, applications, published work, technical learning | internal - cloud OK |
| `VAULT/Research-Private/` | Unpublished work, data, manuscripts in prep, the lab notebook | private - local models only in bulk automation |
| `VAULT/Confidential/` | Legal, housing, medical, other people's records | private - never indexed |
| `VAULT/Finance/` | Tax and financial records | private - never indexed |
| `VAULT/Memory/` | The agent's own state (this folder) | internal |

Nothing under `VAULT/` is ever committed to the template repository.

## Source folders

_Where the owner's knowledge lives on disk, mapped during onboarding (step 4
of BOOTSTRAP.md). Copies go into a tier's `00_Inbox/`; raw data stays in place._

| Folder on disk | What it holds | Tier | How it comes in |
|---|---|---|---|
| (TBD) | | | copy to inbox / reference in place |

## Integrations

- (TBD - which of Gmail / Calendar / Drive / Slack / GitHub / Ollama are
  connected; see docs/INTEGRATIONS_SETUP.md)

## Paper Watchlist

_The daily papers check (arXiv, bioRxiv, PubMed) matches new papers against
these phrases. One bullet each; `label: term1, term2` also works._

- (TBD - e.g. "light-sheet microscopy", "protein design: binder, de novo")

## On-demand context files

Not auto-loaded; Read them when the task needs them:

- `PLAYBOOK.md` - taste, brainstorming, design and publication strategy
- `AI_WORKFLOW.md` - how to operate as a collaborator; coding preferences
- `ACTIVE_PROJECTS.md` - live project state, bottlenecks, next decisions
- `CAREER.md` - career direction and decision criteria
- `COLLABORATORS.md` - verified people, roles, and working context
- `LAB_PROTOCOLS.md` - protocol index and capture template
