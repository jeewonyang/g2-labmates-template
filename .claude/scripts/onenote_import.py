"""Bring a past OneNote lab notebook into G2 (the owner, 2026-09-21).

Three things come out of one OneNote notebook:

1. **Experiment pages -> notebook entries.** Every page of a project section
   group's "Experiments" section becomes an entry in that project's notebook
   (`10_Projects/<project>/04_Notebook/`), titled `ON-nnn_<Project>_<date>`
   (ON = from OneNote, so the EXP-nnn series of new work never collides with
   it). Like every entry, it shows on the Lab notebook while its project is
   Active and in the Archive once the project is Done.
2. **Protocol pages -> LabSerf protocols** under
   `labserf/Protocols/onenote/<Project>/`, which the Advisor's
   protocol index reads and cites.
3. **Stock Solutions pages -> LabSerf protocols** under
   `Protocols/onenote/Stock Solutions/` - inventories, primer lists, buffers.

Deterministic and local: no model reads a page on the way in (these are
unpublished results; bulk processing stays off the cloud). Nothing is
rephrased: each entry keeps the page verbatim. When the page used their own
template headings (Introduction / Objective / Materials & Method / Result /
Conclusion) with content under them, that content goes to the matching
section; a template block left empty above free-form notes is dropped and the
notes become Materials & Methods. Nothing is invented to fill a section.

The export reads a COPY of the notebook: OneNote may rewrite files it opens,
and the source lives under archive/, a Google Drive mirror.

Re-running is safe: a manifest keyed on OneNote page id keeps every page on
the same ExperimentID, and a rewrite goes through the writer's history.

    python .claude/scripts/onenote_import.py --source "<notebook folder>" [--dry-run]
    python .claude/scripts/onenote_import.py --skip-export       # reuse the last export
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import lab_notebook as nb  # noqa: E402
import onenote_md  # noqa: E402
from shared import DATA, REPO_ROOT, atomic_write_json, atomic_write_text, log_line, read_json  # noqa: E402

PACIFIC = ZoneInfo("America/Los_Angeles")
WORK = DATA / "onenote"
MANIFEST = WORK / "import-manifest.json"
# Which project owns a page OneNote holds in several projects, keyed by the
# page's content hash: {"<sha1>": {"owner": "Gamma", "title": ..., "drop": [...]}}.
# Set with --keep/--drop; read on every run so a re-import never brings a
# dropped copy back.
OWNERS = WORK / "owners.json"
EXPORTER = SCRIPTS / "onenote_export.ps1"
LABSERF_PROTOCOLS = Path(os.environ.get("LABSERF_ROOT") or (REPO_ROOT / "labserf")) / "Protocols" / "onenote"
DEFAULT_SOURCE = REPO_ROOT / "archive" / "OneNote" / "LabNotebook"  # or pass --source
ON_ID = re.compile(r"^ON-(\d{3,})$")
HEADINGS = {
    "introduction": "introduction",
    "background": "introduction",
    "objective": "objective",
    "objectives": "objective",
    "aim": "objective",
    "materials & method": "materials_methods",
    "materials & methods": "materials_methods",
    "materials and methods": "materials_methods",
    "materials": "materials_methods",
    "methods": "materials_methods",
    "method": "materials_methods",
    "result": "result",
    "results": "result",
    "conclusion": "conclusion",
    "conclusions": "conclusion",
    "discussion": "conclusion",
}
DATA_PATH = re.compile(
    r"([A-Za-z]:\\[^\s|<>\"*?]+|\\\\[^\s|<>\"*?]+|/Volumes/[^\s|<>\"]+|"
    r"\b[\w.-]+\.(?:fcs|mqd|wsp|mat|csv|xlsx|pzfx|dna|ab1|tif|tiff|czi|nd2)\b)",
    re.I,
)


# ------------------------------------------------------------------ export

def export(source: Path) -> Path:
    """Copy the notebook to the scratch area and export its pages via COM."""
    copy = WORK / source.name
    if copy.exists():
        stamp = datetime.now(PACIFIC).strftime("%Y%m%d-%H%M%S")
        copy.rename(copy.with_name(f"{copy.name}.prev-{stamp}"))  # kept, not deleted
    shutil.copytree(source, copy)
    out = WORK / "xml"
    if out.exists():
        stamp = datetime.now(PACIFIC).strftime("%Y%m%d-%H%M%S")
        out.rename(out.with_name(f"xml.prev-{stamp}"))
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(EXPORTER),
         "-Notebook", str(copy), "-Out", str(out)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900,
    )
    if proc.returncode != 0 or "exported" not in proc.stdout:
        raise RuntimeError(f"OneNote export failed: {(proc.stderr or proc.stdout).strip()[:800]}")
    return out


# ------------------------------------------------------------------ hierarchy

def pages_by_section(xml_dir: Path) -> list[dict]:
    """Every exported page with its section path, parent page, and file."""
    root = ET.fromstring((xml_dir / "_hierarchy.xml").read_text(encoding="utf-8-sig"))
    ns = onenote_md.NS
    by_id = {}
    for f in sorted(xml_dir.glob("[0-9]*.xml")):
        page = onenote_md.read_page(f)
        by_id[page["page_id"]] = page
    rows = []

    def walk(node, path):
        parents: dict[int, str] = {}
        for ch in node:
            tag = ch.tag.replace(ns, "")
            if tag in ("SectionGroup", "Section"):
                if ch.get("isRecycleBin") == "true" or ch.get("isInRecycleBin") == "true":
                    continue
                walk(ch, path + [ch.get("name")])
            elif tag == "Page":
                level = int(ch.get("pageLevel") or 1)
                parents[level] = ch.get("name") or ""
                page = by_id.get(ch.get("ID"))
                if page is None:
                    continue
                rows.append({
                    **page,
                    "section": path,
                    "section_file": ch.get("ID"),
                    "level": level,
                    "parent": parents.get(level - 1, "") if level > 1 else "",
                })

    walk(root, [])
    return rows


# ------------------------------------------------------------------ mapping

def _heading(line: str) -> str | None:
    m = re.match(r"^- (?:\[[ x]\] )?(.+?)\s*:?\s*$", line)
    if not m:
        return None
    return HEADINGS.get(m.group(1).strip().lower())


def split_sections(markdown: str) -> dict[str, str]:
    """Their template headings -> sections; everything else -> Materials & Methods.

    Only top-level lines count as headings. A run of headings with nothing
    between them is an unfilled template block: dropped, and the notes that
    follow are the body.
    """
    lines = markdown.splitlines()
    marks = [(i, _heading(line)) for i, line in enumerate(lines) if _heading(line)]
    out = {k: [] for k in ("introduction", "objective", "materials_methods", "result", "conclusion")}
    if not marks:
        out["materials_methods"] = lines
        return {k: "\n".join(v).strip() for k, v in out.items()}
    idx = [i for i, _ in marks]
    template = len(marks) >= 3 and idx == list(range(idx[0], idx[0] + len(idx)))
    if template:
        body = lines[:idx[0]] + lines[idx[-1] + 1:]
        out["materials_methods"] = body
        return {k: "\n".join(v).strip() for k, v in out.items()}
    out["materials_methods"] = lines[:idx[0]]
    for n, (i, key) in enumerate(marks):
        end = idx[n + 1] if n + 1 < len(idx) else len(lines)
        # Children of a heading bullet are indented; lift them to top level.
        chunk = [re.sub(r"^  ", "", ln) for ln in lines[i + 1:end]]
        out[key].extend(chunk)
    return {k: "\n".join(v).strip() for k, v in out.items()}


def entry_date(title: str, created: str) -> str:
    """The date in the title (their EXnnn_YYYYMMDD / YYMMDD naming) beats the
    page's creation time, which moved when pages were reorganised."""
    for m in re.finditer(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)", title):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}"
    m = re.match(r"^(\d{2})(\d{2})(\d{2})(?!\d)", title.strip())
    if m:
        y, mo, d = 2000 + int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}"
    try:
        dt = datetime.fromisoformat(created.replace("Z", "+00:00")).astimezone(PACIFIC)
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return datetime.now(PACIFIC).strftime("%Y-%m-%d")


