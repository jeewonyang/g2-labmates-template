"""Hybrid search over the vault index: 0.7 vector + 0.3 keyword.

Usage:
  python .claude/scripts/memory_search.py "what did we decide about X"
  python .claude/scripts/memory_search.py "reply tone" --path-prefix Memory/drafts/sent
  python .claude/scripts/memory_search.py "sqlite" --k 5 --json

Scores are min-max normalized within each result set (best = 1.0), then
merged as 0.7 * vector_similarity + 0.3 * keyword_bm25. A result found by
only one method keeps only that component.
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import db  # noqa: E402
from embeddings import embed_query  # noqa: E402

VEC_WEIGHT, KW_WEIGHT = 0.7, 0.3
CANDIDATES = 40  # fetched per method before merging


def fts_query(raw: str) -> str:
    """Quote tokens and OR them - recall over precision for the merge stage."""
    tokens = re.findall(r"\w+", raw, flags=re.UNICODE)
    return " OR ".join(f'"{t}"' for t in tokens) if tokens else '""'


def normalize(scores: dict[int, float], higher_is_better: bool) -> dict[int, float]:
    if not scores:
        return {}
    values = list(scores.values())
    lo, hi = min(values), max(values)
    if hi == lo:
        return {k: 1.0 for k in scores}
    return {k: ((v - lo) / (hi - lo)) if higher_is_better
            else ((hi - v) / (hi - lo)) for k, v in scores.items()}


def search(query: str, k: int = 8, path_prefix: str | None = None) -> list[dict]:
    conn = db.connect()

    prefix_filter = ""
    params_suffix: tuple = ()
    if path_prefix:
        prefix_filter = " AND c.path LIKE ?"
        params_suffix = (path_prefix.replace("\\", "/").rstrip("/") + "%",)

    # Vector: KNN over the whole corpus, prefix filtered after the join.
    import sqlite_vec
    emb = sqlite_vec.serialize_float32(embed_query(query))
    vec_rows = conn.execute(
        f"""SELECT v.chunk_id, v.distance FROM chunks_vec v
            JOIN chunks c ON c.id = v.chunk_id
            WHERE v.embedding MATCH ? AND v.k = ?{prefix_filter}
            ORDER BY v.distance""",
        (emb, CANDIDATES * (10 if path_prefix else 1), *params_suffix),
    ).fetchall()[:CANDIDATES]
    vec_scores = normalize({cid: d for cid, d in vec_rows}, higher_is_better=False)

    # Keyword: BM25 (smaller is better in FTS5).
    kw_rows = conn.execute(
        f"""SELECT f.rowid, bm25(chunks_fts) FROM chunks_fts f
            JOIN chunks c ON c.id = f.rowid
            WHERE chunks_fts MATCH ?{prefix_filter}
            ORDER BY bm25(chunks_fts) LIMIT ?""",
        (fts_query(query), *params_suffix, CANDIDATES),
    ).fetchall()
    kw_scores = normalize({cid: s for cid, s in kw_rows}, higher_is_better=False)

    merged = {
        cid: VEC_WEIGHT * vec_scores.get(cid, 0.0) + KW_WEIGHT * kw_scores.get(cid, 0.0)
        for cid in set(vec_scores) | set(kw_scores)
    }
    top = sorted(merged.items(), key=lambda kv: -kv[1])[:k]

    results = []
    for cid, score in top:
        path, pos, text = conn.execute(
            "SELECT path, pos, text FROM chunks WHERE id = ?", (cid,)).fetchone()
        results.append({
            "score": round(score, 3),
            "path": path,
            "pos": pos,
            "text": text,
            "in_vector": cid in vec_scores,
            "in_keyword": cid in kw_scores,
        })
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Hybrid vault search")
    parser.add_argument("query")
    parser.add_argument("--k", type=int, default=8)
    parser.add_argument("--path-prefix", default=None,
                        help="restrict to paths under this VAULT-relative prefix")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(errors="replace")  # cp949 console safety
    except Exception:
        pass

    results = search(args.query, k=args.k, path_prefix=args.path_prefix)
    if args.as_json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0
    if not results:
        print("no results")
        return 0
    for i, r in enumerate(results, 1):
        snippet = " ".join(r["text"].split())[:220]
        tags = "".join(t for t, on in (("V", r["in_vector"]), ("K", r["in_keyword"])) if on)
        print(f"{i}. [{r['score']:.3f} {tags}] {r['path']} #{r['pos']}")
        print(f"   {snippet}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
