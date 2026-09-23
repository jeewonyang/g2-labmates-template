#!/usr/bin/env python
"""Index this lab's own protocol documents so they can be searched offline.

`Protocols/` holds the lab's .docx / .doc / .xlsx / .pdf protocols. Those are
the *authoritative* source for buffer conditions, concentrations, incubation
times and volumes — ahead of any paper. This script extracts their text once
into a local index so the advisor can grep it instead of guessing.

    python index_protocols.py                 # (re)build the index
    python index_protocols.py --search "PEI"  # search the index
    python index_protocols.py --show "Transfection_PEI.xlsx"

Nothing is uploaded anywhere: the index is a plain JSON file next to the
skill, and the lab's documents never leave the machine.
"""
import argparse
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
#: The built index. Queries read only this — never `Protocols/` — so the skill
#: works unchanged when `Protocols/` is absent, moved, or on another machine.
INDEX = SKILL / "assets" / "protocol_index.json"


def find_repo():
    """The repo root, without assuming where this skill is nested.

    `$LABSERF_ROOT`, else the nearest ancestor of the skill or the working
    directory that holds a `.claude/`, else the working directory.
    """
    import os

    env = os.environ.get("LABSERF_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    for start in (SKILL, Path.cwd().resolve()):
        for candidate in (start, *start.parents):
            if (candidate / ".claude").is_dir() and candidate.name != ".claude":
                return candidate
    return Path.cwd().resolve()


PROTOCOLS = find_repo() / "Protocols"

# Lines that carry an actual experimental condition — what we most want to find.
CONDITION_RE = re.compile(
    r"(\d+\s*(?:%|mM|µM|uM|nM|M\b|mg/?m[lL]|µg|ug|ng|mL|ml|µL|uL|L\b|°C|C\b|rpm|×?\s*g\b|min|hr|hour|h\b|sec|s\b|kDa|U/?µ?[lL]|V\b|mA))"
    r"|(pH\s*\d)",
    re.IGNORECASE,
)


def para_text(p):
    """Paragraph text with superscripts preserved as `^n`.

    Word writes "10⁶ cells" as a normal "10" followed by a superscript run
    "6". Plain `.text` concatenates them into "106" — a seeding density wrong by
    four orders of magnitude, with nothing to signal that formatting was lost.
    Subscripts get `_` for the same reason.
    """
    parts = []
    for run in p.runs:
        text = run.text
        if not text:
            continue
        va = None
        try:
            va = run.font.superscript and "super" or (run.font.subscript and "sub" or None)
        except (AttributeError, ValueError):
            pass
        if va == "super":
            text = f"^{text}"
        elif va == "sub":
            text = f"_{text}"
        parts.append(text)
    return "".join(parts) if parts else p.text


def cell_text(cell):
    return " ".join(" ".join(para_text(p) for p in cell.paragraphs).split())


def from_docx(path):
    import docx  # python-docx

    d = docx.Document(str(path))
    out = [para_text(p) for p in d.paragraphs]
    for table in d.tables:
        for row in table.rows:
            cells = [cell_text(c) for c in row.cells]
            if any(cells):
                out.append(" | ".join(cells))
    return out


def from_doc(path):
    """Legacy Word. macOS ships textutil, which handles these reliably."""
    try:
        res = subprocess.run(
            ["textutil", "-convert", "txt", "-stdout", str(path)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if res.returncode == 0:
            return res.stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        pass
    return []


def from_xlsx(path):
    import openpyxl

    out = []
    wb = openpyxl.load_workbook(str(path), data_only=True, read_only=True)
    for ws in wb.worksheets:
        out.append(f"### sheet: {ws.title}")
        for row in ws.iter_rows(values_only=True):
            cells = ["" if c is None else " ".join(str(c).split()) for c in row]
            if any(cells):
                out.append(" | ".join(cells).rstrip(" |"))
    wb.close()
    return out


def from_pdf(path):
    from pypdf import PdfReader

    out = []
    reader = PdfReader(str(path))
    for i, page in enumerate(reader.pages, 1):
        text = page.extract_text() or ""
        for line in text.splitlines():
            out.append(line)
        out.append(f"[--- end of page {i} ---]")
    return out


def from_markdown(path):
    """Plain-text protocols, e.g. pages brought in from OneNote (Protocols/onenote/)."""
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


READERS = {
    ".md": from_markdown,
    ".docx": from_docx,
    ".doc": from_doc,
    ".xlsx": from_xlsx,
    ".xlsm": from_xlsx,
    ".pdf": from_pdf,
}


def build(protocols_dir=PROTOCOLS, out=INDEX):
    if not protocols_dir.is_dir():
        sys.exit(
            f"no protocol folder at {protocols_dir}.\n"
            "Rebuilding is the only step that reads the lab's documents; searching does not.\n"
            "Point it somewhere with --protocols <dir>, or set LABSERF_ROOT."
        )
    docs = {}
    skipped = []
    for path in sorted(protocols_dir.rglob("*")):
        if not path.is_file() or path.name.startswith(("~$", ".")):
            continue
        # Protocols this skill generated are proposals, not lab practice: an
        # index that cited them would let the advisor source itself. And a
        # page set aside as a duplicate (OneNote import) is not a second source.
        if {"generated", "_superseded"} & set(path.relative_to(protocols_dir).parts):
            continue
        reader = READERS.get(path.suffix.lower())
        if reader is None:
            continue
        try:
            lines = reader(path)
        except (zipfile.BadZipFile, OSError, ValueError, KeyError) as exc:
            skipped.append(f"{path.name}: {type(exc).__name__}: {exc}")
            continue
        lines = [ln.strip() for ln in lines]
        # Keep line numbers stable and 1-based so they can be cited.
        docs[str(path.relative_to(protocols_dir))] = lines
        if not any(lines):
            skipped.append(f"{path.name}: parsed but empty (scanned image?)")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"root": str(protocols_dir), "docs": docs}, indent=1), encoding="utf-8")
    return docs, skipped