def _first_line(markdown: str) -> str:
    for line in markdown.splitlines():
        text = re.sub(r"^\s*-\s*(\[[ x]\]\s*)?", "", line).strip()
        if (text and not text.startswith("|") and not text.startswith("_[")
                and HEADINGS.get(text.rstrip(":").strip().lower()) is None):
            return text[:180]
    return ""


def _code_for(section_group: str, projects: list[dict]) -> str | None:
    want = section_group.strip().lower()
    for p in projects:
        if p["code"].lower() == want:
            return p["code"]
    return None


def _source(notebook: Path, section: list[str]) -> str:
    return str(notebook.joinpath(*section)) + ".one"


# ------------------------------------------------------------------ import

def _digest(r: dict) -> str:
    return hashlib.sha1(r["markdown"].strip().encode()).hexdigest()


def _project_of(r: dict, projects: list[dict]) -> str | None:
    return _code_for(r["section"][0], projects) if r["section"] else None


def record_owner(rows: list[dict], keep: str, drop: str) -> list[str]:
    """Every page present in both `keep` and `drop` belongs to `keep`."""
    projects = nb.list_projects()
    keep = _code_for(keep, projects) or keep
    drop = _code_for(drop, projects) or drop
    by_digest: dict[str, set[str]] = {}
    titles: dict[str, str] = {}
    for r in rows:
        code = _project_of(r, projects) or (r["section"][0] if r["section"] else "")
        if r["markdown"].strip():
            by_digest.setdefault(_digest(r), set()).add(code)
            titles.setdefault(_digest(r), r["title"])
    owners = read_json(OWNERS, {}) or {}
    decided = []
    for digest, codes in by_digest.items():
        if keep in codes and drop in codes:
            rec = owners.setdefault(digest, {"owner": keep, "title": titles[digest], "drop": []})
            rec["owner"] = keep
            rec["drop"] = sorted(set(rec.get("drop", [])) | {drop})
            decided.append(titles[digest])
    atomic_write_json(OWNERS, owners)
    return decided


