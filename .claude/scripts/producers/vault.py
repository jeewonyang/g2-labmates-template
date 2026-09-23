"""Vault Maintenance producer - keeps the vault current.

Three streams:

  untriaged intake -> triage.classify   (reuses triage/enqueue.py's candidate
                                         walk, which already knows every
                                         exclusion rule)
  pending sources  -> wiki.ingest       (reuses wiki_build's enumeration and
                                         its wiki-state.json cursor)
  yesterday's log  -> memory.reflect    (once per calendar day)

**This producer owns no state of its own.** Each stream defers to the module
that already tracks its cursor: triage/enqueue.py walks the inboxes,
wiki_build.py owns wiki-state.json, and heartbeat-state.json holds
`reflection_date`. An earlier version of this file kept its own
`producer-vault.json` with a duplicate `wiki_ingested` map, which is exactly the
"two systems both believe they own what ran last" failure the Agent OS plan
warns about - the two would drift the first time a page was ingested by the
`wiki` skill instead of by a job.

The reflection guard is shared with heartbeat_produce.py rather than
duplicated. Folding reflection into the scan was a deliberate 2026-07-09
decision, so the "Run scan now" button still triggers it; this producer checks
the same `reflection_date` cursor, which makes whichever runs first the only one
that spends anything. Running both is a no-op, not a double charge.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ledger  # noqa: E402
from shared import REPO_ROOT, now  # noqa: E402

TEAM = "vault"

# Triage volume is capped per run. The archive backlog is tens of thousands of
# documents; draining it is a deliberate overnight `dispatch.py --watch
# --runtimes ollama` session, not something a daily pass should silently start.
MAX_TRIAGE_PER_RUN = 40

# Wiki volume is capped lower, for a different reason: wiki.ingest is
# REVIEW_REQUIRED, so every job enqueued here becomes an item in their approval
# queue. 12/day is a backlog they can actually clear alongside everything else.
# Raising it past agent_day's codex cap (20) just grows the queue without
# ingesting faster. To burn down the backlog deliberately, run
# `dispatch.py --once --kinds wiki.ingest --max N` by hand.
MAX_WIKI_PER_RUN = 12

# Sources newer than this are "fresh knowledge" and jump the backlog queue.
WIKI_FRESH_DAYS = 3

# Statuses meaning a job for this source is already in play. Sources are only
# marked ingested at apply() time (after approval), so without this guard every
# daily run would re-enqueue everything still sitting in the review queue.
KNOWN_STATUSES = {
    "created", "claimed", "needs_review", "approved", "completed", "rejected",
    "superseded",
}


def _inflight_paths(kind: str) -> set:
    """Payload paths that already have a live job of this kind."""
    out = set()
    for j in ledger.query(kind=kind):
        if j.get("status") in KNOWN_STATUSES:
            p = (j.get("payload") or {}).get("path")
            if p:
                out.add(p)
    return out


def _triage_specs() -> list[dict]:
    try:
        from triage.enqueue import candidates
    except ImportError:
        return []
    inflight = _inflight_paths("triage.classify")
    specs = []
    for p in candidates():
        rel = str(p.relative_to(REPO_ROOT)).replace("\\", "/")
        if rel in inflight:
            continue
        specs.append({
            "kind": "triage.classify",
            "runtime": "ollama",            # local: intake mixes in sensitive material
            "sensitivity": "private",
            "payload": {"path": rel},
        })
        if len(specs) >= MAX_TRIAGE_PER_RUN:
            break
    return specs


def _wiki_specs() -> list[dict]:
    """Pending wiki sources, freshest first, then backlog in path order.

    Enumeration comes from wiki_build.iter_source_files(), NOT a local glob.
    That walk is the one place the vault exclusions live - Finance,
    Confidential, Research-Private, 00_Inbox, secrets, junk and vendored dirs -
    and a second copy here would drift out of sync exactly as wiki_build itself
    drifted from memory_index.py (fixed 2026-07-27). Everything it yields is
    cloud-safe by construction, which is what lets these jobs run on codex.
    """
    import wiki_build

    state = wiki_build.load_state()
    pending = wiki_build.pending_sources(state)
    if not pending:
        return []

    inflight = _inflight_paths("wiki.ingest")
    cutoff = now().timestamp() - WIKI_FRESH_DAYS * 86400

    # Fresh edits first (newest knowledge is the most useful to have indexed),
    # then the backlog in path order so folder-adjacent files - which tend to be
    # topically related - get ingested near each other and cross-link well.
    fresh = sorted((t for t in pending if t[1] >= cutoff),
                   key=lambda t: -t[1])
    backlog = [t for t in pending if t[1] < cutoff]

    specs = []
    for rel, _mtime, _size in fresh + backlog:
        # wiki_build yields paths relative to VAULT; every ledger payload in
        # this system is relative to REPO_ROOT. Converting here is not
        # cosmetic - two things depend on it:
        #   1. wiki_ingest resolves the path against REPO_ROOT, so a bare
        #      "Memory/SOUL.md" reads nothing and the model dutifully reports
        #      "no extractable text".
        #   2. dispatch.derive_sensitivity() matches the literal prefixes
        #      "VAULT/Confidential/" and "VAULT/Research-Private/". A
        #      VAULT-relative path would slip past that guard entirely.
        path = f"VAULT/{rel}"
        if path in inflight:
            continue
        specs.append({
            "kind": "wiki.ingest",
            "runtime": "codex",
            "sensitivity": "internal",
            "payload": {"path": path},
        })
        if len(specs) >= MAX_WIKI_PER_RUN:
            break
    return specs


def _reflect_specs() -> list[dict]:
    import heartbeat_produce
    target = heartbeat_produce.should_reflect()
    if not target:
        return []
    return [{
        "kind": "memory.reflect",
        "runtime": "claude",
        "sensitivity": "internal",
        "payload": {"date": target},
    }]


def plan() -> list[dict]:
    return _reflect_specs() + _wiki_specs() + _triage_specs()
