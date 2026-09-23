"""Ollama adapter - local, free, never leaves the machine.

Every job marked `private` routes here. Structured output uses Ollama's
`format` field, which accepts a JSON Schema directly.

Model roles on this box (12 GB VRAM, RTX 4070):
  qwen3:8b           5.2 GB  classifier workhorse, ~3 s/call
  qwen3:14b          9.3 GB  harder judgment
  gemma3:12b-it-qat  8.9 GB  NO tool support (per the owner's own eval) - structured output only
  llama3.2           2.0 GB  fallback / smoke tests

VRAM is the reason the dispatcher caps ollama concurrency at 1: qwen3:14b plus
the bge-m3 embedding model will not co-reside and will spill to CPU.
"""

import json
import os
import urllib.error
import urllib.request

from . import RunResult

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("SECONDBRAIN_LOCAL_MODEL", "qwen3:8b")
RUNTIME = "ollama"


def available() -> bool:
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=5):
            return True
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def run(prompt: str, *, schema: dict | None = None, cwd=None,
        timeout: int = 300, model: str | None = None,
        cancel_check=None, progress_callback=None) -> RunResult:
    model = model or DEFAULT_MODEL
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        # Low temperature: these are classification and extraction jobs, not prose.
        "options": {"temperature": 0.1},
    }
    if schema:
        body["format"] = schema

    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/chat",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            chunks = []
            payload = {}
            if progress_callback:
                progress_callback(None)
            for raw in r:
                if cancel_check and cancel_check():
                    return RunResult(
                        ok=False,
                        error="ollama run cancelled by user",
                        runtime=RUNTIME,
                        model=model,
                        meta={"cancelled": True},
                    )
                if progress_callback:
                    progress_callback(None)
                event = json.loads(raw.decode("utf-8"))
                chunks.append((event.get("message") or {}).get("content", ""))
                if event.get("done"):
                    payload = event
            text = "".join(chunks)
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        return RunResult(ok=False, error=f"ollama unreachable: {e}",
                         runtime=RUNTIME, model=model)
    except json.JSONDecodeError as e:
        return RunResult(ok=False, error=f"ollama returned non-JSON: {e}",
                         runtime=RUNTIME, model=model)

    data = None
    if schema:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            return RunResult(ok=False, text=text, runtime=RUNTIME, model=model,
                             error=f"structured output did not parse: {e}")

    return RunResult(
        ok=True, data=data, text=text, runtime=RUNTIME, model=model,
        # Local inference has no marginal dollar cost. Recording the zero row is
        # the point: it keeps the local-vs-cloud ratio visible in the ledger.
        cost_usd=0.0,
        tokens_in=payload.get("prompt_eval_count", 0),
        tokens_out=payload.get("eval_count", 0),
        meta={"total_duration_ns": payload.get("total_duration", 0)},
    )