def import_experiments(rows: list[dict], notebook: Path, *, dry_run: bool) -> list[dict]:
    projects = nb.list_projects()
    manifest = read_json(MANIFEST, {}) or {}
    owners = read_json(OWNERS, {}) or {}
    written = []
    next_id: dict[str, int] = {}
    for rec in manifest.values():
        m = ON_ID.match(rec.get("experiment_id", ""))
        if m:
            next_id[rec["project"]] = max(next_id.get(rec["project"], 0), int(m.group(1)))
    for r in rows:
        if len(r["section"]) < 2 or r["section"][-1].lower() != "experiments":
            continue
        code = _code_for(r["section"][0], projects)
        if code is None:
            log_line("onenote_import", f"no notebook project for section {r['section']}; skipped")
            continue
        body = r["markdown"].strip()
        if not body or "template" in r["title"].lower():
            continue
        key = f"{code}:{r['page_id']}"
        rec = manifest.get(key)
        owner = (owners.get(_digest(r)) or {}).get("owner")
        if owner and owner != code:
            # A copy in a project that does not own the page: set any entry
            # made from it aside, and never file it again.
            if rec and not rec.get("superseded") and not dry_run:
                title = f"{rec['experiment_id']}_{code}_{entry_date(r['title'], r['created'])}"
                try:
                    nb.supersede_entry(code, title, kept_in=owner)
                except nb.NotebookError as exc:
                    log_line("onenote_import", f"could not set aside {title}: {exc}")
                rec["superseded"] = owner
            written.append({"title": rec["experiment_id"] if rec else "", "page": r["title"],
                            "setAside": code, "keptIn": owner})
            continue
        if rec is None:
            next_id[code] = next_id.get(code, 0) + 1
            rec = {"project": code, "experiment_id": f"ON-{next_id[code]:03d}", "title": r["title"]}
            manifest[key] = rec
        sections = split_sections(body)
        digest = _digest(r)
        dropped = set((owners.get(digest) or {}).get("drop", []))
        twins = [x["section"][0] for x in rows
                 if x is not r and x["section"][-1:] == ["Experiments"]
                 and _digest(x) == digest
                 and (_project_of(x, projects) or x["section"][0]) not in dropped]
        intro_bits = [
            f"Imported from the OneNote notebook **{notebook.name}**, section "
            f"*{'/'.join(r['section'])}*, page \"{r['title']}\".",
        ]
        if r["parent"]:
            intro_bits.append(f"Part of the OneNote topic \"{r['parent']}\".")
        if twins:
            intro_bits.append(f"An identical page is also filed under {', '.join(sorted(set(twins)))}.")
        if sections["introduction"]:
            intro_bits.append("")
            intro_bits.append(sections["introduction"])
        paths = sorted(set(DATA_PATH.findall(body)))
        entry = {
            "project_code": code,
            "experiment_id": rec["experiment_id"],
            "date": entry_date(r["title"], r["created"]),
            "assay": "bench",
            "outcome": "pending",
            "status": "final",
            "name": r["title"],
            "summary": _first_line(body),
            "input_path": f"OneNote: {_source(notebook, r['section'])} > {r['title']}",
            "result_path": "; ".join(paths[:6]) if paths else "not recorded in the OneNote page",
            "introduction": "\n".join(intro_bits),
            "objective": sections["objective"] or r["title"],
            "materials_methods": sections["materials_methods"],
            "result": sections["result"]
            or "_Not separated from the notes in the OneNote page; the full record is under Materials & Methods._",
            "conclusion": sections["conclusion"] or "_None recorded in the OneNote page._",
            "next_steps": [],
            "source": "onenote",
            "source_path": _source(notebook, r["section"]),
            "source_page": r["title"],
            "source_parent": r["parent"],
            "source_created": r["created"],
            "source_modified": r["modified"],
            "also_in": ", ".join(sorted(set(twins))),
        }
        if dry_run:
            written.append({"title": f"{rec['experiment_id']}_{code}_{entry['date']}", "page": r["title"]})
            continue
        out = nb.write_entry(entry)
        written.append({**out, "page": r["title"]})
    if not dry_run:
        atomic_write_json(MANIFEST, manifest)
    return written