def load(index=INDEX):
    if not index.exists():
        sys.exit(
            f"No index at {index}.\n"
            f"Build it once from the lab's protocol folder:  python {Path(__file__).name}\n"
            "After that, searching never touches that folder again."
        )
    return json.loads(index.read_text(encoding="utf-8"))


def search(term, index=INDEX, conditions_only=False, context=0):
    data = load(index)
    pat = re.compile(term, re.IGNORECASE)
    hits = 0
    for name, lines in data["docs"].items():
        for i, line in enumerate(lines):
            if not line or not pat.search(line):
                continue
            if conditions_only and not CONDITION_RE.search(line):
                continue
            hits += 1
            print(f"{name}:{i + 1}: {line}")
            for j in range(i + 1, min(i + 1 + context, len(lines))):
                if lines[j]:
                    print(f"{name}:{j + 1}| {lines[j]}")
    if not hits:
        print(f"no match for {term!r} in the lab's own protocols")
    return hits


def show(name, index=INDEX, lines=None):
    """Print one protocol, or `--lines N-M` of it.

    Verifying a citation means reading the cited line and its neighbours, so
    that is a first-class operation rather than something to pipe through sed.
    """
    data = load(index)
    matches = [k for k in data["docs"] if name.lower() in k.lower()]
    if not matches:
        sys.exit(f"no protocol matching {name!r}. Try --list")
    lo, hi = 1, None
    if lines:
        m = re.match(r"^(\d+)(?:\s*-\s*(\d+))?$", lines.strip())
        if not m:
            sys.exit(f"--lines wants N or N-M, got {lines!r}")
        lo = int(m.group(1))
        hi = int(m.group(2) or m.group(1))
    for name_ in matches:
        doc = data["docs"][name_]
        end = len(doc) if hi is None else min(hi, len(doc))
        print(f"===== {name_}  (lines {lo}-{end} of {len(doc)}) =====")
        for i in range(lo, end + 1):
            line = doc[i - 1]
            if line:
                print(f"{i}: {line}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--protocols", type=Path, default=PROTOCOLS)
    ap.add_argument("--index", type=Path, default=INDEX)
    ap.add_argument("--search", metavar="REGEX")
    ap.add_argument("--conditions-only", action="store_true",
                    help="with --search, keep only lines that state a number + unit")
    ap.add_argument("-C", "--context", type=int, default=0)
    ap.add_argument("--show", metavar="FILENAME")
    ap.add_argument("--lines", metavar="N-M",
                    help="with --show, print only this line range (for verifying a citation)")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    if args.search:
        return 0 if search(args.search, args.index, args.conditions_only, args.context) else 1
    if args.show:
        show(args.show, args.index, args.lines)
        return 0
    if args.list:
        data = load(args.index)
        for name, lines in sorted(data["docs"].items()):
            print(f"{len(lines):5d} lines  {name}")
        return 0

    docs, skipped = build(args.protocols, args.index)
    total = sum(len(v) for v in docs.values())
    print(f"indexed {len(docs)} protocols, {total} lines -> {args.index}")
    for s in skipped:
        print(f"  skipped/empty: {s}")
    return 0


if __name__ == "__main__":
    # _console_safe: a cp949/cp1252 Windows console cannot print "—" and the
    # like; replace what it cannot show rather than crash after the work is done.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(errors="replace")
        except AttributeError:
            pass
    try:
        sys.exit(main())
    except BrokenPipeError:  # piped into head
        sys.exit(0)
