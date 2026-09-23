"""The lab notebook: one markdown entry per experiment, filed under its project.

This module is the notebook's only writer. The dashboard (`labNotebook.ts`)
reads the files and spawns this CLI for every write; the lab runner
(`lab_run.py`) imports `write_entry` directly. One writer means one definition
of the format, which is the lesson of the lit-review digests: a heading renamed
in one copy empties a page silently.

Where entries live (the owner, 2026-09-21): unpublished results, so
`VAULT/Research-Private/10_Projects/<project folder>/04_Notebook/`. That tree is
gitignored by the allowlist, indexed only locally, and excluded from the wiki.
`04_` continues the folders every project already carries (00_Literature,
01_Data, 02_Figures, 03_Paper).

The contract, asserted by tests/test_lab_notebook.py:

- Title and filename are `<ExperimentID>_<ProjectID>_<YYYY-MM-DD>`.
- The body has exactly five `##` sections, in this order: Introduction,
  Objective, Materials & Methods, Result, Conclusion.
- **Every entry records its input data path and its result data path**
  (the owner, 2026-09-21), in frontmatter *and* as the first two lines of
  Materials & Methods. The writer puts them there itself rather than trusting
  a model to, and refuses an entry missing either one.
- Next steps are `- [ ]` lines under `### Next steps` in the Conclusion, so the
  shared task extractor turns them into planner tasks with a preview.
- Rewriting an entry copies the previous version to `04_Notebook/.history/`
  first. Nothing is deleted.

CLI (JSON in on stdin where noted, JSON out on stdout):
    lab_notebook.py projects
    lab_notebook.py next-id --project Alpha
    lab_notebook.py write            < entry.json   (or --file entry.json)
    lab_notebook.py check <file.md>
    lab_notebook.py create-project --code NewProject
    lab_notebook.py archive --project Alpha --title EXP-001_Alpha_2026-09-21
    lab_notebook.py restore --project Alpha --title EXP-001_Alpha_2026-09-21
    lab_notebook.py template --assay computational
    lab_notebook.py session [--transcript <file.jsonl> | --cwd <dir>]
    lab_notebook.py provenance --repo <dir> --input <path> --result <path> [--path <p> ...]
                               [--save-diff <file.patch>]

Computational entries (the owner, 2026-09-22) keep the same five sections. The
`lab-notebook` skill files them at the end of a coding/analysis session; the
sub-headings it fills come from `template`, and the code's git state and the
existence of every data path come from `provenance` - code, not the model.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from shared import REPO_ROOT, VAULT, atomic_write_text, log_line  # noqa: E402

PACIFIC = ZoneInfo("America/Los_Angeles")
PROJECTS_ROOT = VAULT / "Research-Private" / "10_Projects"
NOTEBOOK_DIR = "04_Notebook"
HISTORY_DIR = ".history"
DB = REPO_ROOT / "prisma" / "dev.db"

SECTIONS = ("Introduction", "Objective", "Materials & Methods", "Result",
            "Conclusion")
ASSAYS = ("flow", "ultrasound", "primer-design", "bench", "computational",
          "other")
OUTCOMES = ("positive", "negative", "mixed", "inconclusive",
            "technical-failure", "pending")
STATUSES = ("draft", "final")

EXPERIMENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,23}$")
AUTO_ID = re.compile(r"^EXP-(\d{3,})$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TITLE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9-]{0,23})_([A-Za-z0-9]+)_(\d{4}-\d{2}-\d{2})$")
# Folders that hold a project. `_other` is a catch-all, not a project.
PROJECT_FOLDER = re.compile(r"^(?:\d{2}_)?([A-Za-z][A-Za-z0-9]*)$")
NOTE_TYPE = "experiment"
# Provenance an importer may add to frontmatter (OneNote, 2026-09-21). A fixed
# list so a caller cannot write arbitrary keys into their notebook files.
SOURCE_KEYS = ("source", "source_path", "source_page", "source_parent",
               "source_created", "source_modified", "also_in")
# Code provenance of a computational entry (2026-09-22), structured so it is
# searchable and shown on the entry page. Filled from `provenance`, which reads
# git - a commit hash is never typed by a model. `code_captured` says when: git
# describes the tree at that moment, not necessarily when the analysis ran.
CODE_KEYS = ("code_repo", "code_remote", "code_branch", "code_commit",
             "code_dirty", "code_diff", "code_captured", "environment")
# Which AI did the work and what they asked it (the owner, 2026-09-22: "a
# summarized prompt and the AI model used, for future logging"). `ai_model` is
# read by code wherever it can be (the transcript, the runner's result);
# `prompt_summary` is their request in two or three sentences - verbatim for a
# LabSerf run, whose instructions are already short. `logged_by` says which
# path filed the entry: skill | auto | lab-run.
SESSION_KEYS = ("ai_model", "prompt_summary", "session_id", "logged_by")
# What a rewrite from the edit dialog keeps from the file it replaces when the
# caller does not resend it (`keep_provenance`). Before this, an edit dropped
# an imported entry's source_* keys.
KEPT_ON_REWRITE = ("run_id", "negative_result_id") + SOURCE_KEYS + CODE_KEYS + SESSION_KEYS

# The sub-headings a computational entry fills inside the five sections. `##`
# stays the contract; `###` is free, so these cost the parser nothing. Discussion
# precedes Next steps because everything after `### Next steps` is task lines.
COMPUTATIONAL_TEMPLATE = {
    "introduction": "Why this analysis, and what it builds on (earlier entries by title).",
    "objective": "The question the session set out to answer, in one or two sentences.",
    "materials_methods": (
        "### Pipeline\n\n```mermaid\nflowchart LR\n  A[input] --> B[step] --> C[output]\n```\n\n"
        "### Inputs\n\n| Data | Path | Notes |\n|---|---|---|\n\n"
        "### Outputs\n\n| Output | Path | Notes |\n|---|---|---|\n\n"
        "### Code & environment\n\nScripts run, parameters, and the command to rerun."),
    "result": "Findings with numbers and n; figures as paths. Failed or null results too.",
    "conclusion": "### Discussion\n\nInterpretation, caveats, alternatives.\n\n"
                  "### Takeaway\n\nWhat was learned, in two or three sentences.",
    "next_steps": ["One concrete step per line"],
}
# Archived entries live apart from their project (the owner, 2026-09-21: "a
# separate place to store and view all archived notebook entries"): the
# research vault's own 90_Archive, one folder per project code. Archiving is a
# move, never a delete, and restore moves it back.
ARCHIVE_ROOT = VAULT / "Research-Private" / "90_Archive" / "Lab Notebook"


class NotebookError(ValueError):
    """An entry that would break the contract. Reported, never half-written."""


# ------------------------------------------------------------------ projects

def list_projects() -> list[dict]:
    """Every project folder, with its code: `00_Alpha` -> `Alpha`."""
    if not PROJECTS_ROOT.is_dir():
        return []
    projects = []
    for folder in sorted(PROJECTS_ROOT.iterdir()):
        if not folder.is_dir():
            continue
        match = PROJECT_FOLDER.match(folder.name)
        if not match:
            continue
        notebook = folder / NOTEBOOK_DIR
        entries = sorted(p.name for p in notebook.glob("*.md")) if notebook.is_dir() else []
        projects.append({
            "code": match.group(1),
            "folder": folder.name,
            "entryCount": len(entries),
        })
    return projects


PROJECT_CODE = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,39}$")


def create_project(code: str) -> dict:
    """Make a new project's folder with its notebook (the owner, 2026-09-21:
    "create a new Project along with a new notebook entry or analysis").

    The folder is named with the code itself - the same string the planner
    project is titled with, so the two stay matched. An existing project of
    that code (any case) is returned, never shadowed by a second folder.
    """
    code = str(code or "").strip()
    if not PROJECT_CODE.match(code):
        raise NotebookError(
            "a project name is letters and digits only, starting with a letter "
            f"(it becomes the ProjectID in every entry title): {code!r}")
    for project in list_projects():
        if project["code"].lower() == code.lower():
            return {**project, "created": False}
    folder = PROJECTS_ROOT / code
    (folder / NOTEBOOK_DIR).mkdir(parents=True, exist_ok=True)
    log_line("lab_notebook", f"created project folder {_rel(folder)}")
    return {"code": code, "folder": code, "entryCount": 0, "created": True}


def project_folder(code: str) -> Path:
    for project in list_projects():
        if project["code"].lower() == str(code or "").strip().lower():
            return PROJECTS_ROOT / project["folder"]
    raise NotebookError(f"no project folder for code {code!r} under "
                        f"VAULT/Research-Private/10_Projects/")


def _canonical_code(code: str) -> str:
    """The code as the folder spells it, whatever case they typed."""
    return PROJECT_FOLDER.match(project_folder(code).name).group(1)


def next_experiment_id(code: str) -> str:
    """Next free `EXP-nnn` for a project, read off the filenames on disk.

    The files are the counter. A second store would drift the first time they
    rename or adds an entry in Obsidian.
    """
    highest = 0
    for notebook in (project_folder(code) / NOTEBOOK_DIR,
                     archive_dir(_canonical_code(code))):
        if not notebook.is_dir():
            continue
        # Archived entries count too: an id is never reused once filed.
        for path in notebook.glob("*.md"):
            match = TITLE.match(path.stem)
            if match:
                auto = AUTO_ID.match(match.group(1))
                if auto:
                    highest = max(highest, int(auto.group(1)))
    return f"EXP-{highest + 1:03d}"


# ------------------------------------------------------------------ writing

def _text(value, limit: int = 20_000) -> str:
    return str(value or "").replace("\r\n", "\n").strip()[:limit]


def _yaml(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _normalize(entry: dict) -> dict:
    code = _canonical_code(entry.get("project_code") or entry.get("project"))
    date = _text(entry.get("date"), 10) or datetime.now(PACIFIC).strftime("%Y-%m-%d")
    if not DATE.match(date):
        raise NotebookError(f"date must be YYYY-MM-DD, got {date!r}")
    experiment_id = _text(entry.get("experiment_id"), 24) or next_experiment_id(code)
    if not EXPERIMENT_ID.match(experiment_id):
        raise NotebookError(
            "experiment id may use letters, digits and '-' only (no '_', "
            f"which separates the title parts): {experiment_id!r}")
    assay = _text(entry.get("assay"), 32) or "other"
    if assay not in ASSAYS:
        raise NotebookError(f"assay must be one of {ASSAYS}, got {assay!r}")
    outcome = _text(entry.get("outcome"), 32) or "pending"
    if outcome not in OUTCOMES:
        raise NotebookError(f"outcome must be one of {OUTCOMES}, got {outcome!r}")
    status = _text(entry.get("status"), 16) or "draft"
    if status not in STATUSES:
        raise NotebookError(f"status must be one of {STATUSES}, got {status!r}")
    input_path = _text(entry.get("input_path"), 1_000)
    result_path = _text(entry.get("result_path"), 1_000)
    if not input_path or not result_path:
        raise NotebookError(
            "every notebook entry records both the input data path and the "
            "result data path")
    sections = {
        "Introduction": _text(entry.get("introduction")),
        "Objective": _text(entry.get("objective")),
        "Materials & Methods": _text(entry.get("materials_methods")),
        "Result": _text(entry.get("result")),
        "Conclusion": _text(entry.get("conclusion")),
    }
    steps = entry.get("next_steps") or []
    if isinstance(steps, str):
        steps = [line for line in steps.splitlines()]
    next_steps = []
    for step in steps:
        line = re.sub(r"^\s*(?:[-*]\s*)?(?:\[[ xX]\]\s*)?", "", str(step or "")).strip()
        if line:
            next_steps.append(line[:300])
    return {
        "experiment_id": experiment_id,
        "project_code": code,
        "date": date,
        "title": f"{experiment_id}_{code}_{date}",
        "name": _text(entry.get("name") or entry.get("summary_title"), 200),
        "summary": " ".join(_text(entry.get("summary"), 600).split()),
        "assay": assay,
        "outcome": outcome,
        "status": status,
        "input_path": input_path,
        "result_path": result_path,
        "run_id": _text(entry.get("run_id"), 64),
        "negative_result_id": _text(entry.get("negative_result_id"), 32),
        "provenance": {k: " ".join(_text(entry.get(k), 600).split())
                       for k in SOURCE_KEYS + CODE_KEYS + SESSION_KEYS
                       if _text(entry.get(k), 600)},
        "sections": sections,
        "next_steps": next_steps[:20],
    }


def render(entry: dict) -> str:
    """The one layout. Obsidian and the dashboard both read this."""
    fm = [
        "---",
        "type: lab-notebook",
        f"title: {entry['title']}",
        f"experiment_id: {_yaml(entry['experiment_id'])}",
        f"project_id: {entry['project_code']}",
        f"date: {entry['date']}",
        f"assay: {entry['assay']}",
        f"outcome: {entry['outcome']}",
        f"status: {entry['status']}",
        f"input_path: {_yaml(entry['input_path'])}",
        f"result_path: {_yaml(entry['result_path'])}",
    ]
    if entry["name"]:
        fm.append(f"name: {_yaml(entry['name'])}")
    if entry["run_id"]:
        fm.append(f"run_id: {entry['run_id']}")
    if entry["negative_result_id"]:
        fm.append(f"negative_result_id: {entry['negative_result_id']}")
    for key, value in entry.get("provenance", {}).items():
        fm.append(f"{key}: {_yaml(value)}")
    fm.append(f"updated: {datetime.now(PACIFIC).isoformat(timespec='seconds')}")
    fm.append("---")

    body = [f"# {entry['title']}", ""]
    if entry["name"]:
        body += [f"**{entry['name']}**", ""]
    if entry["summary"]:
        body += [f"> {entry['summary']}", ""]
    for section in SECTIONS:
        body.append(f"## {section}")
        body.append("")
        text = entry["sections"][section]
        if section == "Materials & Methods":
            # The data paths lead the section, written by code, every time.
            body.append(f"- **Input data:** `{entry['input_path']}`")
            body.append(f"- **Result data:** `{entry['result_path']}`")
            body.append("")
        if section == "Conclusion":
            body.append(text or "_Not yet written._")
            body.append("")
            body.append("### Next steps")
            body.append("")
            if entry["next_steps"]:
                body += [f"- [ ] {step}" for step in entry["next_steps"]]
            else:
                body.append("_None recorded._")
            body.append("")
            continue
        body.append(text or "_Not yet written._")
        body.append("")
    return "\n".join(fm) + "\n\n" + "\n".join(body).rstrip() + "\n"


def archive_dir(code: str) -> Path:
    return ARCHIVE_ROOT / code


def entry_path(entry: dict) -> Path:
    """Where this entry lives: its archive copy if it was archived, else the
    project notebook. A rewrite of an archived entry stays archived."""
    name = f"{entry['title']}.md"
    archived = archive_dir(entry["project_code"]) / name
    if archived.exists():
        return archived
    return project_folder(entry["project_code"]) / NOTEBOOK_DIR / name


def _rel(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:  # a projects root outside the repo (tests)
        return path.as_posix()


SUPERSEDED_DIR = "_superseded"


def supersede_entry(code: str, title: str, *, kept_in: str, sync_db: bool = True) -> dict:
    """Set a duplicate aside (the owner, 2026-09-21: the TEV pages copied into
    both Beta and Gamma belong to Gamma). The file moves to
    90_Archive/Lab Notebook/_superseded/<code>/ - out of every listing, never
    deleted - and records which project keeps the page."""
    if not TITLE.match(title):
        raise NotebookError(f"not a notebook entry title: {title!r}")
    code = _canonical_code(code)
    name = f"{title}.md"
    src = next((p for p in (archive_dir(code) / name,
                            project_folder(code) / NOTEBOOK_DIR / name) if p.exists()), None)
    if src is None:
        raise NotebookError(f"{title} is not in the {code} notebook or archive")
    dst = ARCHIVE_ROOT / SUPERSEDED_DIR / code / name
    if dst.exists():
        raise NotebookError(f"{dst.name} is already set aside; nothing moved")
    dst.parent.mkdir(parents=True, exist_ok=True)
    text = src.read_text(encoding="utf-8")
    note = f"superseded_by: {_yaml(kept_in)}\n"
    if text.startswith("---\n") and "superseded_by:" not in text:
        text = text.replace("\n---\n", "\n" + note + "---\n", 1)
    atomic_write_text(dst, text)
    src.unlink()  # the content now lives at dst: a move, not a delete
    if sync_db and DB.exists():
        try:
            con = sqlite3.connect(DB, timeout=30)
            try:
                now = int(datetime.now().timestamp() * 1000)
                con.execute(
                    "UPDATE Note SET sourceUrl=?, archivedAt=COALESCE(archivedAt, ?), updatedAt=? WHERE sourceUrl=?",
                    (_rel(dst), now, now, _rel(src)))
                con.commit()
            finally:
                con.close()
        except sqlite3.Error as exc:
            log_line("lab_notebook", f"note sync failed superseding {title}: {exc}")
    log_line("lab_notebook", f"superseded {_rel(src)} -> {_rel(dst)} (kept in {kept_in})")
    return {"path": _rel(dst), "title": title, "projectCode": code, "keptIn": kept_in}


def move_entry(code: str, title: str, *, to_archive: bool, sync_db: bool = True) -> dict:
    """Archive (or restore) one entry: a move between the project notebook and
    90_Archive/Lab Notebook/<code>/. Refuses to overwrite either side."""
    if not TITLE.match(title):
        raise NotebookError(f"not a notebook entry title: {title!r}")
    code = _canonical_code(code)
    live = project_folder(code) / NOTEBOOK_DIR / f"{title}.md"
    archived = archive_dir(code) / f"{title}.md"
    src, dst = (live, archived) if to_archive else (archived, live)
    if not src.exists():
        raise NotebookError(f"{title} is not {'in the notebook' if to_archive else 'archived'}")
    if dst.exists():
        raise NotebookError(f"{dst.name} already exists at the destination; nothing moved")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    if sync_db and DB.exists():
        try:
            con = sqlite3.connect(DB, timeout=30)
            try:
                now = int(datetime.now().timestamp() * 1000)
                con.execute(
                    "UPDATE Note SET sourceUrl=?, archivedAt=?, updatedAt=? WHERE sourceUrl=?",
                    (_rel(dst), now if to_archive else None, now, _rel(src)))
                con.commit()
            finally:
                con.close()
        except sqlite3.Error as exc:
            log_line("lab_notebook", f"note sync failed moving {title}: {exc}")
    log_line("lab_notebook", f"{'archived' if to_archive else 'restored'} {_rel(dst)}")
    return {"path": _rel(dst), "title": title, "projectCode": code,
            "archived": to_archive}


def write_entry(raw: dict, *, sync_db: bool = True, archived: bool = False) -> dict:
    """Validate, render, file, and link one entry. Returns where it landed.

    `archived=True` files it straight into the notebook archive - how past
    notebooks (OneNote) come in: they are records, not working entries.
    """
    entry = _normalize(raw)
    path = entry_path(entry)
    if raw.get("keep_provenance") and path.exists():
        # The edit dialog resends only what it shows; keep what it does not.
        old, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
        for key in KEPT_ON_REWRITE:
            value = " ".join(str(old.get(key) or "").split())[:600]
            if not value:
                continue
            if key in ("run_id", "negative_result_id"):
                entry[key] = entry[key] or value
            else:
                entry["provenance"].setdefault(key, value)
    if archived and path.parent != archive_dir(entry["project_code"]):
        live = path
        path = archive_dir(entry["project_code"]) / path.name
        if live.exists():
            raise NotebookError(f"{live.name} is a live notebook entry; archive it instead")
    path.parent.mkdir(parents=True, exist_ok=True)
    replaced = False
    if path.exists():
        # A rewrite keeps the previous version. Never a delete.
        stamp = datetime.now(PACIFIC).strftime("%Y%m%d-%H%M%S")
        history = path.parent / HISTORY_DIR
        history.mkdir(exist_ok=True)
        shutil.copy2(path, history / f"{path.stem}.{stamp}.md")
        replaced = True
    text = render(entry)
    problems = check_text(text, path.stem)
    if problems:
        raise NotebookError("; ".join(problems))
    atomic_write_text(path, text)
    rel = _rel(path)
    note_id = None
    if sync_db:
        try:
            note_id = _sync_note(entry, rel, text,
                                 archived=path.parent == archive_dir(entry["project_code"]))
        except sqlite3.Error as exc:  # the file is the record; the row is a link
            log_line("lab_notebook", f"note sync failed for {rel}: {exc}")
    log_line("lab_notebook", f"{'rewrote' if replaced else 'wrote'} {rel}")
    return {"path": rel, "title": entry["title"], "replaced": replaced,
            "noteId": note_id, "projectCode": entry["project_code"]}


# ------------------------------------------------------------------ prisma link

def _match_project(con, code: str) -> str | None:
    """A Prisma project whose title names the code, if exactly one does."""
    rows = con.execute(
        "SELECT id, title FROM Project WHERE archivedAt IS NULL").fetchall()
    exact = [r[0] for r in rows if r[1].strip().lower() == code.lower()]
    if len(exact) == 1:
        return exact[0]
    loose = [r[0] for r in rows if code.lower() in r[1].lower()]
    return loose[0] if len(loose) == 1 else None


def _sync_note(entry: dict, rel: str, text: str, *, archived: bool = False) -> str | None:
    """Upsert the Prisma Note that puts this entry on its project's page.

    Keyed on sourceUrl, the vault path. The markdown file stays canonical: the
    row carries a copy for the planner's project view, rewritten on each save.
    """
    if not DB.exists():
        return None
    now = int(datetime.now().timestamp() * 1000)
    date_ms = int(datetime.strptime(entry["date"], "%Y-%m-%d")
                  .replace(tzinfo=PACIFIC).timestamp() * 1000)
    body = text.split("\n---\n", 1)[-1].strip()
    title = entry["title"] + (f" - {entry['name']}" if entry["name"] else "")
    con = sqlite3.connect(DB, timeout=30)
    try:
        con.execute("PRAGMA busy_timeout=30000")
        project_id = _match_project(con, entry["project_code"])
        row = con.execute("SELECT id FROM Note WHERE sourceUrl = ?", (rel,)).fetchone()
        if row:
            con.execute(
                """UPDATE Note SET title=?, contentMarkdown=?, type=?, date=?,
                   projectId=COALESCE(projectId, ?), updatedAt=?, archivedAt=?
                   WHERE id=?""",
                (title[:300], body[:200_000], NOTE_TYPE, date_ms, project_id,
                 now, now if archived else None, row[0]))
            note_id = row[0]
        else:
            note_id = f"note_{uuid.uuid4().hex}"
            con.execute(
                """INSERT INTO Note
                   (id,title,contentMarkdown,type,pinned,sourceUrl,date,projectId,
                    areaId,resourceId,createdAt,updatedAt,archivedAt)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (note_id, title[:300], body[:200_000], NOTE_TYPE, 0, rel,
                 date_ms, project_id, None, None, now, now, now if archived else None))
        con.commit()
        return note_id
    finally:
        con.close()


