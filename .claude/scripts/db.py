"""SQLite access layer for memory search: sqlite-vec (vectors) + FTS5 (keywords).

Database lives at .claude/data/memory.db (gitignored). Schema:
- files:      indexed file registry (path, mtime, size) for incremental updates
- chunks:     chunk text + source path/position (rowid is the chunk id)
- chunks_vec: vec0 virtual table, 384-dim cosine embeddings, keyed by chunk id
- chunks_fts: FTS5 external-content table over chunks.text, rowid-linked
"""

import sqlite3
from pathlib import Path

from embeddings import DIM

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "memory.db"


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.enable_load_extension(True)
    import sqlite_vec
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(f"""
        CREATE TABLE IF NOT EXISTS files (
            path TEXT PRIMARY KEY,
            mtime REAL NOT NULL,
            size INTEGER NOT NULL,
            chunk_count INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT NOT NULL,
            pos INTEGER NOT NULL,
            text TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_chunks_path ON chunks(path);
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_vec USING vec0(
            chunk_id INTEGER PRIMARY KEY,
            embedding FLOAT[{DIM}] distance_metric=cosine
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
            text, content='chunks', content_rowid='id'
        );
    """)
    conn.commit()


def drop_all(conn: sqlite3.Connection) -> None:
    for table in ("chunks_fts", "chunks_vec", "chunks", "files"):
        conn.execute(f"DROP TABLE IF EXISTS {table}")
    conn.commit()


def remove_file(conn: sqlite3.Connection, path: str) -> None:
    """Delete a file's chunks from all three chunk stores + the registry."""
    ids = [r[0] for r in conn.execute(
        "SELECT id FROM chunks WHERE path = ?", (path,))]
    for chunk_id in ids:
        conn.execute(
            "INSERT INTO chunks_fts(chunks_fts, rowid, text) "
            "SELECT 'delete', id, text FROM chunks WHERE id = ?", (chunk_id,))
        conn.execute("DELETE FROM chunks_vec WHERE chunk_id = ?", (chunk_id,))
    conn.execute("DELETE FROM chunks WHERE path = ?", (path,))
    conn.execute("DELETE FROM files WHERE path = ?", (path,))


def insert_chunks(conn: sqlite3.Connection, path: str,
                  texts: list[str], embeddings: list[list[float]]) -> None:
    import sqlite_vec
    for pos, (text, emb) in enumerate(zip(texts, embeddings)):
        cur = conn.execute(
            "INSERT INTO chunks(path, pos, text) VALUES (?, ?, ?)",
            (path, pos, text))
        chunk_id = cur.lastrowid
        conn.execute(
            "INSERT INTO chunks_vec(chunk_id, embedding) VALUES (?, ?)",
            (chunk_id, sqlite_vec.serialize_float32(emb)))
        conn.execute(
            "INSERT INTO chunks_fts(rowid, text) VALUES (?, ?)",
            (chunk_id, text))
