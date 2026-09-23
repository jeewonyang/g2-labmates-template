"""Job-kind registry.

Adding a capability to the Agent OS = adding one module here. The dispatcher
resolves `kind` -> module and never needs to change.

Each job module declares:

    KIND             = "triage.classify"      # dotted, matches the ledger field
    DEFAULT_RUNTIME  = "ollama"               # claude | codex | ollama
    SENSITIVITY      = "private"              # private | internal
    REVIEW_REQUIRED  = True                   # effect reaches outside Memory/?
    SCHEMA           = {...}                  # JSON Schema for structured output
    ALLOWED_TOOLS    = [...]                  # optional, claude runtime only

    def build_prompt(payload) -> str: ...
    def apply(job, result) -> None: ...       # only called after approval

REVIEW_REQUIRED is the Advisor-mode gate. Set it True for anything whose effect
reaches outside VAULT/Memory/ - filing into the vault, creating a Gmail draft,
editing source. Only jobs confined to agent-owned state may complete directly.
"""

import importlib
import pkgutil
from pathlib import Path

_REGISTRY: dict = {}
_LOADED = False

REQUIRED_ATTRS = ("KIND", "DEFAULT_RUNTIME", "SENSITIVITY", "REVIEW_REQUIRED",
                  "build_prompt")


def _load() -> None:
    global _LOADED
    if _LOADED:
        return
    pkg_dir = Path(__file__).resolve().parent
    for info in pkgutil.iter_modules([str(pkg_dir)]):
        if info.name.startswith("_"):
            continue
        mod = importlib.import_module(f"{__name__}.{info.name}")
        missing = [a for a in REQUIRED_ATTRS if not hasattr(mod, a)]
        if missing:
            raise ImportError(
                f"job module {info.name} is missing {', '.join(missing)}")
        _REGISTRY[mod.KIND] = mod
    _LOADED = True


def get(kind: str):
    """Return the module for a job kind, or None if unregistered."""
    _load()
    return _REGISTRY.get(kind)


def kinds() -> list[str]:
    _load()
    return sorted(_REGISTRY)
