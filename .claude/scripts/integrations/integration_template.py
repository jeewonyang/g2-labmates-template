"""TEMPLATE for a new integration. Copy to <platform>_integration.py and fill in.

Pattern (mirrors gmail/calendar/drive):
1. Dataclass data model
2. Auth (reuse google_auth, or read a token from .claude/data/secrets/<x>.env)
3. Query functions -> list[dataclass], each wrapped in with_retry()
4. format_context() -> LLM-ready text
5. Register in registry.py, add a subcommand in query.py

Rules:
- The LLM never sees tokens. Auth stays in Python; pass only data.
- Advisor mode: read/draft only. Do NOT write send/post/delete functions.
- Sanitize external text before it reaches an LLM (Phase 8 sanitize.py).
"""

import os
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared import DATA, with_retry  # noqa: E402

SECRETS = DATA / "secrets"


def load_token(filename: str, var: str) -> str:
    """Read KEY=VALUE secrets from .claude/data/secrets/<filename>."""
    path = SECRETS / filename
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith(f"{var}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise KeyError(f"{var} not found in {path}")


@dataclass
class ExampleItem:
    id: str
    title: str


def fetch_items(limit: int = 20) -> list[ExampleItem]:
    _token = load_token("example.env", "EXAMPLE_TOKEN")  # noqa: F841
    def _call():
        raise NotImplementedError("call the platform API here")
    data = with_retry(_call)
    return [ExampleItem(id=d["id"], title=d["title"]) for d in data]


def format_context(items: list[ExampleItem]) -> str:
    if not items:
        return "Nothing new."
    return "\n".join(f"- {i.title}" for i in items)
