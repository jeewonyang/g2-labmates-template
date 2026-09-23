"""Scientific Research producer.

Two streams, all gathered deterministically:

  new papers        -> research.lit_review     (one job per paper)
  active projects   -> research.project_pulse  (one job per project, with the
                                                file/commit/meeting evidence
                                                collected here, not by the model)

A third stream, new meeting notes -> research.next_actions, was retired on
2026-09-22: every job it produced was rejected, and admin.meeting_followup
already works each finished meeting. `_action_specs()` is kept (never-delete)
but no longer called, so its `meetings_processed` cursor simply stops moving.

Evidence collection lives here rather than in the prompt so the jobs need no
Bash: `git log` runs in this process, under the command guard, and the model
receives a list. An unattended agent that cannot shell out is a much smaller
attack surface.

State at .claude/data/state/producer-research.json tracks which meeting notes
have already been turned into action items and when each project was last
pulsed, so a daily run does not re-enqueue yesterday's work.
"""

import subprocess
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared import (MEMORY, REPO_ROOT, STATE_DIR, VAULT,  # noqa: E402
                    atomic_write_json, log_line, now, read_json)

TEAM = "research"

STATE_FILE = STATE_DIR / "producer-research.json"

PULSE_WINDOW_DAYS = 14
PULSE_MIN_INTERVAL_DAYS = 7      # do not re-pulse a project every single day
MAX_PAPERS = 8
MAX_NOTES = 5
MAX_NOTE_CHARS = 20_000

# Where a project's working files live. Research-Private is their real work and is
# forced onto ollama by the dispatcher's path-derived sensitivity guard - the
# producer does not need to (and must not) make that decision.
PROJECT_DIRS = [
    VAULT / "Research-Private" / "10_Projects",
    VAULT / "G2OS-Staging" / "10_Projects",
    MEMORY / "projects",
]
MEETINGS_DIR = MEMORY / "meetings"


def _state() -> dict:
    return read_json(STATE_FILE, {}) or {}


def _save(state: dict) -> None:
    atomic_write_json(STATE_FILE, state)


def active_projects() -> list[str]:
    """Project names from the portfolio table in ACTIVE_PROJECTS.md."""
    path = MEMORY / "ACTIVE_PROJECTS.md"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    names, in_table = [], False
    for line in text.splitlines():
        if line.startswith("| Priority"):
            in_table = True
            continue
        if in_table:
            if not line.startswith("|"):
                break
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) < 2 or set(cells[0]) <= set("-: "):
                continue
            name = cells[1].strip("`").strip()
            if name and name.lower() != "project":
                names.append(name)
    return names


def _recent_files(window_days: int) -> list[str]:
    cutoff = (now() - timedelta(days=window_days)).timestamp()
    out = []
    for base in PROJECT_DIRS:
        if not base.is_dir():
            continue
        for p in base.rglob("*.md"):
            try:
                if p.stat().st_mtime >= cutoff:
                    out.append(str(p.relative_to(REPO_ROOT)).replace("\\", "/"))
            except OSError:
                continue
    return sorted(out)


def _recent_commits(window_days: int) -> list[str]:
    try:
        res = subprocess.run(
            ["git", "log", f"--since={window_days}.days", "--oneline",
             "--no-merges", "-n", "60"],
            cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired) as e:
        log_line("producer", f"research: git log failed: {e!r}")
        return []
    if res.returncode != 0:
        return []
    return [ln for ln in (res.stdout or "").splitlines() if ln.strip()]


def _recent_meetings(window_days: int) -> list[Path]:
    cutoff = (now() - timedelta(days=window_days)).timestamp()
    if not MEETINGS_DIR.is_dir():
        return []
    out = []
    for p in MEETINGS_DIR.glob("*.md"):
        try:
            if p.stat().st_mtime >= cutoff:
                out.append(p)
        except OSError:
            continue
    return sorted(out, key=lambda p: p.stat().st_mtime, reverse=True)


def _match(name: str, haystack: list[str]) -> list[str]:
    """Loose name match - project names are prose, paths are slugs."""
    words = [w for w in name.lower().replace("-", " ").split() if len(w) > 3]
    if not words:
        return []
    return [h for h in haystack
            if any(w in h.lower().replace("-", " ") for w in words)]


def _paper_specs(state: dict) -> list[dict]:
    try:
        from integrations.papers_integration import new_papers
    except ImportError as e:
        log_line("producer", f"research: papers unavailable: {e!r}")
        return []
    try:
        papers = new_papers(max_total=MAX_PAPERS)
    except Exception as e:                  # network, throttle, parse
        log_line("producer", f"research: new_papers failed: {e!r}")
        return []

    specs = []
    for p in papers[:MAX_PAPERS]:
        specs.append({
            "kind": "research.lit_review",
            "runtime": "claude",
            "sensitivity": "internal",      # public arXiv abstract
            "payload": {
                "paper_id": p.arxiv_id,
                "arxiv_id": p.arxiv_id if p.source == "arxiv" else "",
                "title": p.title,
                "authors": p.authors,
                "summary": p.summary,
                "url": p.url,
                "source": p.source,
                "journal": p.journal,
                "matched_queries": p.query,
            },
        })
    return specs


def _pulse_specs(state: dict) -> list[dict]:
    pulsed = state.get("last_pulse", {})
    today = f"{now():%Y-%m-%d}"
    cutoff = (now() - timedelta(days=PULSE_MIN_INTERVAL_DAYS)).strftime("%Y-%m-%d")

    files = _recent_files(PULSE_WINDOW_DAYS)
    commits = _recent_commits(PULSE_WINDOW_DAYS)
    meetings = [str(m.relative_to(REPO_ROOT)).replace("\\", "/")
                for m in _recent_meetings(PULSE_WINDOW_DAYS)]

    specs = []
    for name in active_projects():
        if pulsed.get(name, "") > cutoff:
            continue                        # pulsed recently enough
        specs.append({
            "kind": "research.project_pulse",
            "runtime": "claude",
            "sensitivity": "internal",
            "payload": {
                "project": name,
                "window_days": PULSE_WINDOW_DAYS,
                "recent_files": _match(name, files),
                "recent_commits": _match(name, commits),
                "recent_meetings": _match(name, meetings),
                "last_pulse": pulsed.get(name, ""),
            },
        })
        pulsed[name] = today
    state["last_pulse"] = pulsed
    return specs


def _action_specs(state: dict) -> list[dict]:
    seen = set(state.get("meetings_processed", []))
    specs = []
    for path in _recent_meetings(30)[:MAX_NOTES]:
        rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
        if rel in seen:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not text.strip():
            continue
        specs.append({
            "kind": "research.next_actions",
            "runtime": "claude",
            "sensitivity": "internal",
            "payload": {"path": rel, "text": text[:MAX_NOTE_CHARS],
                        "date": path.stem[:10]},
        })
        seen.add(rel)
    state["meetings_processed"] = sorted(seen)
    return specs


_PENDING: dict | None = None


def plan() -> list[dict]:
    global _PENDING
    state = _state()
    specs = _paper_specs(state) + _pulse_specs(state)
    # The cursors this run advanced are held, not written. producers.run()
    # calls commit() only after the jobs actually exist, so a crash between
    # plan() and enqueue re-produces the work instead of silently skipping it -
    # the same ordering heartbeat_produce.py uses for its snapshot.
    _PENDING = state
    return specs


def commit() -> None:
    """Persist the cursors advanced by the last plan(). Never called on a dry run."""
    global _PENDING
    if _PENDING is not None:
        _save(_PENDING)
        _PENDING = None
