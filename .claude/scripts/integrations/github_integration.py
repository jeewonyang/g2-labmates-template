"""GitHub integration: notifications, assigned issues, review requests.

Read-only. Auth: a CLASSIC personal access token (fine-grained PATs still
can't call the Notifications API) with `notifications` + `repo` scopes, in
.claude/data/secrets/github.env as GITHUB_TOKEN=ghp_...

Uses urllib (no extra deps). The notifications poller honors If-Modified-Since
so unchanged polls cost zero rate limit (heartbeat-friendly).
"""

import json
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared import DATA, STATE_DIR, atomic_write_json, read_json, with_retry  # noqa: E402

SECRETS_FILE = DATA / "secrets" / "github.env"
STATE_FILE = STATE_DIR / "github-state.json"
API = "https://api.github.com"


@dataclass
class Notification:
    id: str
    reason: str
    title: str
    repo: str
    type: str
    updated: str
    url: str


@dataclass
class WorkItem:
    number: int
    title: str
    repo: str
    is_pr: bool
    updated: str
    url: str


def _token() -> str:
    for line in SECRETS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("GITHUB_TOKEN=") and not line.startswith("#"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise KeyError(f"GITHUB_TOKEN not found in {SECRETS_FILE}")


def _get(path: str, params: dict | None = None, headers: dict | None = None):
    """GET api.github.com<path>. Returns (json_or_None, response_headers).
    None json means 304 Not Modified."""
    url = f"{API}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {_token()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "SecondBrain/1.0",
        **(headers or {})})

    def _call():
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode()), dict(resp.headers)
        except urllib.error.HTTPError as e:
            if e.code == 304:
                return None, dict(e.headers)
            raise
    return with_retry(_call, retries=2)


def _subject_url(subject: dict) -> str:
    api_url = subject.get("url") or ""
    return (api_url.replace("api.github.com/repos/", "github.com/")
                   .replace("/pulls/", "/pull/")) if api_url else ""


def notifications(participating: bool = True) -> list[Notification]:
    """Unread notifications. Uses If-Modified-Since: a 304 (nothing new) is
    free and returns the previously cached list."""
    state = read_json(STATE_FILE, {}) or {}
    headers = {}
    if state.get("last_modified"):
        headers["If-Modified-Since"] = state["last_modified"]
    data, resp_headers = _get("/notifications",
                              {"participating": str(participating).lower(),
                               "per_page": 50}, headers)
    if data is None:  # 304 - unchanged since last poll
        cached = state.get("cached", [])
        return [Notification(**n) for n in cached]
    out = [Notification(
        id=n.get("id", ""), reason=n.get("reason", ""),
        title=n.get("subject", {}).get("title", ""),
        repo=n.get("repository", {}).get("full_name", ""),
        type=n.get("subject", {}).get("type", ""),
        updated=n.get("updated_at", ""),
        url=_subject_url(n.get("subject", {}))) for n in data]
    atomic_write_json(STATE_FILE, {
        "last_modified": resp_headers.get("Last-Modified", ""),
        "cached": [vars(n) for n in out]})
    return out


def assigned_items(state: str = "open") -> list[WorkItem]:
    data, _ = _get("/issues", {"filter": "assigned", "state": state,
                               "per_page": 50})
    return [WorkItem(
        number=i.get("number", 0), title=i.get("title", ""),
        repo=(i.get("repository") or {}).get("full_name", ""),
        is_pr="pull_request" in i, updated=i.get("updated_at", ""),
        url=i.get("html_url", "")) for i in (data or [])]


def review_requests() -> list[WorkItem]:
    data, _ = _get("/search/issues",
                   {"q": "is:pr is:open review-requested:@me", "per_page": 30})
    items = (data or {}).get("items", [])
    return [WorkItem(
        number=i.get("number", 0), title=i.get("title", ""),
        repo="/".join(i.get("repository_url", "").rsplit("/", 2)[-2:]),
        is_pr=True, updated=i.get("updated_at", ""),
        url=i.get("html_url", "")) for i in items]


def format_notifications(items: list[Notification]) -> str:
    if not items:
        return "No unread GitHub notifications."
    lines = [f"{len(items)} GitHub notification(s):"]
    for n in items:
        lines.append(f"- [{n.reason}] {n.repo}: {n.title} ({n.type})")
    return "\n".join(lines)


def format_work_items(items: list[WorkItem]) -> str:
    if not items:
        return "Nothing assigned or awaiting review."
    lines = [f"{len(items)} item(s):"]
    for w in items:
        kind = "PR" if w.is_pr else "issue"
        lines.append(f"- {w.repo}#{w.number} ({kind}): {w.title}")
    return "\n".join(lines)


def is_configured() -> bool:
    return SECRETS_FILE.exists()
