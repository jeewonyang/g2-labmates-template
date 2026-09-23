"""Codex CLI adapter - structured extraction and independent second opinions.

Verified against codex-cli 0.144.4. Codex earns a slot rather than being a
redundant second Claude because:

  --output-schema  gives JSON-Schema-*validated* final output, which beats
                   prompt-and-hope for extraction jobs
  -s read-only     a real sandbox for jobs that must not write
  --json           streams events, so /ops can show progress
  independent model family = a genuinely independent review pass, where a
  shared-model bias would be invisible

It already shares this repo's contract (AGENTS.md -> CLAUDE.md) and the same
hooks (.codex/hooks.json -> .claude/hooks/), so it inherits the security posture.

Never pass --dangerously-bypass-approvals-and-sandbox from the dispatcher.
"""

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from . import RunResult

RUNTIME = "codex"
# Empty = inherit ~/.codex/config.toml, which is currently model = "gpt-5.6-sol"
# with model_reasoning_effort = "high". Leaving it empty is deliberate: their CLI
# config stays the single place to change the coding model, rather than this
# file drifting out of sync with it.
DEFAULT_MODEL = os.environ.get("SECONDBRAIN_CODEX_MODEL", "")
# Per-run reasoning effort, passed as -c. None = inherit the config default.
REASONING_EFFORT = os.environ.get("SECONDBRAIN_CODEX_EFFORT") or None

# Auth: `codex login status` reports "Logged in using ChatGPT" on this machine,
# so Codex needs no API key. Verified headless 2026-07-26.


