"""Tracked one-shot deployment of every enabled Agent OS team."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ledger  # noqa: E402
from shared import LOG_DIR, STATE_DIR, atomic_write_json, log_line, now  # noqa: E402

STATE = STATE_DIR / "agent-deploy-state.json"
OUTPUT_LOG = LOG_DIR / "agent-deploy.log"


def write_state(**values) -> None:
    atomic_write_json(STATE, values)


def main() -> int:
    run_id = uuid.uuid4().hex[:12]
    started = now()
    write_state(
        runId=run_id,
        status="running",
        pid=os.getpid(),
        startedAt=started.isoformat(timespec="seconds"),
        finishedAt=None,
        exitCode=None,
        output="",
        queue=ledger.stats().get("by_status", {}),
    )
    log_line("agent-deploy", f"{run_id} started")

    command = [
        sys.executable,
        str(Path(__file__).resolve().parent / "agent_day.py"),
        "--force",
    ]
    try:
        result = subprocess.run(
            command,
            cwd=str(Path(__file__).resolve().parents[2]),
            capture_output=True,
            timeout=4 * 60 * 60,
        )
        output = (
            result.stdout.decode("utf-8", errors="replace")
            + result.stderr.decode("utf-8", errors="replace")
        ).strip()
        status = "completed" if result.returncode == 0 else "failed"
        exit_code = result.returncode
    except Exception as exc:
        output = f"{type(exc).__name__}: {exc}"
        status = "failed"
        exit_code = 1

    finished = now()
    OUTPUT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_LOG.open("a", encoding="utf-8") as handle:
        handle.write(
            f"\n[{started.isoformat(timespec='seconds')}] {run_id}\n{output}\n"
        )
    write_state(
        runId=run_id,
        status=status,
        pid=os.getpid(),
        startedAt=started.isoformat(timespec="seconds"),
        finishedAt=finished.isoformat(timespec="seconds"),
        exitCode=exit_code,
        output=output[-8000:],
        queue=ledger.stats().get("by_status", {}),
    )
    log_line("agent-deploy", f"{run_id} {status} exit={exit_code}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
