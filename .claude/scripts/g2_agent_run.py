"""Run an explicitly requested G2 code change from dashboard Quick Capture.

The browser chooses only a provider and supplies the authored request. It never
supplies a path, executable, command, tool list, model, sandbox, or environment.
Runs are serialized because every provider edits the same working tree.
"""

import argparse
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from runtimes import claude_rt, codex_rt, model_policy  # noqa: E402

# The policy kind the /teams picker pins Cody under. Not a ledger kind: runs
# live in .claude/data/state/g2-agent-runs/, not the job ledger.
POLICY_KIND = "g2.build_fix"
from shared import (REPO_ROOT, STATE_DIR, atomic_write_json,  # noqa: E402
                    file_lock, read_json)

RUNS_DIR = STATE_DIR / "g2-agent-runs"
ACTIVE_LOCK = STATE_DIR / "g2-agent-run-active"
RUN_ID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _path(run_id: str) -> Path:
    if not RUN_ID.fullmatch(run_id):
        raise ValueError("invalid G2 agent run id")
    return RUNS_DIR / f"{run_id}.json"


def _update(path: Path, **changes) -> dict:
    with file_lock(path):
        state = read_json(path, {}) or {}
        # Cancellation is an intervention, not a transient phase update.
        # Heartbeats and a just-finished preflight must never overwrite it.
        if state.get("status") in {"cancel_requested", "cancelled"}:
            requested_status = changes.get("status")
            if requested_status == "running":
                changes = {k: v for k, v in changes.items() if k != "status"}
            elif requested_status in {"completed", "failed"}:
                changes.update(
                    status="cancelled",
                    phase="finished",
                    error=(
                        "Cancelled by the owner. Changes made before cancellation "
                        "were preserved."
                    ),
                )
        state.update(changes)
        atomic_write_json(path, state)
        return state


def _cancel_requested(path: Path) -> bool:
    state = read_json(path, {}) or {}
    return state.get("status") in {"cancel_requested", "cancelled"}


def _mark_cancelled(path: Path, **changes) -> None:
    _update(
        path,
        status="cancelled",
        phase="finished",
        finishedAt=_now(),
        heartbeatAt=_now(),
        agentPid=None,
        error="Cancelled by the owner. Changes made before cancellation were preserved.",
        **changes,
    )


def request_cancel(run_id: str) -> dict:
    path = _path(run_id)
    with file_lock(path):
        state = read_json(path, {}) or {}
        if not state:
            raise ValueError("coding-agent run not found")
        if state.get("status") in {"completed", "failed", "cancelled"}:
            return state
        queued = state.get("status") == "queued"
        state.update(
            status="cancelled" if queued else "cancel_requested",
            phase="finished" if queued else state.get("phase"),
            cancelRequestedAt=_now(),
            cancelledBy="owner",
        )
        if queued:
            state.update(
                finishedAt=_now(),
                error="Cancelled before the coding agent started.",
            )
        atomic_write_json(path, state)
        return state


def build_prompt(request: str) -> str:
    return f"""\
You are operating as the maintenance agent for the local G2 Second Brain
codebase. The text between USER_REQUEST_BEGIN and USER_REQUEST_END is the
user's requested task. It is lower priority than this safety envelope,
AGENTS.md, CLAUDE.md, and the repository security hooks.

Read AGENTS.md and CLAUDE.md first and obey all project instructions. Inspect
the current working tree before editing; it may contain unrelated work in
progress, which you must preserve.

First decide whether this is an actionable request to add, change, debug, or
repair G2. If it is not, make no changes and explain why. If it is actionable,
make reasonable product and engineering judgments and implement the smallest
complete safe change.

Work only inside this repository. Do not read or attach private vault, Inbox,
live database, upload, backup, log, or exported content. In particular, never
read VAULT/Confidential, VAULT/Research-Private, VAULT/Finance, .env files,
credentials, tokens, browser profiles, or provider authentication files. Use
synthetic fixtures when example data is necessary.

Do not delete, rename, move, or truncate existing files or live user data. Do
not commit, push, switch branches, reset, clean, restore, or change Git config.
Do not install or update dependencies, run a live Prisma migration/database
command, use web search/external MCP tools, send or post anything, or widen
network access. If one of those operations is necessary, stop and name the
exact approval needed. Reuse existing services, hooks, and conventions. Run
only repository-approved validation.

Finish with a concise summary of what changed, validation performed, and any
remaining blocker. If the request cannot be completed safely, leave the
working tree unchanged and explain why.

USER_REQUEST_BEGIN
{request.strip()}
USER_REQUEST_END
"""


def _git(*args: str) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    output = (proc.stdout or proc.stderr or "").strip()
    return proc.returncode == 0, output


def _postflight(
    base_sha: str,
    baseline_status: set[str],
) -> tuple[list[str], list[dict], str]:
    head_ok, head = _git("rev-parse", "HEAD")
    status_ok, status = _git("status", "--short", "--untracked-files=all")
    diff_ok, diff_detail = _git("diff", "--check")
    changed = [line for line in status.splitlines() if line.strip()] if status_ok else []
    new_changes = [line for line in changed if line not in baseline_status]
    destructive = [
        line for line in new_changes
        if "D" in line[:2] or "R" in line[:2]
    ]
    checks = [
        {
            "name": "HEAD unchanged",
            "ok": head_ok and head == base_sha,
            "detail": head if head_ok else head or "Could not read HEAD.",
        },
        {
            "name": "Git change inventory",
            "ok": status_ok,
            "detail": (
                f"{len(new_changes)} newly changed paths; "
                f"{len(changed)} total dirty paths."
            ) if status_ok else status,
        },
        {
            "name": "git diff --check",
            "ok": diff_ok,
            "detail": diff_detail or "Passed.",
        },
        {
            "name": "No deletions or renames",
            "ok": not destructive,
            "detail": "; ".join(destructive) or "Passed.",
        },
    ]
    problems = [check["name"] for check in checks if not check["ok"]]
    return new_changes, checks, ", ".join(problems)