# ------------------------------------------------------------------ checking

def parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, text
    fm = {}
    for line in text[4:end].splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            value = value.strip()
            if value.startswith('"'):
                try:
                    value = json.loads(value)
                except json.JSONDecodeError:
                    pass
            fm[key.strip()] = value
    return fm, text[end + 5:]


def check_text(text: str, stem: str) -> list[str]:
    """Everything the contract promises, as a list of what is broken."""
    problems = []
    fm, body = parse_frontmatter(text)
    if fm.get("type") != "lab-notebook":
        problems.append("frontmatter type is not lab-notebook")
    if not TITLE.match(stem):
        problems.append(f"filename {stem!r} is not ExperimentID_ProjectID_YYYY-MM-DD")
    if fm.get("title") != stem:
        problems.append("frontmatter title does not match the filename")
    for key in ("input_path", "result_path"):
        if not str(fm.get(key) or "").strip():
            problems.append(f"missing {key}")
    headings = re.findall(r"^## (.+?)\s*$", body, flags=re.M)
    if tuple(headings) != SECTIONS:
        problems.append(f"sections are {headings}, expected {list(SECTIONS)}")
    methods = body.split("## Materials & Methods", 1)[-1]
    if "**Input data:**" not in methods or "**Result data:**" not in methods:
        problems.append("Materials & Methods does not lead with the data paths")
    if "### Next steps" not in body.split("## Conclusion", 1)[-1]:
        problems.append("Conclusion has no Next steps")
    return problems


