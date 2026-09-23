# Lab notebook + the LabSerf bench

`/research/notebook` (Research -> **Lab notebook**) joins three things: launching
an analysis on your data, recording what the experiment found, and planning the
next cycle.

## What it does

1. **Launch** a flow-cytometry, ultrasound or primer-design job by giving a
   data folder (and, for primers, extra `.dna` maps) plus instructions.
2. **The runner** (`.claude/scripts/lab_run.py`, detached, one run at a time):
   - *Pipeline* (deterministic, no model): flow runs LabSerf's
     `analyze_flow.py`; ultrasound runs `identify_dataset.py --json`; primer
     design has no deterministic stage.
   - *Agent*: Claude on your subscription, working as LabSerf's `labserf` or
     `cloner` agent. It reads `labserf/.claude/agents/*.md` and the skills, finishes the
     pipeline, writes `RESULTS.md` / `NEXT_EXPERIMENTS.md` beside the data,
     records a null or failed result in the negative-result ledger
     (`labserf/LabMemory/`), and returns the notebook sections. "Pipeline only"
     skips this stage and spends nothing.
   - *Notebook*: `lab_notebook.py` files the entry.
3. **Read, edit, plan**: each entry has its own page; **Edit** rewrites it
   through the same writer; **Plan next cycle** turns its next steps into
   planner tasks under the matching project (with a preview first).
   **New entry** logs a bench experiment by hand in the same format.

Nothing scheduled calls the runner: every run is one you launch.

## Setting up the bench

The LabSerf agents and skills ship in this repo under `labserf/.claude/`. What
they need from you:

- **Python with the analysis packages**:
  `pip install -r labserf/requirements.txt`
  (numpy, scipy, matplotlib, pandas, h5py, openpyxl, python-docx, pypdf). If they live in
  a separate conda env, set `LABSERF_PYTHON` in `.env` to that env's
  interpreter path (e.g. `C:\Users\<you>\miniconda3\envs\lab\python.exe`).
  The notebook page tells you when the interpreter is missing.
- **Your own lab files, if you use them.** The cloning skill reads a
  `labserf/Sequences/` folder (SnapGene `.dna` maps; run
  `python labserf/.claude/skills/molecular-cloning/scripts/inventory.py` to
  build its parts inventory), and the scientific advisor indexes a
  `labserf/Protocols/` folder (`index_protocols.py`). Both are gitignored:
  copy in what you have, nothing is shared back.
- **Another LabSerf checkout?** Set `LABSERF_ROOT` to its folder; both the
  runner and the dashboard read it (`lab_run.LABSERF` and `LABSERF_ROOT` in
  `labNotebook.ts`, two copies asserted equal by `test_lab_notebook.py`).

Some skill references name files by the lab's conventions (e.g. a lab cloning
protocol spreadsheet or MATLAB processing scripts). They are documentation for
the agent; ask a labmate for the shared copies if you need them.

## The entry format (one writer: `lab_notebook.py`)

- Path: `VAULT/Research-Private/10_Projects/<project>/04_Notebook/<EXP-nnn>_<Project>_<YYYY-MM-DD>.md`.
  The project code is the folder name without its `NN_` prefix. `EXP-nnn` is
  the next free number in that project's notebook.
- Frontmatter: `type: lab-notebook`, title, ids, date, assay, outcome, status,
  **`input_path`, `result_path`**, and the run and negative-result ids.
- Body: `## Introduction`, `## Objective`, `## Materials & Methods`,
  `## Result`, `## Conclusion` (with `### Next steps` as `- [ ]` lines).
- **Every entry records its input and result data paths.** They are required
  by the writer, the form, and the schema; the writer puts them at the top of
  Materials & Methods itself.
- Rewriting copies the old version to `04_Notebook/.history/` first. Nothing
  is deleted. Each save also upserts a planner Note of type `experiment`.

## Routing and boundaries

- Runs you launch use Claude on your subscription, the same as running the
  LabSerf agents in a Claude Code session yourself.
- The agent runs with the repo as its working directory, so this repo's
  security hooks apply, and it gets access to the data folders only.
- **Raw data is read-only.** Outputs go to `<run>/AI_analysis/`; primer
  designs go to `labserf/Sequences/_designs/`.
- Entries are private: `VAULT/` is never committed and never enters the wiki.

## Active projects and the archive

A project's planner status alone decides where its notebook shows:
`/research/notebook` lists every entry of every **Active** project;
`/research/notebook/archive` lists the notebooks of projects that are Done.
Setting a project back to Active brings its notebook back. Launching and new
entries require an Active project; "+ New project…" in the forms creates the
notebook folder and an Active planner project with the same name.

## Computational entries

For analysis, modeling or pipeline sessions, the `lab-notebook` skill (say
"log this session" in Claude Code) files the same entry with assay
`computational`: a Mermaid pipeline diagram under Materials & Methods,
`### Inputs` / `### Outputs` / `### Code & environment`, and a Conclusion with
`### Discussion`, `### Takeaway`, and `### Next steps`.
Code provenance is frontmatter filled by code, never typed by a model:
`lab_notebook.py provenance --repo <dir> --input .. --result ..` records the
git repo, branch, commit and uncommitted-change count, and warns about missing
or temporary data paths. Every AI-made entry also records `ai_model` and
`prompt_summary`.

## Automatic draft when a project session ends (optional)

`python .claude/scripts/notebook_session.py install` adds a user-level
SessionEnd hook: when a Claude Code session that worked on an Active project
ends (a path segment equals a project folder name), it files a **draft** entry
from that session's own conversation text, with every tool denied. Turn it off
by creating `.claude/data/state/PAUSED` or removing the SessionEnd entry from
`~/.claude/settings.json`. `notebook_session.py check --transcript <file>`
shows the decision without calling a model.

## Past notebooks: OneNote import (Windows)

`python .claude/scripts/onenote_import.py --source "<notebook folder>" [--dry-run]`
reads a OneNote notebook through OneNote desktop and files its experiment pages
as `ON-nnn_<Project>_<date>` entries, verbatim (no model reads a page).

## Tests

`python .claude/scripts/tests/test_lab_notebook.py` (format contract, path
requirement, history on rewrite, the TS/Python copies, the runner's
boundaries), `test_notebook_session.py`, `test_onenote_import.py`.
