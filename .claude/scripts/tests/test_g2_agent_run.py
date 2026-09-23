"""Safety and routing checks for dashboard-launched G2 implementation runs."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import sys

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import g2_agent_run  # noqa: E402
from runtimes import RunResult  # noqa: E402


def check(label, condition, detail=""):
    mark = "PASS" if condition else "FAIL"
    print(f"  [{mark}] {label}" + (f": {detail}" if detail else ""))
    if not condition:
        raise AssertionError(label)


def state(provider: str) -> dict:
    return {
        "id": "12345678-1234-4123-8123-123456789abc",
        "provider": provider,
        "prompt": "Add a small status label.",
        "status": "queued",
        "createdAt": "2026-07-30T00:00:00+00:00",
    }


def test_prompt_contract():
    prompt = g2_agent_run.build_prompt("Fix the capture button.")
    flat = " ".join(prompt.split())
    check("prompt requires project instructions", "Read AGENTS.md and CLAUDE.md" in prompt)
    check("prompt protects private vaults", "VAULT/Research-Private" in prompt)
    check("prompt preserves dirty work", "unrelated work in progress" in flat)
    check("prompt preserves never-delete",
          "Do not delete, rename, move, or truncate existing files" in flat)


def test_codex_is_fixed_to_workspace_write():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        run_file = root / f"{state('codex')['id']}.json"
        g2_agent_run.atomic_write_json(run_file, state("codex"))
        calls = []
        with (
            patch.object(g2_agent_run, "RUNS_DIR", root),
            patch.object(g2_agent_run, "ACTIVE_LOCK", root / "active"),
            patch.object(
                g2_agent_run.codex_rt,
                "run",
                side_effect=lambda *args, **kwargs: (
                    calls.append(kwargs)
                    or RunResult(ok=True, text="done", runtime="codex")
                ),
            ),
        ):
            check("codex run succeeds", g2_agent_run.run_one(state("codex")["id"]) == 0)
        check("codex is workspace sandboxed", calls[0]["sandbox"] == "workspace-write")
        check("codex cwd is fixed", calls[0]["cwd"] == g2_agent_run.REPO_ROOT)


def test_claude_tools_are_fixed_server_side():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        run_file = root / f"{state('claude')['id']}.json"
        g2_agent_run.atomic_write_json(run_file, state("claude"))
        calls = []
        with (
            patch.object(g2_agent_run, "RUNS_DIR", root),
            patch.object(g2_agent_run, "ACTIVE_LOCK", root / "active"),
            patch.object(
                g2_agent_run.claude_rt,
                "run",
                side_effect=lambda *args, **kwargs: (
                    calls.append(kwargs)
                    or RunResult(ok=True, text="done", runtime="claude")
                ),
            ),
        ):
            check("claude run succeeds", g2_agent_run.run_one(state("claude")["id"]) == 0)
        check("claude tools are fixed server side",
              calls[0]["allowed_tools"] == ["Read", "Edit", "Write", "Glob", "Grep", "Bash"])
        check("claude cwd is fixed", calls[0]["cwd"] == g2_agent_run.REPO_ROOT)


def test_cancellation_is_durable_and_idempotent():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        queued_state = state("codex")
        run_file = root / f"{queued_state['id']}.json"
        g2_agent_run.atomic_write_json(run_file, queued_state)
        with patch.object(g2_agent_run, "RUNS_DIR", root):
            first = g2_agent_run.request_cancel(queued_state["id"])
            second = g2_agent_run.request_cancel(queued_state["id"])
        check("queued coding run cancels before launch",
              first["status"] == "cancelled")
        check("repeated cancellation is idempotent",
              second["status"] == "cancelled")

        running_state = {
            **state("claude"),
            "status": "running",
            "phase": "working",
        }
        g2_agent_run.atomic_write_json(run_file, running_state)
        with patch.object(g2_agent_run, "RUNS_DIR", root):
            requested = g2_agent_run.request_cancel(running_state["id"])
        check("running coding run receives a cooperative stop request",
              requested["status"] == "cancel_requested")


if __name__ == "__main__":
    test_prompt_contract()
    test_codex_is_fixed_to_workspace_write()
    test_claude_tools_are_fixed_server_side()
    test_cancellation_is_durable_and_idempotent()
    print("\nAll G2 agent-run tests passed.")
