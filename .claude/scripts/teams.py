"""Team registry: the grouping layer over the job ledger.

A "team" is not a new execution system. Everything still runs as ledger jobs
through dispatch.py, with the same atomic claim, the same path-derived
sensitivity guard, and the same needs_review approval gate. A team is three
things and nothing more:

  1. a set of job kinds it owns,
  2. a producer that decides what work to enqueue and how often,
  3. a name and a card on /teams so the work is legible.

Manifests live in `.claude/agents/teams/*.json` - JSON rather than YAML so the
Next.js dashboard can read the same files without adding a parser dependency
(package.json has no yaml). Both `teams.py` and `src/lib/services/teams.ts`
read these files directly: one source of truth, no codegen, no drift.

Deliberately NOT stored in the ledger: adding a `team` field to the event
schema would mean migrating existing events and keeping two folds in sync.
Team membership is derived from `kind` instead, which is already recorded on
every `created` event. Reassigning a kind to another team is then a manifest
edit, and history re-groups itself correctly.

  python .claude/scripts/teams.py list
  python .claude/scripts/teams.py show research
  python .claude/scripts/teams.py validate
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shared import REPO_ROOT  # noqa: E402

TEAMS_DIR = REPO_ROOT / ".claude" / "agents" / "teams"

VALID_CADENCE = {"daily", "weekdays", "weekly", "manual"}
VALID_SENSITIVITY = {"private", "internal"}

REQUIRED_KEYS = ("id", "name", "kinds", "cadence")


class TeamError(RuntimeError):
    pass


_CACHE: dict | None = None


def _read_manifest(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise TeamError(f"{path.name}: invalid JSON: {e}") from e
    if not isinstance(data, dict):
        raise TeamError(f"{path.name}: manifest must be a JSON object")

    missing = [k for k in REQUIRED_KEYS if k not in data]
    if missing:
        raise TeamError(f"{path.name}: missing {', '.join(missing)}")
    if data["id"] != path.stem:
        raise TeamError(
            f"{path.name}: id {data['id']!r} does not match filename {path.stem!r}")
    if data["cadence"] not in VALID_CADENCE:
        raise TeamError(
            f"{path.name}: cadence {data['cadence']!r} not in {sorted(VALID_CADENCE)}")
    if not isinstance(data.get("kinds"), list):
        raise TeamError(f"{path.name}: kinds must be a list")
    # A retired team keeps its manifest (never-delete) with its kinds moved
    # elsewhere; only a disabled team may own nothing.
    if not data["kinds"] and data.get("enabled", True):
        raise TeamError(f"{path.name}: an enabled team needs at least one kind")

    # Fail closed, exactly like ledger.create(): an unset or bogus ceiling
    # means private, so a misconfigured team can never widen its own routing.
    ceiling = data.get("sensitivity_ceiling")
    data["sensitivity_ceiling"] = (
        ceiling if ceiling in VALID_SENSITIVITY else "private")

    data.setdefault("summary", "")
    data.setdefault("enabled", True)
    data.setdefault("producer", None)
    data.setdefault("run_at", None)
    data.setdefault("order", 50)
    return data


def load_all(*, refresh: bool = False) -> dict:
    """id -> manifest, for every well-formed manifest on disk."""
    global _CACHE
    if _CACHE is not None and not refresh:
        return _CACHE
    out: dict = {}
    if TEAMS_DIR.is_dir():
        for p in sorted(TEAMS_DIR.glob("*.json")):
            m = _read_manifest(p)
            out[m["id"]] = m
    _CACHE = out
    return out


def get(team_id: str) -> dict | None:
    return load_all().get(team_id)


def ids() -> list[str]:
    teams = load_all()
    return sorted(teams, key=lambda t: (teams[t].get("order", 50), t))


def for_kind(kind: str) -> str | None:
    """Which team owns a job kind. None for kinds no team claims."""
    for tid, m in load_all().items():
        if kind in m["kinds"]:
            return tid
    return None


def kind_map() -> dict:
    """kind -> team id, for bulk grouping of ledger jobs."""
    return {k: tid for tid, m in load_all().items() for k in m["kinds"]}


def scheduled_today(weekday: int) -> list[dict]:
    """Enabled teams whose cadence fires on this weekday (Mon=0).

    'weekly' fires Monday. the owner works 7 days a week, so 'daily' has no
    weekend gate - the same call the heartbeat's active hours already make.
    """
    out = []
    for tid in ids():
        m = load_all()[tid]
        if not m.get("enabled") or not m.get("producer"):
            continue
        c = m["cadence"]
        if c == "daily":
            out.append(m)
        elif c == "weekdays" and weekday < 5:
            out.append(m)
        elif c == "weekly" and weekday == 0:
            out.append(m)
    return out


def validate() -> list[str]:
    """Cross-check manifests against the job registry. Returns problems."""
    problems: list[str] = []
    try:
        teams = load_all(refresh=True)
    except TeamError as e:
        return [str(e)]

    import jobs as job_registry
    registered = set(job_registry.kinds())

    seen: dict = {}
    for tid, m in teams.items():
        for k in m["kinds"]:
            if k in seen:
                problems.append(
                    f"kind {k!r} claimed by both {seen[k]!r} and {tid!r}")
            seen[k] = tid
            if k not in registered:
                problems.append(
                    f"{tid}: kind {k!r} has no module in .claude/scripts/jobs/")
        if m.get("producer"):
            mod = TEAMS_DIR.parents[1] / "scripts" / "producers" / f"{m['producer']}.py"
            if not mod.is_file():
                problems.append(
                    f"{tid}: producer {m['producer']!r} not found at {mod}")

    for k in sorted(registered - set(seen)):
        problems.append(f"kind {k!r} is registered but belongs to no team")
    return problems


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    as_json = "--json" in sys.argv

    if cmd == "list":
        teams = load_all()
        if as_json:
            print(json.dumps([teams[t] for t in ids()], indent=2))
            return 0
        for tid in ids():
            m = teams[tid]
            flag = "" if m["enabled"] else "  (disabled)"
            print(f"{tid:<12} {m['cadence']:<9} {len(m['kinds'])} kinds{flag}")
            print(f"             {m['summary']}")
        return 0

    if cmd == "show":
        if len(sys.argv) < 3:
            print("usage: teams.py show <team-id>")
            return 2
        m = get(sys.argv[2])
        if not m:
            print(f"no such team: {sys.argv[2]}")
            return 1
        print(json.dumps(m, indent=2))
        return 0

    if cmd == "validate":
        problems = validate()
        if as_json:
            print(json.dumps({"ok": not problems, "problems": problems}, indent=2))
            return 0 if not problems else 1
        if not problems:
            print("OK - every kind belongs to exactly one team and has a module.")
            return 0
        for p in problems:
            print(f"PROBLEM: {p}")
        return 1

    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