def check_file(path: Path) -> list[str]:
    return check_text(path.read_text(encoding="utf-8"), path.stem)


# ------------------------------------------------------------------ session provenance

def _git(repo: Path, *args: str) -> str:
    try:
        out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                             text=True, encoding="utf-8", errors="replace", timeout=20)
    except (OSError, subprocess.SubprocessError):
        return ""
    # rstrip only: `status --porcelain` lines start with a significant space.
    return out.stdout.rstrip() if out.returncode == 0 else ""


def _clean_remote(url: str) -> str:
    """A remote without credentials: `https://user:token@host/x` -> `https://host/x`."""
    return re.sub(r"^(\w+://)[^/@]+@", r"\1", url)


# Places a session's files disappear from: temp dirs, Claude job/worktree
# folders (deleted with the job), and scratch folders.
SCRATCH_HINTS = ("/tmp/", "/temp/", "/appdata/local/temp/", "/.claude/jobs/",
                 "/.claude/worktrees/", "/scratch/")


def _norm(path: Path) -> str:
    return "/" + path.as_posix().lower().strip("/") + "/"


def _describe_path(raw: str) -> dict:
    path = Path(os.path.expanduser(raw.strip()))
    info = {"path": raw.strip(), "exists": path.exists()}
    warnings = []
    if not path.is_absolute():
        warnings.append("relative path - record an absolute one")
    if path.exists():
        stat = path.stat()
        info["kind"] = "dir" if path.is_dir() else "file"
        if path.is_file():
            info["bytes"] = stat.st_size
        info["modified"] = datetime.fromtimestamp(stat.st_mtime, PACIFIC).isoformat(timespec="seconds")
    else:
        warnings.append("does not exist on this machine")
    where = _norm(path.resolve() if path.exists() else path)
    if (any(h in where for h in SCRATCH_HINTS)
            or where.startswith(_norm(Path(tempfile.gettempdir()).resolve()))):
        warnings.append("in a scratch/temp/worktree folder that may be cleaned up - "
                        "move it somewhere durable before logging it")
    if warnings:
        info["warnings"] = warnings
    return info


