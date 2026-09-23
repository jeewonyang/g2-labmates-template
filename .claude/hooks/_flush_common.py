"""Shared logic for the PreCompact and SessionEnd flush hooks.

Reads the hook payload from stdin, extracts recent conversation text from the
transcript, writes it to a temp file, and spawns memory_flush.py detached so
the hook returns immediately (hooks must not block the session).
"""

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from shared import (REPO_ROOT, TMP_DIR, ensure_dirs, invoked_by,  # noqa: E402
                    log_line, now)

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
MAX_MESSAGES = 80
MAX_CHARS = 30_000


def find_latest_transcript() -> Path | None:
    """Locate this project's most recently modified session transcript.

    Fallback for when the hook payload doesn't arrive on stdin (piped stdin
    into Windows Store Python is unreliable under some shells). The session
    that just ended/compacted is the most recently written JSONL in Claude's
    per-project transcript directory.
    """
    munged = str(REPO_ROOT).replace(":", "-").replace("\\", "-") \
                           .replace("/", "-").replace(" ", "-")
    project_dir = Path.home() / ".claude" / "projects" / munged
    try:
        transcripts = sorted(project_dir.glob("*.jsonl"),
                             key=lambda p: p.stat().st_mtime)
    except OSError:
        return None
    return transcripts[-1] if transcripts else None


def extract_conversation(transcript_path: str) -> str:
    """Pull recent user/assistant text out of the transcript JSONL."""
    lines = []
    try:
        raw = Path(transcript_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    for line in raw.splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = obj.get("message") or {}
        role = msg.get("role")
        if role not in ("user", "assistant"):
            continue
        content = msg.get("content")
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = "\n".join(
                b.get("text", "") for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            )
        else:
            continue
        text = text.strip()
        if text:
            lines.append(f"{role.upper()}: {text}")
    convo = "\n\n".join(lines[-MAX_MESSAGES:])
    return convo[-MAX_CHARS:]


def run_flush_hook(event_name: str) -> int:
    who = invoked_by()
    if who:
        log_line("hooks", f"{event_name}: skipped (CLAUDE_INVOKED_BY={who})")
        return 0

    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        payload = {}
    session_id = payload.get("session_id", "")
    transcript_path = payload.get("transcript_path", "")

    if not transcript_path or not Path(transcript_path).exists():
        latest = find_latest_transcript()
        if latest:
            transcript_path = str(latest)
            session_id = session_id or latest.stem
            log_line("hooks", f"{event_name}: stdin payload unusable, "
                              f"using latest transcript {latest.name}")
    session_id = session_id or "unknown"

    convo = extract_conversation(transcript_path) if transcript_path else ""
    if not convo:
        log_line("hooks", f"{event_name}: nothing to flush (session {session_id})")
        return 0

    ensure_dirs()
    ctx_file = TMP_DIR / f"flush-{session_id}-{now():%H%M%S}.txt"
    ctx_file.write_text(convo, encoding="utf-8")

    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = (subprocess.DETACHED_PROCESS
                                   | subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(
        [sys.executable, str(SCRIPTS / "memory_flush.py"), str(ctx_file), session_id],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        **kwargs,
    )
    log_line("hooks", f"{event_name}: spawned flush for session {session_id} "
                      f"({len(convo)} chars)")
    return 0
