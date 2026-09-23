"""Index vault text into the hybrid search database (incremental).

Scope: all *.md / *.txt under VAULT/ except Finance/, junk dirs, and the
generated index.md map files (navigation noise, not knowledge). Chunks of
~1600 chars (~400 tokens) with overlap, embedded locally via FastEmbed,
stored in SQLite (sqlite-vec + FTS5).

Incremental by default: only new/changed files are re-embedded, deleted
files are pruned. Paths are stored relative to VAULT/ with forward slashes
(e.g. "Memory/drafts/sent/..." for --path-prefix filtering).

Usage:
  python .claude/scripts/memory_index.py            # incremental update
  python .claude/scripts/memory_index.py --rebuild  # from scratch
  python .claude/scripts/memory_index.py --stats    # show index stats
"""

import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import db  # noqa: E402
from embeddings import embed_texts  # noqa: E402
from shared import REPO_ROOT  # noqa: E402

VAULT = REPO_ROOT / "VAULT"
if os.name == "nt":
    VAULT = Path("\\\\?\\" + str(VAULT))

# Top-level vault folders never indexed.
#   Finance      - hard rule, off-limits everywhere.
#   Confidential - sensitive personal records (e.g. immigration or medical
#                  material), legal papers, and third-party records. Embeddings are local,
#                  but *search results* enter an agent's context and that agent
#                  may be a cloud model, so keep this content out of the index
#                  entirely rather than relying on the caller to be careful.
# Research-Private IS indexed: it is the owner's core work and they discuss it
# interactively. Its `private` sensitivity governs *bulk automated* routing
# (see .agent/plans/agent-os/taxonomy.md), not their own searches.
EXCLUDED_TOP = {"Finance", "Confidential"}
# Unsorted intake, excluded at the second level (e.g. G2OS-Staging/00_Inbox).
# 00_Inbox is raw dumps from Drive/Dropbox/SSD that have not been triaged yet,
# and it routinely mixes in sensitive personal records (e.g. immigration or
# medical material) that a search would surface. Since search results enter an
# agent's context, unsorted content stays out of the index until Phase 4 triage
# files it, at which point it gets indexed under its proper destination.
EXCLUDED_SUBDIRS = {"00_Inbox"}
JUNK_DIRS = {".git", ".ipynb_checkpoints", "__pycache__", "node_modules",
             ".venv", "venv", ".obsidian", "$RECYCLE.BIN"}
# Vendored third-party code (Arduino libs, packages) - not the owner's knowledge.
VENDORED_DIRS = {"libraries", "site-packages", "dist-packages", "vendor",
                 "third_party", "bower_components"}
# Machine-generated analysis output (sequencing dumps etc.) - data, not knowledge.
JUNK_DIR_SUFFIXES = ("_results", "_per_base_data")
TEXT_EXTENSIONS = {".md", ".txt"}
SKIP_NAMES = {"index.md"}  # generated map files
# Never index credential/secret files (defence in depth alongside block-secrets).
SECRET_NAME_RE = re.compile(
    r"(recovery.?code|password|secret|credential|\.env|token|api.?key|private.?key)",
    re.IGNORECASE)
MAX_FILE_BYTES = 2_000_000
MIN_FILE_BYTES = 40  # empty/near-empty files carry no knowledge
CHUNK_CHARS = 1_600
OVERLAP_CHARS = 200
EMBED_BATCH = 128


def is_data_dump(text: str) -> bool:
    """True if the text is mostly numbers/whitespace (a data table, not prose)."""
    sample = text[:4000]
    if not sample.strip():
        return True
    numeric = sum(c.isdigit() or c in ".\t ,-+eE\n" for c in sample)
    return numeric / len(sample) > 0.7


def iter_text_files():
    for dirpath, dirnames, filenames in os.walk(VAULT):
        rel_parts = Path(dirpath).relative_to(VAULT).parts
        if rel_parts and rel_parts[0] in EXCLUDED_TOP:
            dirnames.clear()
            continue
        if len(rel_parts) >= 2 and rel_parts[1] in EXCLUDED_SUBDIRS:
            dirnames.clear()
            continue
        dirnames[:] = [d for d in dirnames if d not in JUNK_DIRS
                       and d not in VENDORED_DIRS
                       and not d.endswith(JUNK_DIR_SUFFIXES)]
        for fn in filenames:
            if fn in SKIP_NAMES:
                continue
            if fn.startswith("._"):  # macOS AppleDouble resource forks (binary junk)
                continue
            if SECRET_NAME_RE.search(fn):
                continue
            p = Path(dirpath) / fn
            if p.suffix.lower() in TEXT_EXTENSIONS:
                yield p