def session_provenance(repo: str, inputs: list[str], results: list[str],
                       others: list[str], save_diff: str = "") -> dict:
    """What code can state about a computational session: the code's git state
    and whether each data path is real. The skill copies these, never guesses.

    Returns `frontmatter` (CODE_KEYS to pass straight to `write`), the checked
    paths, and `warnings` the skill must show before filing.

    `save_diff` keeps uncommitted code itself, not just the fact of it: the
    tracked changes against HEAD plus the list of untracked files, written to
    that file (next to the results) and recorded as `code_diff`.
    """
    root = Path(os.path.expanduser(repo or ".")).resolve()
    top = _git(root, "rev-parse", "--show-toplevel")
    fm: dict[str, str] = {}
    warnings: list[str] = []
    dirty: list[str] = []
    if top:
        fm["code_repo"] = Path(top).as_posix()
        remote = _clean_remote(_git(root, "remote", "get-url", "origin"))
        fm["code_remote"] = remote
        fm["code_branch"] = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
        fm["code_commit"] = _git(root, "rev-parse", "HEAD")
        dirty = [line[3:] for line in _git(root, "status", "--porcelain").splitlines() if line.strip()]
        fm["code_dirty"] = f"yes ({len(dirty)} files)" if dirty else "no"
        if dirty and save_diff:
            target = Path(os.path.expanduser(save_diff)).resolve()
            if target.exists():
                raise NotebookError(f"{target} exists; pick a new file for the diff")
            untracked = [line[3:] for line in _git(root, "status", "--porcelain").splitlines()
                         if line.startswith("??")]
            patch = _git(root, "diff", "HEAD", "--binary")
            header = [f"# uncommitted changes in {Path(top).as_posix()} against "
                      f"{fm['code_commit'] or '(no commit)'}"]
            header += [f"# untracked (not in the patch): {u}" for u in untracked]
            target.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(target, "\n".join(header) + "\n" + patch + "\n")
            fm["code_diff"] = target.as_posix()
        elif dirty:
            warnings.append(f"{len(dirty)} uncommitted change(s) in {Path(top).name}: the commit "
                            "alone does not reproduce this run - commit first, or rerun with "
                            "--save-diff <results>/code-uncommitted.patch")
        if not remote:
            warnings.append("the repo has no remote; the commit exists only on this machine")
        if not fm["code_commit"]:
            warnings.append("the repo has no commits yet: nothing pins this code")
    else:
        fm["code_repo"] = root.as_posix()
        warnings.append(f"{root} is not a git repository: no commit pins this code")
    fm["code_captured"] = datetime.now(PACIFIC).isoformat(timespec="seconds")
    # Names only, never values from the environment.
    env = os.getenv("CONDA_DEFAULT_ENV") or Path(os.getenv("VIRTUAL_ENV") or "").name
    if env:
        fm["environment"] = f"{env} (python {sys.version.split()[0]})"
    checked = {
        "inputs": [_describe_path(p) for p in inputs if p.strip()],
        "results": [_describe_path(p) for p in results if p.strip()],
        "other": [_describe_path(p) for p in others if p.strip()],
    }
    if not checked["inputs"]:
        warnings.append("no input path given - every entry records one")
    if not checked["results"]:
        warnings.append("no result path given - every entry records one")
    for group in checked.values():
        for item in group:
            warnings += [f"{item['path']}: {w}" for w in item.get("warnings", [])]
    return {"frontmatter": {k: v for k, v in fm.items() if v},
            "dirtyFiles": dirty[:30], "paths": checked, "warnings": warnings}


