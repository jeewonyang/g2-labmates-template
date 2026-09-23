# Setup guide

Step-by-step instructions for building your own research dashboard from this
template. No coding experience needed. Steps 1-4 get the dashboard running
(about 20 minutes); everything after that is optional and can be done in any
order.

> **Your data stays yours.** Your vault (notes, memory, lab notebook), your
> database, and your LabSerf results are never committed to git. The only
> things in this repository are code and blank templates.

---

## 1. Install the prerequisites

| Tool | Why | Where |
|---|---|---|
| **Node.js** (LTS) | runs the dashboard | [nodejs.org](https://nodejs.org) - accept the defaults |
| **Git** | downloads the template and its updates | [git-scm.com](https://git-scm.com/downloads) - accept the defaults |
| **Python 3.11+** | agent scripts, lab notebook, LabSerf analyses | [python.org](https://www.python.org/downloads/) - on Windows tick **"Add python.exe to PATH"**. Miniconda also works. |

To open a terminal: **Windows** - press Start, type `powershell`, press Enter.
**Mac** - press Cmd-Space, type `terminal`, press Enter.

## 2. Get your own copy

**Recommended:** on the template's GitHub page, click **Use this template ->
Create a new repository**, make it **Private**, and clone *your* repository:

```bash
git clone https://github.com/<your-username>/<your-repo>.git G2
cd G2
```

(Or clone the template directly - `git clone https://github.com/jeewonyang/g2-labmates-template.git G2` -
if you only want to run it locally. Never push your changes back to the template.)

## 3. Install and start the dashboard

Paste each line and press Enter, letting each finish before the next
(`npm install` takes a few minutes the first time):

```bash
npm install
cp .env.example .env
npm run db:push
npm run db:seed
npm run dev
```

On Windows PowerShell, `cp` works; if it does not, use `copy .env.example .env`.

When it prints **Ready**, open <http://localhost:3000>. That is your dashboard,
running only on your machine. Next time, just run `npm run dev` in this folder
(or double-click `start-second-brain.bat` on Windows).

Open `.env` in any text editor and replace the two `generate-...-token` values
with any long random strings (private passwords for the dashboard's own APIs).

## 4. Learn the daily loop (no AI needed)

The dashboard opens with a project called **Set up my dashboard** - its tasks
are this guide, one step each.

- **Today** (left menu): your day. The week strip, the Plan & actual board (it
  plans tasks into the work blocks of your day), due tasks, and the **Daily
  note** on the right. Write your plan there as checkboxes under `@context`
  headings, then press **Pull into tasks** - you get a preview before anything
  is created.
- **Planner**: Inbox, Tasks, Projects, Areas & goals, Notes, Resources,
  Reviews, Archive. Press `c` anywhere to capture a thought into the Inbox,
  then triage it into a task, note, or resource with one click.
- **Research**: Newsletters (paper feeds), Library (reviewed papers), Digests,
  and the **Lab notebook** (step 7).
- **Diagnostics**: the **Setup checklist** shows what is set up on this
  machine and the exact command for anything missing.

**Make the day yours:** edit `.claude/agents/day-schedule.json` - wake time,
work blocks, meals, and reminders. The Today board reads it directly.

## 5. Turn on the AI agent (needs a Claude subscription)

1. Install **Claude Code**: [claude.com/claude-code](https://claude.com/claude-code)
   (a Claude Pro or Max plan; no API key needed).
2. In a terminal in this folder, type `claude`, press Enter, and follow the
   sign-in link.
3. Type: **`Run the onboarding in vault-template/Memory/BOOTSTRAP.md`**

The agent then interviews you (15-20 minutes) and:

- creates your vault (`python .claude/scripts/init_vault.py`) - the folder tree
  under `VAULT/` where your knowledge base lives, split by sensitivity;
- fills `VAULT/Memory/USER.md` with who you are, your projects, your
  collaborators, and your **paper watchlist** (the phrases the literature scan
  matches);
- walks you through step 6.

From then on, every `claude` session in this folder starts knowing who you are
and what you are working on. Ask it anything about the dashboard in plain
language.

## 6. Build your knowledge base from your own folders

Your knowledge base comes from **your** file tree - not a copy of anyone
else's. During onboarding (or any time later: *"Walk me through step 6 of
SETUP_GUIDE.md"*), the agent asks which folders hold your work and agrees with
you, folder by folder, where each belongs:

| Tier (under `VAULT/`) | Put here | Who can read it |
|---|---|---|
| `G2OS-Staging/` | published papers, talks, CV, courses, technical notes | cloud models OK |
| `Research-Private/` | unpublished data, drafts, manuscripts, **your lab notebook** | local models only in automation |
| `Confidential/` | legal, medical, housing, other people's records | never indexed, never sent to a cloud model |
| `Finance/` | tax and money records | never indexed |

Two ways to bring things in:

- **Copy documents into a tier's `00_Inbox/`.** The vault team sorts them into
  `10_Projects / 20_Areas / 30_Resources / 90_Archive` and asks for your
  approval (Agent Center -> Queue & review) before creating any new project
  folder. Sorting private material needs Ollama (step 8) so it never leaves
  your machine; without it, file by hand.
- **Leave raw data where it is.** Large datasets stay on your drive; the lab
  notebook records their paths, never copies them.

The agent only ever **copies**, never moves or deletes your originals. Start
with one folder so you see how filing works.

Search and the wiki are built from the vault:
`python .claude/scripts/memory_index.py --rebuild` (needs Ollama for the
multilingual embedding model), then ask the agent *"build the wiki"*.

## 7. Set up the lab notebook and the LabSerf bench

Research -> **Lab notebook** is where experiments are recorded and analyses
launched. Each **Active** project in the Planner gets its own notebook.

1. **Create a project:** Lab notebook -> New entry -> **+ New project…**. This
   makes an Active planner project and its notebook folder in one step.
2. **Log an experiment by hand:** New entry. Input and result data paths are
   required - they are how you find the data later.
3. **Run an analysis with LabSerf** (flow cytometry, ultrasound, primer
   design):
   ```bash
   pip install -r labserf/requirements.txt
   ```
   If you keep a separate conda environment for analysis, set `LABSERF_PYTHON`
   in `.env` to its `python.exe` (for example
   `C:\Users\<you>\miniconda3\envs\lab\python.exe`). Then Lab notebook ->
   **Launch an analysis**: pick the assay, paste the folder that holds the run,
   add instructions, and launch. Raw data is only read; results land in an
   `AI_analysis/` folder beside it, and a notebook entry is filed.
   "Pipeline only" runs the deterministic analysis without spending AI usage.
4. **Log computational work:** at the end of a Claude Code analysis session,
   say *"log this session"* - the `lab-notebook` skill files an entry with the
   pipeline diagram, inputs, outputs, and the git commit of the code.
5. **Optional:** `python .claude/scripts/notebook_session.py install` drafts an
   entry automatically whenever a Claude Code session that worked on an Active
   project ends.

More: [docs/LAB_NOTEBOOK.md](docs/LAB_NOTEBOOK.md).

## 8. Optional extras

- **Ollama** ([ollama.com](https://ollama.com), free): runs models on your own
  computer so private notes can be sorted and indexed without leaving it.
  After installing: `ollama pull bge-m3` and `ollama pull qwen3:8b`.
- **ChatGPT subscription**: install the Codex CLI and run `codex login` - a
  second runtime the security team uses and a fallback when Claude's usage
  window runs out.
- **Gmail / Calendar / Drive, Slack (read-only), GitHub**: ask the agent
  *"Walk me through connecting my Google account using
  docs/INTEGRATIONS_SETUP.md."* It drafts emails and proposes calendar events;
  only you send or approve anything.
- **Scheduled agents** (Windows): nothing runs on a schedule by default. To run
  the research team every morning and the vault team every evening:
  `powershell -ExecutionPolicy Bypass -File .claude\scripts\setup_scheduler.ps1 -EnableDailyRun`
  (`-Status` shows what is registered, `-Remove` turns it all off). Otherwise
  use the buttons on Agent Center.
- **Phone / tablet access**: [docs/QUICK_CAPTURE_MOBILE.md](docs/QUICK_CAPTURE_MOBILE.md)
  (Tailscale) and [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) (keep the dashboard
  running in the background).

## 9. Getting template updates

If you cloned the template directly: `git pull`. If you used **Use this
template**, add the template as a second remote once and merge from it:

```bash
git remote add template https://github.com/jeewonyang/g2-labmates-template.git
git pull template master
```

After an update: `npm install`, `npm run db:push`, then restart `npm run dev`.
Your vault and database are untouched by updates.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `node` / `npm` not found | Reopen the terminal after installing Node. |
| `python` opens the Microsoft Store | Install Python from python.org and tick "Add to PATH", or set `SECONDBRAIN_PYTHON` in `.env` to a real `python.exe`. |
| Lab notebook says the LabSerf Python is missing | `pip install -r labserf/requirements.txt`, or set `LABSERF_PYTHON` in `.env`. |
| Page buttons do nothing after an update | Stop `npm run dev` (Ctrl-C) and start it again. |
| `npm install` fails with EPERM on Windows | Stop the dev server first (the database engine file is locked while it runs). |
| Anything else | Open `claude` in this folder and describe what you see. |
