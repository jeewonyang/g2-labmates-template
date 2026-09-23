"""Registry of available integrations and whether each is configured.

Adding an integration: create its module, then add an entry here. `query.py`
and (later) the heartbeat use this to know what's available and enabled.
"""

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integrations import google_auth  # noqa: E402

DATA = Path(__file__).resolve().parents[2] / "data"
SECRETS = DATA / "secrets"


@dataclass
class Integration:
    name: str
    description: str
    is_configured: Callable[[], bool]
    setup_hint: str


REGISTRY: dict[str, Integration] = {
    "gmail": Integration(
        "gmail", "Read email, create drafts (personal Google account)",
        google_auth.is_configured,
        "python .claude/scripts/setup_auth.py google"),
    "calendar": Integration(
        "calendar", "Upcoming events (personal Google account)",
        google_auth.is_configured,
        "python .claude/scripts/setup_auth.py google"),
    "drive": Integration(
        "drive", "List/read files (personal Google account)",
        google_auth.is_configured,
        "python .claude/scripts/setup_auth.py google"),
    "slack": Integration(
        "slack", "Read messages, detect items needing a reply (read-only)",
        lambda: (SECRETS / "slack.env").exists(),
        "add SLACK_USER_TOKEN (xoxp-) to .claude/data/secrets/slack.env (see docs)"),
    "github": Integration(
        "github", "Notifications, assigned issues, review requests",
        lambda: (SECRETS / "github.env").exists(),
        "add GITHUB_TOKEN (classic PAT) to .claude/data/secrets/github.env"),
    "papers": Integration(
        "papers", "New arXiv, bioRxiv, and high-impact journal matches for the watchlist",
        lambda: True,  # arXiv needs no auth
        "no auth required; watchlist keywords live in USER.md"),
}


def configured() -> list[str]:
    return [name for name, integ in REGISTRY.items() if integ.is_configured()]


def status() -> str:
    lines = ["Integrations:"]
    for name, integ in REGISTRY.items():
        mark = "OK " if integ.is_configured() else "-- "
        lines.append(f"  [{mark}] {name}: {integ.description}")
        if not integ.is_configured():
            lines.append(f"        setup: {integ.setup_hint}")
    return "\n".join(lines)
