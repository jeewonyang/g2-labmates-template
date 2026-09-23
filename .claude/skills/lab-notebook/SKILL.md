---
name: lab-notebook
description: File a computational lab-notebook entry at the end of a coding, analysis, modeling, or pipeline session - the pipeline as a diagram, inputs and outputs, results, discussion, conclusion and next steps - under the matching project in the owner's lab notebook (/research/notebook). Use when they say "log this session", "notebook entry", "write this up in the lab notebook", "add this to my notebook", "/lab-notebook", or wraps up a computational session and asks to record it. Also updates an entry from an earlier session.
---

# Lab notebook: computational entry

A computational session gets the same notebook entry as a bench experiment:
the five sections every entry has (Introduction, Objective, Materials &
Methods, Result, Conclusion), filed under its project in
`VAULT/Research-Private/10_Projects/<project>/04_Notebook/`. The narrative is
in `docs/LAB_NOTEBOOK.md` ("Computational entries").

**One writer.** Every entry goes through `lab_notebook.py write`. Never write
or edit the markdown file yourself; the writer owns the title, the section
headings, the data-path lines, next-step checkboxes and `.history/`.

**Code, not you, states the facts.** The git commit, clean or dirty state, and
whether each data path exists come from `lab_notebook.py provenance`. Copy
its `frontmatter` object into the entry exactly as it comes back. Every path in
the entry is one this session actually read or wrote. If you do not know
something, say it is not recorded. Never guess it.

## 0. Find G2

The CLI lives in the G2 repo. From inside G2, `G2=.`; from any other repo,
`G2=~/Documents/G2` (the same place on the desktop and the Mac). Run it with
`python "$G2/.claude/scripts/lab_notebook.py" ...`. Use Git Bash on Windows:
PowerShell 5.1 re-encodes piped text.

## 1. Collect what happened, from this session only

Go back over this conversation's tool calls and list:

- **Inputs**: files and folders read as data (not code you edited).
- **Outputs**: files written as results, such as tables, figures, fitted
  models and logs.
- **Code**: the repo(s), the scripts or notebooks run, key parameters, and the
  exact commands, including the interpreter/env (for example
  `conda run -n lab python fit.py --k 5`).
- **Numbers**: each finding with its n and the output file it came from, plus
  anything that failed, errored or came out null. A negative result is a
  result.

If the session spanned several repos, the **code repo** is the one whose code
produced the results.

**The AI model and session id come from the transcript**, not from memory:

```bash
python "$G2/.claude/scripts/lab_notebook.py" session --cwd "<this session's cwd>"
```

It reads the newest transcript for that folder. Another session in the same
folder may be newer, so check that `prompts[0]` is this session's first
request. If it is not, find this session's file under
`~/.claude/projects/<cwd with every non-alphanumeric as ->/` and pass it with
`--transcript <file>`. Use its `ai_model` and `session_id` as they come back.
If no transcript can be found, give the exact model id from your own system
prompt and leave `session_id` empty.

## 2. Pick the project

`python "$G2/.claude/scripts/lab_notebook.py" projects` lists the project codes.
Infer the code from the paths (`.../10_Projects/<NN_Code>/...`), the repo, or
the conversation, and **confirm it with them** in the preview. The notebook
page lists only projects that are Active in the planner; the entry for any
other project is still filed, but shows under Archive. If the work fits no
existing project, ask before `create-project --code <Code>`.

## 3. Make the outputs durable, then record provenance right away

Git describes the working tree **now**, not when the analysis ran, so run this
step before anything else changes the tree:

```bash
python "$G2/.claude/scripts/lab_notebook.py" provenance --repo <code repo> \
  --input <primary input> [--input <more>] \
  --result <primary result dir or file> [--result <more>] \
  [--path <script or figure>]...
```

Read its `warnings` and act on each one:

- **Output in a scratch, temp or worktree folder** (it may be deleted with the
  job or worktree): propose copying it to a durable place, such as the run's
  own results folder or the project's `01_Data/` or `02_Figures/`, and wait
  for their yes before copying. Copy; never move or delete. Then re-run
  `provenance` with the new paths.
- **Does not exist / relative path**: fix the path from what the session
  actually wrote. If the file is gone, say so in the entry; never point at a
  path that is not there.
- **Uncommitted changes**: committing in their repo is their call. Ask: commit
  first, or keep the diff next to the results by re-running with
  `--save-diff <result dir>/code-uncommitted-<YYYY-MM-DD>.patch`, which never
  overwrites. Do not commit or push on your own. The patch is the diff
  verbatim, so before filing, check it for a tracked `.env`, config or key
  file. If one is there, tell them, and commit or stash the code another way
  instead of keeping a secret in the notebook folder.
- **Not a git repository / no remote**: file anyway, and say in *Code &
  environment* how the code can be found again.

