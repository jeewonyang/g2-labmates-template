"""Per-machine model policy: which model each job kind runs on, set from /teams.

The job modules hard-code a sensible default (`MODEL = "opus"`), and until now
that was the only place a model could be chosen - retuning an agent meant
editing Python. This file is the override layer the dashboard's model picker
writes, and the one place the dispatcher reads before calling a runtime:

    {
      "defaults": {"claude": "fable"},                    # every claude kind
      "kinds": {"hr.packet_review": {"claude": "opus"}},  # one kind, one runtime
      "updated": "2026-09-18T21:00:00-07:00"
    }

Resolution, most specific first: kinds[kind][runtime] -> defaults[runtime] ->
None (the module's own MODEL, then the runtime default). Keyed by runtime so a
job that fails over from claude to codex asks the policy again for codex
rather than carrying a claude model name across.

It lives under .claude/data/state/ (gitignored, per machine) on purpose: the
desktop is the machine that runs the agents, and a versioned config edited
from the dashboard would dirty the checkout and block the auto-updater.

Failover is untouched. A policy that names "fable" still steps down
fable -> opus -> sonnet inside claude_rt when a window is spent, because
MODEL_BACKUP keys on the model name, not on where it came from. The Max
portfolio planner is deliberately outside this file: it pins its own model
pair and passes model_fallback=False.

  python .claude/scripts/runtimes/model_policy.py show
  python .claude/scripts/runtimes/model_policy.py set <kind|*> <runtime> <model>
  python .claude/scripts/runtimes/model_policy.py clear <kind|*> [runtime]
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared import STATE_DIR, atomic_write_json, file_lock, now, read_json  # noqa: E402

POLICY_FILE = STATE_DIR / "model-policy.json"

RUNTIMES = ("claude", "codex", "ollama")

# What the picker offers per runtime. Claude aliases are the CLI's own
# (`claude -p --model fable`); MODEL_BACKUP in failover.py knows the first
# three, so a spent window still steps down. Codex and ollama take any name
# their CLI accepts - the dashboard offers only the runtime default for them.
CHOICES = {
    "claude": ("fable", "opus", "sonnet", "haiku"),
    "codex": (),
    "ollama": (),
}
# Full model ids are accepted too (claude-fable-5, claude-opus-5, gpt-5,
# qwen3:14b); this only keeps shell-ish junk out of a CLI argument.
MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,60}$")
KIND_RE = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")


class PolicyError(ValueError):
    pass


def load() -> dict:
    data = read_json(POLICY_FILE, {}) or {}
    if not isinstance(data, dict):
        data = {}
    defaults = data.get("defaults") if isinstance(data.get("defaults"), dict) else {}
    kinds = data.get("kinds") if isinstance(data.get("kinds"), dict) else {}
    return {"defaults": dict(defaults), "kinds": {k: dict(v) for k, v in kinds.items()
                                                  if isinstance(v, dict)},
            "updated": data.get("updated")}


def _save(data: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    data["updated"] = now().isoformat(timespec="seconds")
    atomic_write_json(POLICY_FILE, data)


def model_for(kind: str | None, runtime: str, *, inherit_default: bool = True) -> str | None:
    """The policy's answer for this kind on this runtime, or None for "as coded".

    `inherit_default=False` honours only an explicit pin for this kind, never
    the runtime-wide default: the Max trading planner asks that way, so the
    floor-wide "every desk on Sonnet" switch can never quietly move a
    portfolio judgment - only a pick made on Max's own chip does.
    """
    if runtime not in RUNTIMES:
        return None
    data = load()
    by_kind = data["kinds"].get(str(kind or ""), {})
    picked = by_kind.get(runtime) or (data["defaults"].get(runtime) if inherit_default else None)
    picked = str(picked or "").strip()
    return picked if picked and MODEL_RE.match(picked) else None


def _check(runtime: str, model: str | None) -> str | None:
    if runtime not in RUNTIMES:
        raise PolicyError(f"Unknown runtime {runtime!r}.")
    if model is None or str(model).strip() == "":
        return None
    model = str(model).strip()
    if not MODEL_RE.match(model):
        raise PolicyError("That is not a model name.")
    return model


def set_model(kind: str | None, runtime: str, model: str | None) -> dict:
    """Pin one kind (or, with kind None / "*", the runtime default). An empty
    model clears the pin, so the module's own MODEL applies again."""
    model = _check(runtime, model)
    with file_lock(POLICY_FILE):
        data = load()
        if not kind or kind == "*":
            if model:
                data["defaults"][runtime] = model
            else:
                data["defaults"].pop(runtime, None)
        else:
            if not KIND_RE.match(kind):
                raise PolicyError(f"Unknown job kind {kind!r}.")
            entry = data["kinds"].setdefault(kind, {})
            if model:
                entry[runtime] = model
            else:
                entry.pop(runtime, None)
            if not entry:
                data["kinds"].pop(kind, None)
        _save(data)
    return data


def main() -> int:
    argv = sys.argv[1:]
    cmd = argv[0] if argv else "show"
    try:
        if cmd == "show":
            print(json.dumps(load(), indent=2))
            return 0
        if cmd == "set" and len(argv) == 4:
            print(json.dumps(set_model(argv[1], argv[2], argv[3]), indent=2))
            return 0
        if cmd == "clear" and len(argv) in (2, 3):
            runtimes = [argv[2]] if len(argv) == 3 else list(RUNTIMES)
            data = load()
            for rt in runtimes:
                data = set_model(argv[1], rt, None)
            print(json.dumps(data, indent=2))
            return 0
    except PolicyError as e:
        print(json.dumps({"error": str(e)}))
        return 2
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
