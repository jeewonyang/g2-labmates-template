"""Learn the owner's classification tendencies from their manual corrections.

Every time they decline or edit a triage decision - a destination revised in
/ops, a filing rejected, or an applied capture's dashboard entity corrected on
the Inbox - the correction is appended to a local JSONL log. Two consumers:

  1. The LOCAL classifier prompt (triage_classify, Ollama) gets aggregated
     tendencies plus recent concrete examples with titles. Titles never leave
     this machine: the classifier runs locally by construction.
  2. The CLOUD verifier prompt (triage_review) and the versioned memory file
     VAULT/Memory/TRIAGE_TENDENCIES.md get AGGREGATE COUNTS ONLY - transition
     patterns like "note -> task x5", never a title, path, or content. That is
     the same sanitization contract the review pipeline already promises.

Recording is best-effort everywhere it is hooked: a failure to record a lesson
must never block the ledger transition or the Prisma correction it describes.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared import REPO_ROOT, STATE_DIR, file_lock, log_line, now  # noqa: E402

STATE_FILE = STATE_DIR / "triage-corrections.jsonl"
MEMORY_FILE = REPO_ROOT / "VAULT" / "Memory" / "TRIAGE_TENDENCIES.md"

# The dimensions a correction can move along. `action_kind` is the one the owner
# flagged first: tasks being filed as notes.
FIELDS = ("vault", "bucket", "folder", "folder_mode", "action_kind")

MAX_PROMPT_EXAMPLES = 8
MAX_LOG_ROWS = 2000          # oldest rows beyond this are dropped on rewrite


def _first_action_kind(proposal: dict | None) -> str | None:
    for action in (proposal or {}).get("actions") or []:
        if isinstance(action, dict) and action.get("kind"):
            return str(action["kind"])
    return None


def snapshot(proposal: dict | None) -> dict:
    """Reduce a proposal to the comparable classification dimensions."""
    proposal = proposal or {}
    return {
        "vault": proposal.get("vault"),
        "bucket": proposal.get("bucket"),
        "folder": proposal.get("folder"),
        "folder_mode": proposal.get("folder_mode"),
        "action_kind": _first_action_kind(proposal),
    }


def _diffs(old: dict, new: dict) -> list[dict]:
    out = []
    for field in FIELDS:
        a, b = old.get(field), new.get(field)
        if a != b and not (a is None and b is None):
            out.append({"field": field, "from": a, "to": b})
    return out


def _load() -> list[dict]:
    rows: list[dict] = []
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except OSError:
        pass
    return rows


def _normalize(value: dict | None) -> dict:
    """Accept either a full proposal or an already-reduced snapshot."""
    value = value or {}
    if any(k in value for k in ("vault", "bucket", "actions", "folder_mode")):
        return snapshot(value)
    return {field: value.get(field) for field in FIELDS}


def record(source: str, *, title: str = "", old: dict | None = None,
           new: dict | None = None, by: str = "owner", job: str | None = None,
           note: str = "") -> dict | None:
    """Append one correction/decline. Returns the row, or None if a no-op."""
    old_snap = _normalize(old)
    new_snap = _normalize(new)
    declined = new is None
    diffs = [] if declined else _diffs(old_snap, new_snap)
    if not declined and not diffs:
        return None                       # they saved without changing anything
    row = {
        "ts": now().isoformat(timespec="seconds"),
        "source": source,
        "by": by,
        "job": job,
        "title": str(title or "")[:200],
        "old": old_snap,
        "new": None if declined else new_snap,
        "declined": declined,
        "diffs": diffs,
        "note": str(note or "")[:300],
    }
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(STATE_FILE):
        rows = _load()
        rows.append(row)
        if len(rows) > MAX_LOG_ROWS:
            rows = rows[-MAX_LOG_ROWS:]
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    try:
        refresh_memory(rows)
    except OSError as exc:
        log_line("triage", f"tendencies memory refresh failed: {exc!r}")
    return row


def record_from_revision(job: dict, new_proposal: dict, *,
                         by: str = "owner", note: str = "") -> dict | None:
    """Record a human /ops correction of a triage.classify proposal."""
    if (job or {}).get("kind") != "triage.classify":
        return None
    old = job.get("proposal") or {}
    payload = job.get("payload") or {}
    title = (old.get("title")
             or str(payload.get("path") or "").replace("\\", "/").rsplit("/", 1)[-1])
    return record("ops-correction", title=title, old=old, new=new_proposal,
                  by=by, job=job.get("job"), note=note)


def record_rejection(job: dict, *, by: str = "owner",
                     reason: str = "") -> dict | None:
    """Record a declined (rejected) triage.classify filing."""
    if (job or {}).get("kind") != "triage.classify":
        return None
    old = job.get("proposal") or {}
    payload = job.get("payload") or {}
    title = (old.get("title")
             or str(payload.get("path") or "").replace("\\", "/").rsplit("/", 1)[-1])
    return record("ops-decline", title=title, old=old, new=None,
                  by=by, job=job.get("job"), note=reason)


def aggregate(rows: list[dict] | None = None) -> Counter:
    """Count (field, from, to) transitions across all recorded corrections."""
    counts: Counter = Counter()
    for row in rows if rows is not None else _load():
        for diff in row.get("diffs") or []:
            key = (str(diff.get("field")),
                   str(diff.get("from")), str(diff.get("to")))
            counts[key] += 1
        if row.get("declined"):
            old = row.get("old") or {}
            counts[("declined", f"{old.get('vault')}/{old.get('bucket')}",
                    "left-in-inbox")] += 1
    return counts


def _aggregate_lines(counts: Counter, *, min_count: int = 1,
                     limit: int = 12) -> list[str]:
    lines = []
    for (field, src, dst), n in counts.most_common():
        if n < min_count or len(lines) >= limit:
            continue
        if field == "declined":
            lines.append(f"- declined {src} filings entirely: {n}x")
        else:
            lines.append(f"- corrected {field}: {src} -> {dst} ({n}x)")
    return lines


def prompt_block() -> str:
    """Local-classifier prompt section. May include titles (local model only)."""
    rows = _load()
    if not rows:
        return ""
    counts = aggregate(rows)
    lines = _aggregate_lines(counts)
    examples = []
    for row in rows[-MAX_PROMPT_EXAMPLES:][::-1]:
        title = row.get("title") or "(untitled)"
        if row.get("declined"):
            examples.append(f'- "{title}": they declined the proposed filing'
                            + (f" ({row['note']})" if row.get("note") else ""))
            continue
        moves = ", ".join(
            f"{d.get('field')} {d.get('from')} -> {d.get('to')}"
            for d in row.get("diffs") or [])
        if moves:
            examples.append(f'- "{title}": {moves}')
    if not lines and not examples:
        return ""
    parts = ["\nLEARNED FROM THE OWNER'S PAST CORRECTIONS",
             "They have manually corrected earlier classifications. Match their",
             "demonstrated preferences; when a pattern below applies, follow it."]
    if lines:
        parts.append("Recurring corrections:")
        parts.extend(f"  {line}" for line in lines)
    if examples:
        parts.append("Recent examples:")
        parts.extend(f"  {line}" for line in examples)
    return "\n".join(parts) + "\n"


def review_block() -> str:
    """Cloud-verifier prompt section. AGGREGATES ONLY - no titles or paths."""
    counts = aggregate()
    lines = _aggregate_lines(counts, min_count=2)
    if not lines:
        return ""
    return ("\nTHE OWNER'S RECORDED CORRECTION TENDENCIES (aggregate counts only)\n"
            "When a proposal repeats one of these patterns they have repeatedly\n"
            "corrected, prefer their demonstrated choice:\n"
            + "\n".join(lines) + "\n")


def refresh_memory(rows: list[dict] | None = None) -> None:
    """Write the versioned, cloud-safe tendencies summary into VAULT/Memory.

    Aggregate transition counts only. This file is git-versioned and loadable
    by cloud sessions, so it must never contain a capture title, source path,
    or content fragment.
    """
    if rows is None:
        rows = _load()
    counts = aggregate(rows)
    lines = _aggregate_lines(counts, limit=30)
    total = len(rows)
    body = [
        "# Triage tendencies (auto-generated)",
        "",
        "_Generated by `.claude/scripts/triage/lessons.py` from the owner's manual",
        "triage corrections. Aggregate patterns only - titles and paths stay in",
        "the local, gitignored log at `.claude/data/state/triage-corrections.jsonl`.",
        "Do not edit by hand; the next recorded correction overwrites this file._",
        "",
        f"Updated: {now():%Y-%m-%d %H:%M} · corrections recorded: {total}",
        "",
        "## Recurring patterns",
        "",
    ]
    body.extend(lines if lines else ["(none yet)"])
    body += [
        "",
        "## How G2 uses this",
        "",
        "- The local Ollama classifier prompt includes these patterns plus",
        "  recent concrete examples (local machine only).",
        "- The cloud verifier prompt includes only the aggregate patterns above.",
        "- A pattern seen 2+ times is treated as an explicit preference.",
        "",
    ]
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = MEMORY_FILE.with_suffix(".md.tmp")
    tmp.write_text("\n".join(body), encoding="utf-8")
    tmp.replace(MEMORY_FILE)