def _slug(title: str) -> str:
    s = re.sub(r"[^\w\s.-]+", " ", title).strip()
    return re.sub(r"\s+", " ", s)[:80] or "untitled"


def import_protocols(rows: list[dict], notebook: Path, *, dry_run: bool) -> list[str]:
    """Protocol and Stock Solutions pages -> LabSerf Protocols/onenote/."""
    projects = nb.list_projects()
    owners = read_json(OWNERS, {}) or {}
    written, seen = [], {}
    for r in rows:
        section = r["section"]
        leaf = section[-1].lower() if section else ""
        if leaf in ("protocol", "protocols") and len(section) >= 2:
            folder = _code_for(section[0], projects) or section[0]
        elif leaf == "stock solutions":
            folder = "Stock Solutions"
        else:
            continue
        body = r["markdown"].strip()
        if not body:
            continue
        digest = hashlib.sha1(body.encode()).hexdigest()
        owner = (owners.get(digest) or {}).get("owner")
        if owner and folder != owner:
            # Not this project's page: move a copy an earlier run filed here
            # aside (kept, not deleted) and let the owner's copy stand.
            stale = LABSERF_PROTOCOLS / folder / f"{_slug(r['title'])}.md"
            if stale.exists() and not dry_run:
                aside = LABSERF_PROTOCOLS / "_superseded" / folder / stale.name
                aside.parent.mkdir(parents=True, exist_ok=True)
                if not aside.exists():
                    shutil.move(str(stale), str(aside))
            continue
        if digest in seen:
            # The same protocol filed under two projects: one file, both named.
            first = seen[digest]
            path = LABSERF_PROTOCOLS / first["folder"] / f"{_slug(first['title'])}.md"
            if not dry_run and path.exists():
                text = path.read_text(encoding="utf-8")
                if f"also filed under {folder}" not in text:
                    text = text.replace("\n\n", f"\n> Also filed under {folder} in OneNote.\n\n", 1)
                    atomic_write_text(path, text)
            continue
        seen[digest] = {"folder": folder, "title": r["title"]}
        path = LABSERF_PROTOCOLS / folder / f"{_slug(r['title'])}.md"
        header = (
            f"# {r['title']}\n\n"
            f"> Imported from OneNote: {_source(notebook, section)} (page created "
            f"{r['created'][:10]}, last edited {r['modified'][:10]}). Verbatim; "
            "images and attachments are not carried over.\n\n"
        )
        written.append(str(path.relative_to(REPO_ROOT)))
        if not dry_run:
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(path, header + body + "\n")
    return written


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--source", default=str(DEFAULT_SOURCE),
                    help="the OneNote notebook folder (it is copied, never opened in place)")
    ap.add_argument("--skip-export", action="store_true",
                    help="reuse the last export under .claude/data/onenote/xml")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--keep", help="with --drop: pages OneNote holds in both projects belong to this one")
    ap.add_argument("--drop", help="with --keep: the project whose copies are set aside")
    args = ap.parse_args()
    if bool(args.keep) != bool(args.drop):
        ap.error("--keep and --drop go together")
    source = Path(args.source).resolve()
    xml_dir = WORK / "xml" if args.skip_export else export(source)
    rows = pages_by_section(xml_dir)
    if args.keep and not args.dry_run:
        decided = record_owner(rows, args.keep, args.drop)
        log_line("onenote_import", f"{len(decided)} shared pages now owned by {args.keep}: {decided}")
    entries = import_experiments(rows, source, dry_run=args.dry_run)
    protocols = import_protocols(rows, source, dry_run=args.dry_run)
    print(json.dumps({"entries": entries, "protocols": protocols,
                      "pages": len(rows), "dry_run": args.dry_run}, ensure_ascii=False, indent=1))
    log_line("onenote_import", f"{len(entries)} entries, {len(protocols)} protocol pages from {source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
