"""Draft lifecycle management (Advisor mode, task #1).

Folders under VAULT/Memory/drafts/:
- active/  : drafts awaiting the owner's action (heartbeat agent writes here)
- sent/    : they replied on the platform; file holds their ACTUAL reply text
             (the voice-matching corpus for future drafts)
- expired/ : >24h old with no action

Deterministic pieces live here (expiry sweep, email sent-detection). Draft
GENERATION is done by the heartbeat agent, which writes the files itself.

Draft file format: YYYY-MM-DD_<type>_<slug>.md with YAML frontmatter
(type, source_id, recipient, subject, context, created, status) +
"## Original Message" + "## Draft Reply" sections.
"""

import re
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shared import MEMORY, TIMEZONE, log_line, now  # noqa: E402

DRAFTS = MEMORY / "drafts"
ACTIVE, SENT, EXPIRED = DRAFTS / "active", DRAFTS / "sent", DRAFTS / "expired"
EXPIRY_HOURS = 24


def ensure_dirs() -> None:
    for d in (ACTIVE, SENT, EXPIRED):
        d.mkdir(parents=True, exist_ok=True)


def parse_frontmatter(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    m = re.match(r"---\n(.*?)\n---", text, re.S)
    if not m:
        return {}
    fm = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip().strip('"').strip("'")
    return fm


def _created_at(fm: dict, path: Path) -> datetime:
    raw = fm.get("created", "")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw[:16], fmt).replace(tzinfo=TIMEZONE)
        except ValueError:
            continue
    return datetime.fromtimestamp(path.stat().st_mtime, TIMEZONE)


def expire_old() -> list[str]:
    """Move active drafts older than EXPIRY_HOURS to expired/."""
    ensure_dirs()
    moved = []
    cutoff = now() - timedelta(hours=EXPIRY_HOURS)
    for f in ACTIVE.glob("*.md"):
        if _created_at(parse_frontmatter(f), f) < cutoff:
            shutil.move(str(f), str(EXPIRED / f.name))
            moved.append(f.name)
    if moved:
        log_line("heartbeat", f"drafts: expired {len(moved)}: {', '.join(moved)}")
    return moved


def detect_sent() -> list[str]:
    """Email drafts where the owner has since replied on the thread: capture their
    actual reply and move the draft to sent/. (Slack detection: future work.)"""
    ensure_dirs()
    moved = []
    email_drafts = [(f, parse_frontmatter(f)) for f in ACTIVE.glob("*.md")]
    email_drafts = [(f, fm) for f, fm in email_drafts if fm.get("type") == "email"
                    and fm.get("thread_id")]
    if not email_drafts:
        return moved
    from integrations import gmail_integration as gm
    from integrations.google_auth import build_service
    svc = build_service("gmail", "v1")
    for f, fm in email_drafts:
        try:
            thread = svc.users().threads().get(
                userId="me", id=fm["thread_id"], format="metadata",
                metadataHeaders=["From"]).execute()
            created = _created_at(fm, f)
            my_reply_id = None
            for msg in thread.get("messages", []):
                if "SENT" in msg.get("labelIds", []) and \
                        int(msg.get("internalDate", 0)) / 1000 > created.timestamp():
                    my_reply_id = msg["id"]
            if not my_reply_id:
                continue
            reply_text = gm.get_message_body(my_reply_id)[:4000]
            content = f.read_text(encoding="utf-8", errors="replace")
            content += (f"\n\n## Actual Reply (sent by the owner)\n\n{reply_text}\n")
            content = content.replace("status: active", "status: sent")
            (SENT / f.name).write_text(content, encoding="utf-8")
            f.unlink()
            moved.append(f.name)
        except Exception as e:
            log_line("heartbeat", f"drafts: sent-detection failed for {f.name}: {e!r}")
    if moved:
        log_line("heartbeat", f"drafts: moved to sent/: {', '.join(moved)}")
    return moved


def active_summary() -> str:
    ensure_dirs()
    files = sorted(ACTIVE.glob("*.md"))
    if not files:
        return "No active drafts."
    lines = [f"{len(files)} active draft(s):"]
    for f in files:
        fm = parse_frontmatter(f)
        lines.append(f"- {f.name} (to: {fm.get('recipient', '?')}, "
                     f"re: {fm.get('subject', '?')}, created {fm.get('created', '?')})")
    return "\n".join(lines)


if __name__ == "__main__":
    print("expired:", expire_old())
    print("sent:", detect_sent())
    print(active_summary())
