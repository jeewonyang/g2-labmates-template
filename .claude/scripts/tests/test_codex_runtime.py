"""Regression tests for the Codex runtime boundary."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtimes import codex_rt  # noqa: E402


def check(condition, label):
    if not condition:
        raise AssertionError(label)
    print(f"PASS {label}")


with tempfile.TemporaryDirectory() as temp:
    runtime_dir = Path(temp)
    original_available = codex_rt.available
    original_path = codex_rt.codex_path
    original_mkdtemp = codex_rt.tempfile.mkdtemp
    original_popen = codex_rt.subprocess.Popen
    original_wait = codex_rt._wait_for_process

    class TimedOutProcess:
        def __init__(self, command, **kwargs):
            self.command = command
            self.returncode = None

    def time_out_after_final_message(proc, **kwargs):
        output_path = Path(proc.command[proc.command.index("-o") + 1])
        output_path.write_text(
            json.dumps({"clean": True, "summary": "done", "findings": []}),
            encoding="utf-8",
        )
        proc.returncode = -9
        return "", "", False, True

    try:
        codex_rt.available = lambda: True
        codex_rt.codex_path = lambda: "codex"
        codex_rt.tempfile.mkdtemp = lambda **kwargs: str(runtime_dir)
        codex_rt.subprocess.Popen = TimedOutProcess
        codex_rt._wait_for_process = time_out_after_final_message
        result = codex_rt.run(
            "audit",
            schema={
                "type": "object",
                "properties": {
                    "clean": {"type": "boolean"},
                    "summary": {"type": "string"},
                    "findings": {"type": "array", "items": {"type": "object"}},
                },
            },
            timeout=1,
        )
    finally:
        codex_rt.available = original_available
        codex_rt.codex_path = original_path
        codex_rt.tempfile.mkdtemp = original_mkdtemp
        codex_rt.subprocess.Popen = original_popen
        codex_rt._wait_for_process = original_wait

check(result.ok, "complete structured output survives a process timeout")
check(result.data["summary"] == "done", "recovered structured data is returned")
check(
    result.meta.get("recovered_after_timeout") is True,
    "timeout recovery is recorded in runtime metadata",
)

with tempfile.TemporaryDirectory() as local_app_data:
    bundled = Path(local_app_data) / "OpenAI" / "Codex" / "bin" / "build"
    bundled.mkdir(parents=True)
    executable = bundled / "codex.exe"
    executable.write_bytes(b"MZ")
    original_local_app_data = codex_rt.os.environ.get("LOCALAPPDATA")
    try:
        codex_rt.os.environ["LOCALAPPDATA"] = local_app_data
        selected = codex_rt.codex_path()
    finally:
        if original_local_app_data is None:
            codex_rt.os.environ.pop("LOCALAPPDATA", None)
        else:
            codex_rt.os.environ["LOCALAPPDATA"] = original_local_app_data

check(
    selected == str(executable),
    "background runtime prefers the accessible desktop Codex copy",
)


# `codex exec --json` reports real failures on stdout and exits 1 with an empty
# stderr. Losing that message cost the backup routing its trigger: a spent
# ChatGPT subscription read as a bare "codex exit 1:" and failed over to
# nothing. Observed live 2026-08-14.
OUT_OF_CREDITS = (
    '{"type":"thread.started","thread_id":"01a0"}\n'
    '{"type":"turn.started"}\n'
    '{"type":"error","message":"Your workspace is out of credits. '
    'Ask your workspace owner to refill in the billing page."}\n'
)

check(
    "out of credits" in codex_rt._stream_error(OUT_OF_CREDITS),
    "a codex failure on the event stream survives into the error text",
)
check(
    codex_rt._stream_error('{"type":"item.completed"}\nnot json\n') == "",
    "a healthy event stream reports no error",
)

from runtimes import failover  # noqa: E402

check(
    failover.is_capacity_error(
        f"codex exit 1: {codex_rt._stream_error(OUT_OF_CREDITS)}"),
    "an out-of-credits codex run earns the Claude counterpart",
)

print("\nAll Codex runtime tests passed.")
