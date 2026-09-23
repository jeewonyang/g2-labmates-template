"""Background memory flush: distill a conversation into daily-log bullets.

Spawned detached by the PreCompact/SessionEnd hooks with a context temp file.
Runs one no-tools Claude turn (via runtimes/claude_rt, which prefers the
subscription `claude` CLI over an API key) to decide which decisions, lessons,
facts, and open threads are worth keeping. Appends a bullet summary to today's
daily log, or writes nothing if the model answers FLUSH_OK.

Safety rails:
- CLAUDE_INVOKED_BY=memory_flush is set BEFORE the model call, so the
  SessionEnd hook fired by our own subprocess exits immediately
  (recursion prevention).
- Dedup: skips if the same session flushed < 60s ago (PreCompact followed by
  SessionEnd would otherwise double-log).
- All daily-log writes go through shared.file_lock().

Usage: python memory_flush.py <context_file> <session_id>
Test:  python memory_flush.py --test   (runs on a tiny built-in context)
"""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shared import (AGENT_MODEL, STATE_DIR, append_to_daily_log,  # noqa: E402
                    atomic_write_json, ensure_dirs, file_lock, load_env,
                    log_line, read_json)

# Must be set before any model call so child processes inherit it.
os.environ["CLAUDE_INVOKED_BY"] = "memory_flush"
load_env()

FLUSH_STATE = STATE_DIR / "flush-state.json"
DEDUP_WINDOW_S = 60

SYSTEM_PROMPT = """You are the memory-flush component of The Owner's Second Brain.
You receive the tail of a Claude Code conversation. Extract ONLY what is worth
remembering across sessions:
- decisions made (and why)
- lessons learned / mistakes to avoid
- new facts about the owner, their projects, or their tools
- unfinished threads that a future session must pick up

Output rules:
- If nothing is worth saving, output exactly: FLUSH_OK
- Otherwise output 1-8 markdown bullets, each self-contained and specific.
- No preamble, no headers, no commentary - just the bullets.
- Never include secrets, tokens, or file contents - describe, don't quote."""


def summarize(context: str) -> str:
    """One no-tools turn on the subscription CLI (see runtimes/claude_rt.py).

    A flush fires on every SessionEnd, so this was the most frequent API-key
    caller in the system despite being the smallest call.
    """
    from runtimes import failover

    # No tools and a strict output contract, on either path: failover.run_text
    # replaces the assistant persona rather than layering on it (matching the
    # SDK semantics this had) and falls back to the local model when the
    # subscription window is spent. A flush fires on every SessionEnd, so
    # losing them for the rest of a rate window loses a day of memory - and
    # the local path keeps transcript tails on the machine, which is the
    # better place for them anyway.
    result = failover.run_text(
        f"Conversation tail:\n\n{context}",
        system=SYSTEM_PROMPT,
        model=AGENT_MODEL,
        timeout=300,
        invoked_by="memory-flush",
        usage_source="memory-flush")
    if not result.ok:
        raise RuntimeError(result.error or "memory flush failed")
    return result.text.strip()


def already_flushed(session_id: str) -> bool:
    state = read_json(FLUSH_STATE, {}) or {}
    last = state.get(session_id, 0)
    return (time.time() - last) < DEDUP_WINDOW_S


def mark_flushed(session_id: str) -> None:
    with file_lock(FLUSH_STATE):
        state = read_json(FLUSH_STATE, {}) or {}
        state[session_id] = time.time()
        # keep the state file small - drop entries older than a day
        cutoff = time.time() - 86_400
        state = {k: v for k, v in state.items() if v > cutoff}
        atomic_write_json(FLUSH_STATE, state)


def main() -> int:
    ensure_dirs()
    if "--test" in sys.argv:
        context = ("USER: let's use sqlite-vec for the vault index\n\n"
                   "ASSISTANT: Agreed - decision: sqlite-vec with cosine distance, "
                   "384-dim MiniLM embeddings.")
        session_id = f"test-{int(time.time())}"
        cleanup = None
    else:
        if len(sys.argv) < 3:
            print("usage: memory_flush.py <context_file> <session_id>", file=sys.stderr)
            return 2
        ctx_file = Path(sys.argv[1])
        session_id = sys.argv[2]
        try:
            context = ctx_file.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            log_line("flush", f"ERROR reading context {ctx_file}: {e!r}")
            return 1
        cleanup = ctx_file

    if already_flushed(session_id):
        log_line("flush", f"dedup: session {session_id} flushed <{DEDUP_WINDOW_S}s ago")
        if cleanup:
            cleanup.unlink(missing_ok=True)
        return 0
    # Mark BEFORE the (slow) model call - the second hook of a PreCompact+SessionEnd
    # pair fires within seconds, well inside the model's response time.
    mark_flushed(session_id)

    try:
        summary = summarize(context)
    except Exception as e:
        # No model available - usually the `claude` CLI missing or logged out.
        # Save a raw excerpt rather than losing the session: worse than a
        # distilled summary, far better than nothing.
        log_line("flush", f"model call failed (session {session_id}): {e!r} "
                          "- falling back to raw excerpt")
        excerpt = context[-2_000:]
        append_to_daily_log(
            "Session flush (raw fallback - LLM unavailable)",
            "_Run `claude login` to restore intelligent summaries "
            "(no API key needed)._\n\n"
            "```\n" + excerpt.replace("```", "``") + "\n```",
        )
        if cleanup:
            cleanup.unlink(missing_ok=True)
        return 0

    if not summary or summary.upper().startswith("FLUSH_OK"):
        log_line("flush", f"session {session_id}: FLUSH_OK (nothing to save)")
    else:
        append_to_daily_log("Session flush", summary)
        log_line("flush", f"session {session_id}: saved {summary.count(chr(10)) + 1} lines")

    if cleanup:
        cleanup.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
