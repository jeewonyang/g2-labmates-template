"""What a Claude Code session did, read deterministically from its transcript.

Used by the lab notebook (the owner, 2026-09-22: every computational entry
records the AI model used and a summarized prompt) in two places:

- `lab_notebook.py session` - the `lab-notebook` skill reads its own session's
  id and model(s) here instead of stating them from memory;
- `notebook_session.py` - the SessionEnd auto-logger decides from this digest
  whether a session was project work at all, before any model is called.

Only the transcript is read. Tool *results* (file contents, command output) are
never part of the digest - only what they typed, what the assistant wrote, and
the paths and commands of each tool call - so the digest carries nothing a
session did not already send, and no file content rides along.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

TRANSCRIPTS = Path.home() / ".claude" / "projects"
PATH_KEYS = ("file_path", "path", "notebook_path")
READ_TOOLS = {"Read", "Glob", "Grep", "NotebookRead"}
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
SHELL_TOOLS = {"Bash", "PowerShell"}
# Wrappers the harness puts inside user turns; not what they typed.
NOISE = re.compile(r"<(system-reminder|local-command-[a-z]+|command-[a-z]+|"
                   r"task-notification|persisted-output)>.*?</\1>", re.S)


def transcript_dir(cwd: str | Path) -> Path:
    """Claude Code files a session under its cwd with every non-alphanumeric
    character turned into '-': C:\\Users\\x\\G2 -> C--Users-x-G2."""
    return TRANSCRIPTS / re.sub(r"[^A-Za-z0-9]", "-", str(cwd))


def latest_transcript(cwd: str | Path) -> Path | None:
    """The session writing right now is the newest transcript for its cwd."""
    try:
        files = sorted(transcript_dir(cwd).glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    except OSError:
        return None
    return files[-1] if files else None


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content
                         if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _clean(text: str) -> str:
    return NOISE.sub("", text or "").strip()


def digest(path: str | Path, *, max_prompt: int = 2_000, max_text: int = 1_500) -> dict:
    """The session as data: ids, models, prompts, assistant prose, tool calls.

    Unreadable lines are skipped; a missing file gives an empty digest with
    `error`, never an exception, because a hook calls this at shutdown.
    """
    out = {"session_id": "", "cwd": "", "models": [], "started": "", "ended": "",
           "prompts": [], "assistant": [], "turns": [], "tools": [], "read_paths": [],
           "written_paths": [], "commands": [], "transcript": str(path)}
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        out["error"] = f"transcript unreadable: {exc}"
        return out
    for line in lines:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        out["session_id"] = out["session_id"] or obj.get("sessionId", "")
        if obj.get("cwd") and not out["cwd"]:
            out["cwd"] = obj["cwd"]
        stamp = obj.get("timestamp") or ""
        if stamp:
            out["started"] = out["started"] or stamp
            out["ended"] = stamp
        msg = obj.get("message") or {}
        role = msg.get("role")
        content = msg.get("content")
        if obj.get("type") == "user" and role == "user" and not obj.get("isMeta") \
                and not obj.get("isSidechain"):
            text = _clean(_text_of(content))
            if text:
                out["prompts"].append(text[:max_prompt])
                out["turns"].append(("USER", text[:max_prompt]))
            continue
        if role != "assistant":
            continue
        model = msg.get("model") or ""
        if model and not model.startswith("<") and model not in out["models"]:
            out["models"].append(model)
        text = _clean(_text_of(content))
        if text and not obj.get("isSidechain"):
            out["assistant"].append(text[:max_text])
            out["turns"].append(("ASSISTANT", text[:max_text]))
        for block in content if isinstance(content, list) else []:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            name = block.get("name", "")
            args = block.get("input") or {}
            call = {"tool": name}
            target = next((str(args[k]) for k in PATH_KEYS if args.get(k)), "")
            if target:
                call["path"] = target
                bucket = out["written_paths"] if name in WRITE_TOOLS else out["read_paths"]
                if name in WRITE_TOOLS | READ_TOOLS and target not in bucket:
                    bucket.append(target)
            if name in SHELL_TOOLS and args.get("command"):
                call["command"] = str(args["command"])[:600]
                out["commands"].append(call["command"])
            out["tools"].append(call)
    return out


def wrote_notebook_entry(d: dict) -> bool:
    """She (or the skill) already filed this session: a `lab_notebook.py write`."""
    return any("lab_notebook.py" in c and re.search(r"\bwrite\b", c) for c in d["commands"])


def conversation(d: dict, *, limit: int = 30_000) -> str:
    """Their prompts and the assistant's prose in the order they happened - the
    model's material for the entry. Trimmed from the front, since the end of a
    session holds its results; their first prompt is always kept."""
    text = "\n\n".join(f"{role}: {body}" for role, body in d["turns"])
    if len(text) <= limit:
        return text
    first = f"USER: {d['prompts'][0]}\n\n[...]\n\n" if d["prompts"] else ""
    return first + text[-(limit - len(first)):]