def rel_path(p: Path) -> str:
    return str(p.relative_to(VAULT)).replace("\\", "/")


def chunk_text(text: str) -> list[str]:
    """Greedy paragraph packing into ~CHUNK_CHARS windows with overlap."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks, current = [], ""
    for para in paragraphs:
        # hard-split single paragraphs that exceed the window
        while len(para) > CHUNK_CHARS:
            head, para = para[:CHUNK_CHARS], para[CHUNK_CHARS - OVERLAP_CHARS:]
            if current:
                chunks.append(current)
                current = ""
            chunks.append(head)
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) > CHUNK_CHARS and current:
            chunks.append(current)
            current = current[-OVERLAP_CHARS:] + "\n\n" + para
        else:
            current = candidate
    if current.strip():
        chunks.append(current)
    return [c for c in chunks if len(c.strip()) >= 40]  # drop trivial fragments


def show_stats(conn) -> None:
    files = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    size_mb = db.DB_PATH.stat().st_size / 1e6 if db.DB_PATH.exists() else 0
    print(f"indexed files: {files:,} | chunks: {chunks:,} | db: {size_mb:.1f} MB")
    for prefix, n in conn.execute(
        "SELECT substr(path, 1, instr(path || '/', '/') - 1), COUNT(*) "
        "FROM chunks GROUP BY 1 ORDER BY 2 DESC"):
        print(f"  {prefix or '(root)'}: {n:,} chunks")


def main() -> int:
    started = time.time()
    conn = db.connect()
    if "--rebuild" in sys.argv:
        db.drop_all(conn)
    db.init_schema(conn)
    if "--stats" in sys.argv:
        show_stats(conn)
        return 0

    known = {path: (mtime, size) for path, mtime, size in
             conn.execute("SELECT path, mtime, size FROM files")}
    seen, added, updated, skipped, failed = set(), 0, 0, 0, 0

    for p in iter_text_files():
        try:
            st = p.stat()
        except OSError:
            failed += 1
            continue
        if st.st_size < MIN_FILE_BYTES:
            continue  # empty/near-empty: not tracked, pruned below if seen before
        rel = rel_path(p)
        seen.add(rel)
        if rel in known and known[rel] == (st.st_mtime, st.st_size):
            skipped += 1
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            failed += 1
            continue
        if len(text.encode("utf-8", "replace")) > MAX_FILE_BYTES:
            skipped += 1
            continue
        if is_data_dump(text):
            db.remove_file(conn, rel)  # prune if it was indexed before
            conn.execute("INSERT OR REPLACE INTO files(path, mtime, size, chunk_count) "
                         "VALUES (?, ?, ?, 0)", (rel, st.st_mtime, st.st_size))
            conn.commit()
            skipped += 1
            continue
        chunks = chunk_text(text)
        db.remove_file(conn, rel)
        if chunks:
            embeddings = []
            for i in range(0, len(chunks), EMBED_BATCH):
                embeddings.extend(embed_texts(chunks[i:i + EMBED_BATCH]))
            db.insert_chunks(conn, rel, chunks, embeddings)
        conn.execute(
            "INSERT INTO files(path, mtime, size, chunk_count) VALUES (?, ?, ?, ?)",
            (rel, st.st_mtime, st.st_size, len(chunks)))
        conn.commit()
        if rel in known:
            updated += 1
        else:
            added += 1

    removed = 0
    for gone in set(known) - seen:
        db.remove_file(conn, gone)
        removed += 1
    conn.commit()

    print(f"indexed in {time.time() - started:,.0f}s: "
          f"{added} added, {updated} updated, {removed} removed, "
          f"{skipped} unchanged/skipped, {failed} unreadable")
    show_stats(conn)
    return 0


if __name__ == "__main__":
    sys.exit(main())