`environment` records the env of the shell running the CLI. If the analysis ran
in another interpreter, replace it with what the session used: the env name
and the version that interpreter printed (`<python> --version`).

## 4. Fill the template

`python "$G2/.claude/scripts/lab_notebook.py" template --assay computational`
prints the JSON the writer takes, with guidance text in each field. Replace
every guidance string. The sub-headings are `###` because the five `##`
sections are fixed.

- `name`: a short human title. `summary`: one sentence stating the finding.
- `outcome`: `positive | negative | mixed | inconclusive | technical-failure |
  pending`. `status`: `draft` unless they say it is final.
- `input_path` / `result_path`: the **primary** input and result, as absolute
  paths. The writer prints them first in Materials & Methods, so do not repeat
  them in the prose.
- The code keys (`code_repo`, `code_commit`, ...) come verbatim from
  `provenance.frontmatter`. Leave out any it did not return.
- `ai_model` and `session_id`: from `session` (step 1). `logged_by`: `skill`.
- `prompt_summary`: what they asked for this session, in one to three plain
  sentences, written from their own prompts (`session` lists them). Summarize;
  do not paste them.
- **Introduction**: why this analysis, and what it builds on (earlier entries
  by title, papers, a conversation).
- **Objective**: the question, in one or two sentences.
- **Materials & Methods**:
  - `### Pipeline`: a Mermaid flowchart. Obsidian and the dashboard both draw
    it, and a diagram that does not parse shows as its source.
    - Use `flowchart LR` for a linear pipeline and `flowchart TD` when it
      branches.
    - Draw data as `[(cylinder)]` nodes and steps as `[box]` nodes, and put the
      script or tool on the edge: `raw[(FCS files)] -->|analyze_flow.py| gated[gated events]`.
    - Put a label in quotes if it has `()`, `:` or `/`.
    - Keep it to 15 nodes or fewer, with basic syntax only: no click handlers,
      styles or HTML.
    - If the session was a single step, write that plainly instead of drawing
      one box.
  - `### Inputs` and `### Outputs`: tables of what, where (absolute path) and
    notes (format, size, n). Every row is a path from step 1.
  - `### Code & environment`: the scripts with their paths, the parameters
    that matter, and a command to rerun. Point to the frontmatter for the
    commit rather than retyping it, and mention the saved diff if there is one.
- **Result**: the findings with numbers, n, and the output file each came from.
  Give figures as paths. Include failures and nulls.
- **Conclusion**: `### Discussion` (interpretation, caveats, alternatives, what
  would change the conclusion), then `### Takeaway` (what was learned, in two or three sentences).
  Never write `### Next steps` yourself.
- `next_steps`: a list of concrete, checkable steps, one per item, with no
  `- [ ]` prefix. They become planner tasks through "Plan next cycle".

Keep raw data out of the entry: no pasted tables beyond a summary, and no
credentials, tokens or `.env` values. The identity boundary holds here too:
nothing about their family's careers belongs in their notebook.

## 5. Preview, then write

Get the title first: `lab_notebook.py next-id --project <Code>` gives
`EXP-nnn`, and the title is `EXP-nnn_<Code>_<YYYY-MM-DD>` (today, Pacific).
Show them:

- the title, project, outcome, and the two data paths;
- the code line (repo, commit, clean or dirty, env) and every unresolved
  `provenance` warning;
- the AI model and the summarized prompt;
- the pipeline diagram source, and the Result and Next steps in full.

Write only after they say yes. Save the JSON as UTF-8 to a scratch file and run:

```bash
python "$G2/.claude/scripts/lab_notebook.py" write --file <entry.json>
```

The reply names the vault path. Run `lab_notebook.py check <that path>` and
report the result, together with the dashboard location:
`/research/notebook/<Code>/<title>`.

**Continuing an earlier entry**: pass that entry's `experiment_id` and `date`
with the full new content. The writer copies the old version to `.history/`
first, and nothing is lost. To add to it rather than replace it, read the old
file first and merge.

## Boundaries

- This is their own interactive session, like running a LabSerf agent themselves.
- **The automatic fallback.** When a session ends without this skill having
  run, a user-level SessionEnd hook (`notebook_session.py`) may file a
  **draft** entry marked `logged_by: auto`. That happens only if the session
  worked on an Active project. A session that ran this skill's `write` is never
  auto-logged, so there are no duplicates. Using the skill still gives the
  better entry: you have the whole session, while the hook sees only its text.
  If an auto draft for this session already exists (same `session_id`), pass
  its `experiment_id` and `date` so this entry replaces it.
- Research-Private stays private: gitignored, indexed locally only, and never
  in the wiki. Do not copy the entry anywhere else.
- Nothing is deleted. A rewrite keeps history, and copying outputs to a durable
  place leaves the originals where they are.
