"""Producers: the deterministic half of every team.

A producer decides WHAT work exists. It never calls a model. It reads the
filesystem, the integrations, and the ledger, and returns a list of job specs;
`enqueue()` turns those into ledger jobs. Keeping the gathering deterministic is
what makes a failed run cheap to retry and a dry run honest.

Each producer module exposes:

    TEAM = "research"
    def plan() -> list[dict]     # [{"kind", "payload", "runtime"?, "sensitivity"?}]

and optionally:

    def commit() -> None                    # persist cursors plan() advanced;
                                            # called only after enqueue succeeds
    def produce(*, dry_run=False) -> dict   # for producers that own state,
                                            # bypassing plan()/enqueue()

`produce()` exists for `admin`, which delegates to heartbeat_produce.py - that
script owns the integration snapshot cursor, and two things advancing the same
cursor is the bug this avoids.

`commit()` exists so a producer that tracks "already handled" cursors writes
them only once the jobs are really in the ledger. Dry runs never commit, and a
crash mid-enqueue re-produces rather than silently skipping work.
"""

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ledger  # noqa: E402


def get(name: str):
    """Import a producer module by its manifest name."""
    return importlib.import_module(f"{__name__}.{name}")


def enqueue(specs, *, dry_run: bool = False) -> list[str]:
    """Create one ledger job per spec. Returns the new job ids."""
    if dry_run:
        return []
    out = []
    for s in specs:
        out.append(ledger.create(
            s["kind"], s.get("payload") or {},
            runtime=s.get("runtime"),
            sensitivity=s.get("sensitivity", "private"),
            parent=s.get("parent"),
        ))
    return out


def run(name: str, *, dry_run: bool = False) -> dict:
    """Run one producer. Uniform result shape for agent_day.py to report."""
    mod = get(name)
    if hasattr(mod, "produce"):
        return mod.produce(dry_run=dry_run)
    specs = mod.plan()
    ids = enqueue(specs, dry_run=dry_run)
    if not dry_run and hasattr(mod, "commit"):
        mod.commit()            # only now are the jobs durable
    by_kind: dict = {}
    for s in specs:
        by_kind[s["kind"]] = by_kind.get(s["kind"], 0) + 1
    return {
        "created": len(ids),
        "planned": len(specs),
        "by_kind": by_kind,
        "job_ids": ids,
    }