def template(assay: str) -> dict:
    """The JSON skeleton `write` takes, with guidance text per field."""
    if assay != "computational":
        raise NotebookError("only the computational template exists; bench and "
                            "LabSerf entries come from the dialog and the runner")
    return {"project_code": "", "assay": "computational", "outcome": "pending",
            "status": "draft", "name": "", "summary": "", "input_path": "",
            "result_path": "", **{k: "" for k in CODE_KEYS + SESSION_KEYS},
            **COMPUTATIONAL_TEMPLATE}


def session_info(transcript: str = "", cwd: str = "") -> dict:
    """The session's own id and model(s), read from its transcript - the skill
    records these instead of stating them from memory. With no transcript
    given, the newest one for `cwd` is the session running now."""
    import session_digest
    path = Path(transcript) if transcript else session_digest.latest_transcript(cwd or os.getcwd())
    if path is None or not path.exists():
        return {"error": "no transcript found for this session", "ai_model": ""}
    d = session_digest.digest(path)
    return {"session_id": d["session_id"], "ai_model": ", ".join(d["models"]),
            "models": d["models"], "cwd": d["cwd"], "started": d["started"],
            "ended": d["ended"], "prompts": d["prompts"], "transcript": str(path),
            "already_logged": session_digest.wrote_notebook_entry(d)}


