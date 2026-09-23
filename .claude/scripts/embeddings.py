"""Local embeddings for vault search.

Primary backend: **bge-m3 via Ollama** (1024-dim, multilingual). Migrated
2026-07-25 from FastEmbed all-MiniLM-L6-v2 (384-dim, English-only), which could
not represent the substantial Korean-language content in the vault and archive.

Fallback: FastEmbed all-MiniLM-L6-v2, used only if Ollama is unreachable. The
fallback has a *different dimension*, so the index must be rebuilt when the
backend changes - `db.py` derives its vec0 schema from DIM, and a dimension
mismatch against an existing table raises at insert time. `memory_index.py
--rebuild` drops and recreates the table, which is the supported path.

Both backends are local: no API, no cost, nothing leaves the machine. That
matters - this indexes Research-Private and personal content.
"""

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"
# Must be set before fastembed is imported (fallback path only).
os.environ.setdefault("FASTEMBED_CACHE_PATH", str(DATA / "models"))

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("SECONDBRAIN_EMBED_MODEL", "bge-m3")
OLLAMA_DIM = 1024
OLLAMA_TIMEOUT = int(os.environ.get("SECONDBRAIN_EMBED_TIMEOUT", "300"))

FALLBACK_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
FALLBACK_DIM = 384

_backend = None  # "ollama" | "fastembed"
_fastembed_model = None


def _ollama_available() -> bool:
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=5) as r:
            tags = json.load(r)
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError):
        return False
    names = {m.get("name", "").split(":")[0] for m in tags.get("models", [])}
    return OLLAMA_MODEL.split(":")[0] in names


def backend() -> str:
    """Resolve the backend once per process."""
    global _backend
    if _backend is None:
        _backend = "ollama" if _ollama_available() else "fastembed"
    return _backend


def _resolve_dim() -> int:
    return OLLAMA_DIM if backend() == "ollama" else FALLBACK_DIM


def _get_fastembed():
    global _fastembed_model
    if _fastembed_model is None:
        from fastembed import TextEmbedding
        (DATA / "models").mkdir(parents=True, exist_ok=True)
        _fastembed_model = TextEmbedding(model_name=FALLBACK_MODEL)
    return _fastembed_model


def _embed_ollama(texts: list[str]) -> list[list[float]]:
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/embed",
        data=json.dumps({"model": OLLAMA_MODEL, "input": texts}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT) as r:
        payload = json.load(r)
    vectors = payload.get("embeddings")
    if not vectors or len(vectors) != len(texts):
        raise RuntimeError(
            f"ollama returned {len(vectors or [])} embeddings for {len(texts)} inputs"
        )
    return vectors


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Batch-embed documents. Returns DIM-dimensional float lists."""
    if not texts:
        return []
    if backend() == "ollama":
        return _embed_ollama(texts)
    return [e.tolist() for e in _get_fastembed().embed(texts)]


def embed_query(text: str) -> list[float]:
    return embed_texts([text])[0]


DIM = _resolve_dim()
