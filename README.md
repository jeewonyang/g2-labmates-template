# G2 - labmates template

A self-hosted research dashboard you run on your own computer: a daily
**Today** view and **Planner** (tasks, projects, notes, reviews), a
**Research desk** (paper feeds, a reviewed-paper library, and a **lab
notebook** that launches LabSerf analyses on your data), and an optional **AI
agent layer** that runs on your own Claude (and optionally ChatGPT)
subscription.

It ships **blank**. There is no one's data in it: you build the knowledge base
from your own folders, and everything personal stays on your machine.

**-> Start here: [SETUP_GUIDE.md](SETUP_GUIDE.md)** - step by step, no coding
experience needed.

## What you get

| Space | What it does |
|---|---|
| **Today** | Week strip with drag-to-reschedule, a Plan & actual board that fits tasks into the work blocks of your day, due and scheduled tasks, a daily note that turns checkbox lines into tasks (with a preview), and the brief from the research team. |
| **Planner** | PARA + GTD: Inbox (press `c` to capture anything), Tasks, Projects, Areas & goals, Notes, Resources, Reviews, Archive. |
| **Research** | Newsletters (arXiv / bioRxiv / PubMed feeds matched to your watchlist), a Library of AI-reviewed papers, Digests, and the **Lab notebook**. |
| **Lab notebook** | One notebook per Active project. Log experiments by hand, or launch **LabSerf** flow-cytometry, ultrasound, or primer-design analyses on a data folder; each run files an entry with its input and result paths. Computational sessions can be logged from Claude Code. |
| **Agent Center** | The agent teams, their models, and the approval queue. Agents draft and propose; you approve. |
| **Knowledge** | The wiki and memory vault the agents maintain from your files. |

### The agents (all optional)

| Team | Does | Runs on |
|---|---|---|
| **Research** - Rho | Reviews papers against your active projects; tracks project progress. | Claude |
| **Research** - Argus (LabSerf bench) | Flow/ultrasound analysis, primer and construct design, experiment critique, figure review - launched from the lab notebook. | Claude |
| **Housekeeping** - Vera | Files what you drop into a vault inbox, keeps the wiki and memory current. | Ollama (local) + Claude |
| **Housekeeping** - Sable | Weekly read-only audit of this repo (secrets, dependencies, stale docs). | Codex |
| **Admin** - Ada | Drafts email/Slack replies and proposes calendar events, if you connect those accounts. | Claude |

Nothing is scheduled until you opt in; every team also has a run button.

## Safety model

- **Drafts, never sends.** The agent never emails, posts, or messages anyone.
  The only writes that leave your machine are a Gmail *draft* and an inserted
  calendar event, each after you approve that specific item.
- **Private stays local.** Content in `VAULT/Research-Private/` and
  `VAULT/Confidential/` never goes to a cloud model in bulk automation; the
  dispatcher forces it onto a local model.
- **Nothing is deleted.** Every delete in the app is a soft archive.
- **Your vault is never committed.** `VAULT/`, the database, `.env`, and
  LabSerf results are gitignored. Keep your own copy of this repository
  private.

## Stack

Next.js 15 (App Router) + TypeScript + Tailwind v4, SQLite via Prisma, Python
agent scripts under `.claude/scripts/`, Claude Code / Codex CLI / Ollama as
runtimes. Business logic lives in framework-free services in
`src/lib/services/`. See [CLAUDE.md](CLAUDE.md) for the architecture and rules
the agents follow when they change code.

## Commands

| Command | Does |
|---|---|
| `npm run dev` | Start the dashboard at http://localhost:3000 |
| `npm run db:push` / `db:seed` / `db:reset` | Apply the schema / load the setup project / reset everything |
| `npm run typecheck` / `lint` / `test` / `build` | Checks |
| `python .claude/scripts/init_vault.py` | Create your vault (safe to re-run) |
| `python .claude/scripts/agent_day.py --team research --force` | Run the research team now |
| `python .claude/scripts/tests/test_<name>.py` | Python tests (run each file directly) |

More: [docs/COMMANDS.md](docs/COMMANDS.md).
