"""Durable user feedback for reply drafts.

The dashboard calls this module instead of rewriting draft Markdown itself.
Edits and relationship confirmations are appended to a local JSONL history,
then injected into future draft prompts as user-confirmed examples. Dismissal
moves a draft to expired without deleting its content or feedback history.

CLI:
  python draft_feedback.py classify <filename> <group>
  python draft_feedback.py edit <filename> --reply-file <path>
  python draft_feedback.py dismiss <filename>
  python draft_feedback.py dismiss-all
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shared import (MEMORY, STATE_DIR, atomic_write_text, file_lock,  # noqa: E402
                    now)

ACTIVE = MEMORY / "drafts" / "active"
EXPIRED = MEMORY / "drafts" / "expired"
FEEDBACK = STATE_DIR / "draft-feedback.jsonl"
GROUPS = {"Mentor/PI", "Mentee", "Collaborator", "Colleague"}
# Seed relationship overrides - replace with your own key people (see USER.md)
CONFIRMED_ANCHORS = {
    "ada advisor": "Mentor/PI",
    "sam student": "Mentee",
}
SAFE_NAME = re.compile(r"^[\w.\- ]+\.md$")


def _timestamp() -> str:
    return now().isoformat(timespec="seconds")


def _safe_name(filename: str) -> str:
    if not SAFE_NAME.fullmatch(filename or ""):
        raise ValueError("invalid draft filename")
    return filename


def _field(raw: str, key: str) -> str:
    match = re.search(rf"^{re.escape(key)}:\s*(.*)$", raw, re.MULTILINE)
    return match.group(1).strip().strip("\"'") if match else ""


def _section(raw: str, heading: str) -> str:
    match = re.search(
        rf"##\s+{re.escape(heading)}\s*\r?\n([\s\S]*?)(?=\r?\n##\s|$)",
        raw,
        re.IGNORECASE,
    )
    return match.group(1).strip() if match else ""


def _frontmatter_value(value) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    if any(char in text for char in (":", "#", "\"", "'")):
        return json.dumps(text, ensure_ascii=False)
    return text


def _set_frontmatter(raw: str, changes: dict) -> str:
    match = re.match(r"^---\r?\n([\s\S]*?)\r?\n---\r?\n?", raw)
    if not match:
        raise ValueError("draft is missing frontmatter")
    lines = match.group(1).splitlines()
    remaining = dict(changes)
    updated = []
    for line in lines:
        key = line.split(":", 1)[0].strip() if ":" in line else ""
        if key in remaining:
            updated.append(f"{key}: {_frontmatter_value(remaining.pop(key))}")
        else:
            updated.append(line)
    for key, value in remaining.items():
        updated.append(f"{key}: {_frontmatter_value(value)}")
    return "---\n" + "\n".join(updated) + "\n---\n\n" + raw[match.end():]


def _set_reply(raw: str, reply: str) -> str:
    pattern = re.compile(
        r"(##\s+Draft Reply\s*\r?\n)([\s\S]*?)(?=\r?\n##\s|$)",
        re.IGNORECASE,
    )
    if not pattern.search(raw):
        raise ValueError("draft is missing its reply section")
    return pattern.sub(
        lambda match: f"{match.group(1)}\n{reply.strip()}\n",
        raw,
        count=1,
    )


def _append(event: dict) -> None:
    FEEDBACK.parent.mkdir(parents=True, exist_ok=True)
    row = {"ts": _timestamp(), **event}
    with file_lock(FEEDBACK):
        with open(FEEDBACK, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())


def events() -> list[dict]:
    try:
        rows = []
        for line in FEEDBACK.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
        return rows
    except OSError:
        return []


def confirmed_group(recipient: str) -> str | None:
    key = str(recipient or "").strip().casefold()
    for row in reversed(events()):
        if (
            row.get("event") == "relationship_confirmed"
            and str(row.get("recipient", "")).strip().casefold() == key
            and row.get("group") in GROUPS
        ):
            return row["group"]
    return CONFIRMED_ANCHORS.get(key)


def prompt_block(recipient: str) -> str:
    """Return compact user-confirmed guidance for one future draft."""
    group = confirmed_group(recipient)
    rows = events()
    relevant = []
    for row in reversed(rows):
        if row.get("event") != "reply_edited":
            continue
        same_person = (
            str(row.get("recipient", "")).strip().casefold()
            == str(recipient or "").strip().casefold()
        )
        same_group = bool(group and row.get("relationship_group") == group)
        if same_person or same_group:
            relevant.append(row)
        if len(relevant) >= 3:
            break
    if not group and not relevant:
        return ""

    lines = ["USER-CONFIRMED RELATIONSHIP AND TONE LESSONS"]
    if group:
        lines.append(
            f"- {recipient} is confirmed as {group}. Use this; do not re-infer it."
        )
    for row in reversed(relevant):
        before = str(row.get("original_reply", "")).strip()[:600]
        after = str(row.get("edited_reply", "")).strip()[:600]
        lines.extend([
            f"- For {row.get('recipient') or row.get('relationship_group')}, "
            "the owner edited:",
            f"  DRAFT: {before}",
            f"  THEIR VERSION: {after}",
            "  Match the choices in THEIR VERSION when the context is comparable.",
        ])
    return "\n".join(lines)


def classify(filename: str, group: str, *, by: str = "owner") -> dict:
    if group not in GROUPS:
        raise ValueError("invalid relationship group")
    path = ACTIVE / _safe_name(filename)
    with file_lock(path):
        raw = path.read_text(encoding="utf-8")
        recipient = _field(raw, "recipient")
        source_id = _field(raw, "source_id")
        old_group = _field(raw, "relationship_group")
        old_status = _field(raw, "relationship_status") or "inferred"
        updated = _set_frontmatter(
            raw,
            {
                "relationship_group": group,
                "relationship_status": "confirmed",
                "relationship_confirmed_by": by,
                "relationship_confirmed_at": _timestamp(),
            },
        )
        atomic_write_text(path, updated)
    # A category describes the person, not one message. Keep every other
    # currently active draft for the same recipient consistent with the
    # confirmation so the dashboard does not ask for the same approval twice.
    updated_drafts = 1
    for candidate in ACTIVE.glob("*.md"):
        if candidate == path:
            continue
        try:
            candidate_raw = candidate.read_text(encoding="utf-8")
        except OSError:
            continue
        if _field(candidate_raw, "recipient").strip().casefold() != recipient.strip().casefold():
            continue
        with file_lock(candidate):
            candidate_raw = candidate.read_text(encoding="utf-8")
            if (
                _field(candidate_raw, "recipient").strip().casefold()
                != recipient.strip().casefold()
            ):
                continue
            candidate_updated = _set_frontmatter(
                candidate_raw,
                {
                    "relationship_group": group,
                    "relationship_status": "confirmed",
                    "relationship_confirmed_by": by,
                    "relationship_confirmed_at": _timestamp(),
                },
            )
            atomic_write_text(candidate, candidate_updated)
            updated_drafts += 1
    _append({
        "event": "relationship_confirmed",
        "recipient": recipient,
        "source_id": source_id,
        "old_group": old_group,
        "group": group,
        "was_inferred": old_status != "confirmed",
        "by": by,
    })
    return {
        "ok": True,
        "group": group,
        "status": "confirmed",
        "updated_drafts": updated_drafts,
    }


def edit(filename: str, reply: str, *, by: str = "owner") -> dict:
    clean = str(reply or "").strip()
    if not clean or len(clean) > 20_000:
        raise ValueError("reply must contain 1-20,000 characters")
    path = ACTIVE / _safe_name(filename)
    with file_lock(path):
        raw = path.read_text(encoding="utf-8")
        original = _section(raw, "Draft Reply")
        if original == clean:
            return {"ok": True, "changed": False}
        recipient = _field(raw, "recipient")
        source_id = _field(raw, "source_id")
        group = (
            _field(raw, "relationship_group")
            or confirmed_group(recipient)
            or "Collaborator"
        )
        updated = _set_reply(raw, clean)
        updated = _set_frontmatter(
            updated,
            {
                "reply_edited": "true",
                "reply_edited_by": by,
                "reply_edited_at": _timestamp(),
            },
        )
        atomic_write_text(path, updated)
    _append({
        "event": "reply_edited",
        "recipient": recipient,
        "source_id": source_id,
        "relationship_group": group,
        "original_reply": original[:20_000],
        "edited_reply": clean,
        "by": by,
    })
    return {"ok": True, "changed": True, "learned": True}


def dismiss(filename: str, *, by: str = "owner") -> dict:
    source = ACTIVE / _safe_name(filename)
    EXPIRED.mkdir(parents=True, exist_ok=True)
    with file_lock(source):
        raw = source.read_text(encoding="utf-8")
        updated = _set_frontmatter(
            raw,
            {
                "status": "expired",
                "dismissed_by": by,
                "dismissed_at": _timestamp(),
            },
        )
        target = EXPIRED / source.name
        if target.exists():
            suffix = now().strftime("%Y%m%d-%H%M%S")
            target = EXPIRED / f"{source.stem}__dismissed-{suffix}{source.suffix}"
        atomic_write_text(source, updated)
        source.replace(target)
    _append({
        "event": "draft_dismissed",
        "recipient": _field(raw, "recipient"),
        "source_id": _field(raw, "source_id"),
        "filename": source.name,
        "archived_as": target.name,
        "by": by,
    })
    return {"ok": True, "moved": "expired", "filename": target.name}


def dismiss_all(*, by: str = "owner") -> dict:
    """Archive every active draft, preserving each file and feedback event."""
    archived = []
    failed = []
    for path in sorted(ACTIVE.glob("*.md")):
        try:
            result = dismiss(path.name, by=by)
            archived.append(result["filename"])
        except (OSError, ValueError) as exc:
            failed.append({"filename": path.name, "error": str(exc)[:500]})
    return {
        "ok": not failed,
        "archived": len(archived),
        "filenames": archived,
        "failed": failed,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    classify_parser = sub.add_parser("classify")
    classify_parser.add_argument("filename")
    classify_parser.add_argument("group", choices=sorted(GROUPS))
    edit_parser = sub.add_parser("edit")
    edit_parser.add_argument("filename")
    edit_parser.add_argument("--reply-file", required=True)
    dismiss_parser = sub.add_parser("dismiss")
    dismiss_parser.add_argument("filename")
    sub.add_parser("dismiss-all")
    args = parser.parse_args()

    try:
        if args.action == "classify":
            result = classify(args.filename, args.group)
        elif args.action == "edit":
            result = edit(
                args.filename,
                Path(args.reply_file).read_text(encoding="utf-8"),
            )
        elif args.action == "dismiss":
            result = dismiss(args.filename)
        else:
            result = dismiss_all()
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok", True) else 2


if __name__ == "__main__":
    raise SystemExit(main())