def find_session_entry(code: str, session_id: str) -> dict | None:
    """The entry already filed for this session, if any (live or archived).

    A resumed session ends more than once; the second log rewrites the first
    entry (history kept) instead of filing a duplicate."""
    if not session_id:
        return None
    code = _canonical_code(code)
    for folder in (project_folder(code) / NOTEBOOK_DIR, archive_dir(code)):
        for path in sorted(folder.glob("*.md")) if folder.is_dir() else []:
            try:
                fm, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
            except OSError:
                continue
            if fm.get("session_id") == session_id:
                return {"path": path, "experiment_id": fm.get("experiment_id", ""),
                        "date": fm.get("date", ""), "title": path.stem}
    return None


# ------------------------------------------------------------------ cli

def _emit(payload: dict, code: int = 0) -> int:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    return code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("projects")
    nid = sub.add_parser("next-id")
    nid.add_argument("--project", required=True)
    wr = sub.add_parser("write")
    # A UTF-8 file instead of stdin: Windows PowerShell 5.1 re-encodes what it
    # pipes to a native program, which mangles Korean and symbols.
    wr.add_argument("--file", default="")
    chk = sub.add_parser("check")
    chk.add_argument("file")
    newp = sub.add_parser("create-project")
    newp.add_argument("--code", required=True)
    for name in ("archive", "restore"):
        mv = sub.add_parser(name)
        mv.add_argument("--project", required=True)
        mv.add_argument("--title", required=True)
    tpl = sub.add_parser("template")
    tpl.add_argument("--assay", default="computational")
    prov = sub.add_parser("provenance")
    prov.add_argument("--repo", default=".")
    prov.add_argument("--input", action="append", default=[])
    prov.add_argument("--result", action="append", default=[])
    prov.add_argument("--path", action="append", default=[])
    prov.add_argument("--save-diff", default="")
    ses = sub.add_parser("session")
    ses.add_argument("--transcript", default="")
    ses.add_argument("--cwd", default="")
    args = parser.parse_args()
    try:
        if args.cmd == "projects":
            return _emit({"projects": list_projects()})
        if args.cmd == "next-id":
            return _emit({"experimentId": next_experiment_id(args.project)})
        if args.cmd == "write":
            data = (Path(args.file).read_bytes() if args.file
                    else sys.stdin.buffer.read())
            raw = json.loads(data.decode("utf-8-sig") or "{}")
            return _emit(write_entry(raw))
        if args.cmd == "session":
            return _emit(session_info(args.transcript, args.cwd))
        if args.cmd == "template":
            return _emit(template(args.assay))
        if args.cmd == "provenance":
            return _emit(session_provenance(args.repo, args.input, args.result, args.path,
                                            args.save_diff))
        if args.cmd == "create-project":
            return _emit(create_project(args.code))
        if args.cmd in ("archive", "restore"):
            return _emit(move_entry(args.project, args.title,
                                    to_archive=args.cmd == "archive"))
        if args.cmd == "check":
            problems = check_file(Path(args.file))
            return _emit({"ok": not problems, "problems": problems},
                         0 if not problems else 1)
    except (NotebookError, json.JSONDecodeError, OSError) as exc:
        return _emit({"error": str(exc)}, 1)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