def codex_path() -> str | None:
    """Resolve the launcher to a full path.

    Required on Windows: the installed entry point is codex.CMD, and passing the
    bare name "codex" to subprocess without shell=True raises WinError 2 because
    CreateProcess does no PATHEXT resolution. available() was resolving it while
    run() passed the bare name, so the runtime reported healthy and then failed
    on every dispatch.
    """
    # The Windows Store alias under Program Files/WindowsApps can be visible to
    # shutil.which() yet reject CreateProcess with WinError 5 from background
    # Python. The desktop app also maintains an executable copy under
    # LocalAppData specifically for subprocess use; prefer the newest one.
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "OpenAI" / "Codex" / "bin"
    try:
        copies = sorted(
            local.glob("*/codex.exe"),
            key=lambda candidate: candidate.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        copies = []
    for candidate in copies:
        if candidate.is_file():
            return str(candidate)
    return shutil.which("codex")


def available() -> bool:
    return codex_path() is not None


def _strictify(schema):
    """Convert plain JSON Schema into the strict form Codex requires.

    `--output-schema` is validated as an OpenAI structured-output schema, which
    demands `additionalProperties: false` on every object AND every property
    listed in `required`. Without this, Codex returns HTTP 400
    invalid_json_schema and the job fails - which is exactly what happened on
    the first wiki.ingest run.

    Job modules keep writing ordinary JSON Schema; this normalizes it at the
    boundary. Optionality is preserved by nullable types, not by omission from
    `required`, which is how strict mode expects it to be expressed.
    """
    if not isinstance(schema, dict):
        return schema
    out = dict(schema)
    if out.get("type") == "object" or "properties" in out:
        props = {k: _strictify(v) for k, v in (out.get("properties") or {}).items()}
        out["properties"] = props
        out["additionalProperties"] = False
        out["required"] = list(props)          # strict mode: all keys required
    if "items" in out:
        out["items"] = _strictify(out["items"])
    for key in ("anyOf", "oneOf", "allOf"):
        if key in out and isinstance(out[key], list):
            out[key] = [_strictify(s) for s in out[key]]
    return out


def _parse_jsonl_usage(stream: str) -> tuple[int, int, float]:
    """Best-effort token/cost extraction from --json event stream."""
    tin = tout = 0
    cost = 0.0
    for line in stream.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        usage = ev.get("usage") or (ev.get("info") or {}).get("usage") or {}
        if isinstance(usage, dict):
            tin = usage.get("input_tokens", usage.get("prompt_tokens", tin)) or tin
            tout = usage.get("output_tokens", usage.get("completion_tokens", tout)) or tout
            cost = usage.get("cost_usd", cost) or cost
    return tin, tout, cost


def _stream_error(stream: str) -> str:
    """The failure Codex reported inside its own event stream.

    `codex exec --json` puts real failures on **stdout** as
    `{"type":"error","message":...}` and exits 1 with an empty stderr, so the
    obvious `f"codex exit {rc}: {stderr}"` produced a bare "codex exit 1:".
    That cost more than readability: "Your workspace is out of credits" is what
    tells failover.is_capacity_error() to hand the job to Claude, and without
    it a spent ChatGPT subscription looked like an unexplained crash and failed
    every codex-routed job with no backup.
    """
    messages = []
    for line in (stream or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "error" or event.get("error"):
            msg = event.get("message") or event.get("error")
            if isinstance(msg, dict):
                msg = msg.get("message") or json.dumps(msg)
            if isinstance(msg, str) and msg.strip():
                messages.append(msg.strip())
    return " | ".join(messages)


def _read_last_message(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _structured_result(text: str, schema: dict | None):
    if not schema:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _wait_for_process(proc, *, timeout: int, cancel_check=None,
                      progress_callback=None):
    """Wait in short intervals so dashboard cancellation is cooperative."""
    started = time.monotonic()
    if progress_callback:
        progress_callback(proc.pid)
    while True:
        if cancel_check and cancel_check():
            proc.terminate()
            try:
                stdout, stderr = proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout, stderr = proc.communicate()
            return stdout, stderr, True, False
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 0:
            proc.kill()
            stdout, stderr = proc.communicate()
            return stdout, stderr, False, True
        try:
            stdout, stderr = proc.communicate(timeout=min(1.0, remaining))
            return stdout, stderr, False, False
        except subprocess.TimeoutExpired:
            if progress_callback:
                progress_callback(proc.pid)


def run(prompt: str, *, schema: dict | None = None, cwd=None,
        timeout: int = 900, model: str | None = None,
        web_search: bool = False, sandbox: str = "read-only",
        cancel_check=None, progress_callback=None) -> RunResult:
    if not available():
        return RunResult(ok=False, runtime=RUNTIME,
                         error="codex CLI not found on PATH")
    if sandbox not in {"read-only", "workspace-write"}:
        return RunResult(
            ok=False,
            runtime=RUNTIME,
            error="codex sandbox must be read-only or workspace-write",
        )

    cwd = Path(cwd) if cwd else Path.cwd()
    model = model or DEFAULT_MODEL
    tmpdir = Path(tempfile.mkdtemp(prefix="codex_rt_"))
    last_msg = tmpdir / "last_message.txt"
    prompt_file = tmpdir / "prompt.txt"
    prompt_file.write_text(prompt, encoding="utf-8")

    cmd = [codex_path()]
    if web_search:
        cmd.append("--search")
    cmd += ["exec", "--json",
           "-C", str(cwd),
           # Dispatcher calls rely on the default read-only value. The only
           # workspace-write caller is the explicit Quick Capture G2 runner.
           "-s", sandbox,
           "-o", str(last_msg),
           "--skip-git-repo-check"]
    if model:
        cmd += ["-m", model]
    if REASONING_EFFORT:
        cmd += ["-c", f'model_reasoning_effort="{REASONING_EFFORT}"']
    if schema:
        schema_file = tmpdir / "schema.json"
        schema_file.write_text(json.dumps(_strictify(schema)), encoding="utf-8")
        cmd += ["--output-schema", str(schema_file)]
    # Deliver the prompt on stdin ("-"), not as an argv element. A multi-line
    # prompt passed as a Windows command-line argument gets mangled - Codex
    # received a 3.2k-char prompt and replied "no source was provided". stdin
    # also sidesteps the ~8k command-line length limit.
    cmd.append("-")

    try:
        with open(prompt_file, "r", encoding="utf-8") as prompt_stream:
            proc = subprocess.Popen(
                cmd,
                stdin=prompt_stream,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            stdout, stderr, cancelled, timed_out = _wait_for_process(
                proc,
                timeout=timeout,
                cancel_check=cancel_check,
                progress_callback=progress_callback,
            )
    except OSError as e:
        return RunResult(ok=False, runtime=RUNTIME, model=model,
                         error=f"codex failed to start: {e}")

    if cancelled:
        return RunResult(
            ok=False,
            runtime=RUNTIME,
            model=model or "codex-default",
            error="codex run cancelled by user",
            meta={"cancelled": True},
        )
    if timed_out:
        # Codex writes `-o` only when it has a final answer. On Windows the CLI
        # can finish that atomic write but keep the parent process alive long
        # enough for the runtime to hit its deadline. A complete,
        # parseable structured result is safer to keep than to discard and
        # rerun; partial output still fails closed.
        recovered_text = _read_last_message(last_msg)
        recovered_data = _structured_result(recovered_text, schema)
        if recovered_data is not None:
            return RunResult(
                ok=True,
                data=recovered_data,
                text=recovered_text,
                runtime=RUNTIME,
                model=model or "codex-default",
                meta={"recovered_after_timeout": True},
            )
        return RunResult(ok=False, runtime=RUNTIME, model=model,
                         error=f"codex timed out after {timeout}s")

    text = ""
    text = _read_last_message(last_msg) or (stdout or "").strip()

    if proc.returncode != 0:
        detail = (_stream_error(stdout) or (stderr or "").strip()
                  or "no error message on stdout or stderr")
        return RunResult(ok=False, runtime=RUNTIME, model=model, text=text,
                         error=f"codex exit {proc.returncode}: {detail[:400]}")

    data = None
    if schema:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            return RunResult(ok=False, runtime=RUNTIME, model=model, text=text,
                             error=f"structured output did not parse: {e}")

    tin, tout, cost = _parse_jsonl_usage(stdout or "")
    # `codex exec` authenticates with the owner's ChatGPT subscription, so any
    # cost it reports is API-equivalent, not billed. See RunResult.subscription.
    return RunResult(ok=True, data=data, text=text, runtime=RUNTIME,
                     model=model or "codex-default",
                     cost_usd=cost, tokens_in=tin, tokens_out=tout,
                     subscription=True)