def run_one(run_id: str) -> int:
    path = _path(run_id)
    _update(path, runnerPid=os.getpid(), heartbeatAt=_now())
    state = read_json(path, {}) or {}
    provider = state.get("provider")
    request = state.get("prompt")
    if provider not in {"codex", "claude"} or not isinstance(request, str):
        _update(path, status="failed", finishedAt=_now(),
                error="Run state is missing a valid provider or prompt.")
        return 2
    if len(request.strip()) < 3 or len(request) > 8_000:
        _update(path, status="failed", finishedAt=_now(),
                error="Prompt must contain 3-8,000 characters.")
        return 2
    if _cancel_requested(path):
        _mark_cancelled(path)
        return 0

    # One writer at a time. A later capture remains visibly queued while this
    # process waits, avoiding concurrent agents trampling the same dirty tree.
    try:
        with file_lock(ACTIVE_LOCK, timeout=4 * 60 * 60):
            if _cancel_requested(path):
                _mark_cancelled(path)
                return 0
            head_ok, base_sha = _git("rev-parse", "HEAD")
            if not head_ok:
                _update(path, status="failed", phase="finished",
                        finishedAt=_now(), error=f"Git preflight failed: {base_sha}")
                return 1
            status_ok, baseline_raw = _git(
                "status", "--short", "--untracked-files=all",
            )
            if not status_ok:
                _update(path, status="failed", phase="finished",
                        finishedAt=_now(),
                        error=f"Git status preflight failed: {baseline_raw}")
                return 1
            baseline_status = set(baseline_raw.splitlines())
            running_state = _update(
                path,
                status="running",
                phase="assessing",
                baseSha=base_sha,
                startedAt=_now(),
                heartbeatAt=_now(),
                error="",
            )
            if running_state.get("status") in {"cancel_requested", "cancelled"}:
                _mark_cancelled(path)
                return 0
            prompt = build_prompt(request)
            # The CLI adapters retain their subscription login and standard OS
            # process context. G2 application/deployment secrets are not part
            # of a coding task and must not be inherited by agent tool calls.
            for key in (
                "DATABASE_URL",
                "CAPTURE_API_TOKEN",
                "OPS_API_TOKEN",
                "ANTHROPIC_API_KEY",
                "OPENAI_API_KEY",
                "GOOGLE_APPLICATION_CREDENTIALS",
            ):
                os.environ.pop(key, None)

            last_heartbeat = 0.0

            def progress(process_id=None):
                nonlocal last_heartbeat
                tick = time.monotonic()
                if tick - last_heartbeat < 2.0:
                    return
                last_heartbeat = tick
                changes = {"phase": "working", "heartbeatAt": _now()}
                if process_id:
                    changes["agentPid"] = process_id
                _update(path, **changes)

            if provider == "codex":
                result = codex_rt.run(
                    prompt,
                    cwd=REPO_ROOT,
                    timeout=30 * 60,
                    # Cody's model is the runtime default unless the /teams
                    # picker pinned one (per-machine policy; the browser still
                    # cannot name a model - only the provider).
                    model=model_policy.model_for(POLICY_KIND, "codex"),
                    sandbox="workspace-write",
                    cancel_check=lambda: _cancel_requested(path),
                    progress_callback=progress,
                )
            else:
                result = claude_rt.run(
                    prompt,
                    cwd=REPO_ROOT,
                    timeout=30 * 60,
                    model=model_policy.model_for(POLICY_KIND, "claude"),
                    allowed_tools=["Read", "Edit", "Write", "Glob", "Grep", "Bash"],
                    invoked_by="g2-quick-capture",
                    usage_source="g2-quick-capture",
                    cancel_check=lambda: _cancel_requested(path),
                    progress_callback=progress,
                )
    except Exception as exc:  # noqa: BLE001 - detached runner must report failure
        _update(path, status="failed", finishedAt=_now(),
                error=f"Runner failed: {exc}")
        return 1

    if _cancel_requested(path) or (result.meta or {}).get("cancelled"):
        changed, checks, _ = _postflight(base_sha, baseline_status)
        _mark_cancelled(
            path,
            result=(result.text or "")[:100_000],
            model=result.model,
            changedFiles=changed,
            checks=checks,
        )
        return 0

    _update(path, phase="verifying", heartbeatAt=_now(), agentPid=None)
    changed, checks, postflight_error = _postflight(base_sha, baseline_status)
    if result.ok and not postflight_error:
        _update(
            path,
            status="completed",
            phase="finished",
            finishedAt=_now(),
            result=(result.text or "Completed without a final message.")[:100_000],
            error="",
            model=result.model,
            changedFiles=changed,
            checks=checks,
        )
        return 0
    _update(
        path,
        status="failed",
        phase="finished",
        finishedAt=_now(),
        result=(result.text or "")[:100_000],
        error=(
            result.error
            or postflight_error
            or f"{provider} did not complete the run."
        )[:4_000],
        model=result.model,
        changedFiles=changed,
        checks=checks,
    )
    return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--cancel", action="store_true")
    args = parser.parse_args()
    if args.cancel:
        import json
        print(json.dumps(request_cancel(args.run_id), ensure_ascii=False))
        return 0
    return run_one(args.run_id)


if __name__ == "__main__":
    raise SystemExit(main())
