"""Text extraction for triage classification.

Deliberately dependency-light: PyMuPDF (`fitz`) is already installed for PDFs,
and .docx is a zip containing XML, so stdlib handles it. Nothing here needs pip.

Everything is best-effort and never raises - a file we cannot read becomes a
`needs_review` job with a reason, not a crash.
"""

import re
import zipfile
from pathlib import Path

# Enough to classify; not so much that a 3 s local call becomes 30 s.
MAX_CHARS = 2_000
# Below this, treat the file as having no usable text (e.g. a scanned PDF).
MIN_USEFUL_CHARS = 50

TEXT_SUFFIXES = {".md", ".txt", ".markdown"}
PDF_SUFFIXES = {".pdf"}
DOCX_SUFFIXES = {".docx"}
# Recognized but not extracted - classified on filename and path alone.
METADATA_ONLY = {".pptx", ".xlsx", ".xls", ".csv", ".zip", ".dna", ".png",
                 ".jpg", ".jpeg", ".tif", ".tiff", ".heic", ".mp4", ".gif"}

_WS = re.compile(r"\s+")
_DOCX_TAG = re.compile(r"<[^>]+>")
_DOCX_PARA = re.compile(r"</w:p>")


def _clean(text: str) -> str:
    return _WS.sub(" ", text).strip()[:MAX_CHARS]


def _from_text(path: Path) -> str:
    try:
        return _clean(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return ""


def _from_pdf(path: Path) -> str:
    try:
        import fitz
    except ImportError:
        return ""
    try:
        out = []
        with fitz.open(str(path)) as doc:
            for page in doc:                      # first pages carry the identity
                out.append(page.get_text())
                if sum(len(o) for o in out) >= MAX_CHARS:
                    break
        return _clean("".join(out))
    except Exception:
        return ""


def _from_docx(path: Path) -> str:
    """A .docx is a zip; word/document.xml holds the body. No dependency needed."""
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8", errors="replace")
    except (OSError, KeyError, zipfile.BadZipFile):
        return ""
    # Keep paragraph breaks so headings do not run into body text.
    xml = _DOCX_PARA.sub("\n", xml)
    return _clean(_DOCX_TAG.sub(" ", xml))


def sibling_markdown(path: Path) -> Path | None:
    """Some files already have an extracted .md alongside them - prefer it."""
    sib = path.with_suffix(".md")
    return sib if sib.exists() and sib != path else None


def extract(path: Path) -> tuple[str, str]:
    """Return (text, method). Empty text means 'classify on metadata alone'."""
    suffix = path.suffix.lower()

    if suffix in TEXT_SUFFIXES:
        return _from_text(path), "text"

    sib = sibling_markdown(path)
    if sib:
        text = _from_text(sib)
        if len(text) >= MIN_USEFUL_CHARS:
            return text, "sibling-md"

    if suffix in PDF_SUFFIXES:
        text = _from_pdf(path)
        return (text, "pdf") if len(text) >= MIN_USEFUL_CHARS else ("", "pdf-no-text")
    if suffix in DOCX_SUFFIXES:
        text = _from_docx(path)
        return (text, "docx") if len(text) >= MIN_USEFUL_CHARS else ("", "docx-no-text")
    if suffix in METADATA_ONLY:
        return "", "metadata-only"
    return "", "unsupported"


def describe(path: Path, repo_root: Path) -> dict:
    """Everything the classifier prompt needs about one file."""
    text, method = extract(path)
    try:
        rel = str(path.relative_to(repo_root)).replace("\\", "/")
    except ValueError:
        rel = str(path).replace("\\", "/")
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    siblings = []
    try:
        siblings = sorted(p.name for p in path.parent.iterdir()
                          if p.is_file() and p.name != path.name)[:8]
    except OSError:
        pass
    return {
        "path": rel,
        "name": path.name,
        "folder": path.parent.name,
        "size": size,
        "text": text,
        "method": method,
        "siblings": siblings,
    }
