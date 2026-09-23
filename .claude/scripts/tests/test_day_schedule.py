"""The day schedule is one document that three consumers read.

`.claude/agents/day-schedule.json` holds the owner's day: wake, blocks, meals,
reminders, and the agent automation times derived from it (edit it to match
yours). `setup_scheduler.ps1` registers every SecondBrain task from its
`automation` section, `heartbeat.py` takes its default active hours from the
work blocks, and the /today schedule board plans tasks into them. These tests
assert the document's shape and its invariants, and that each consumer really
reads it rather than carrying its own copy of an hour - the
recurring bug in this repo is two copies of one fact drifting.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
REPO = SCRIPTS.parents[1]
sys.path.insert(0, str(SCRIPTS))

HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

SCHEDULE = REPO / ".claude" / "agents" / "day-schedule.json"
SCHEDULER = SCRIPTS / "setup_scheduler.ps1"
TEAMS = REPO / ".claude" / "agents" / "teams"


def _load() -> dict:
    return json.loads(SCHEDULE.read_text(encoding="utf-8"))


def _mins(hhmm: str) -> int:
    t = datetime.strptime(hhmm, "%H:%M")
    return t.hour * 60 + t.minute


def test_blocks_are_contiguous_from_wake_to_bed_prep():
    d = _load()
    blocks = d["blocks"]
    assert blocks[0]["start"] == d["wake"]
    assert blocks[-1]["end"] == d["bed_prep"]
    for a, b in zip(blocks, blocks[1:]):
        assert _mins(a["start"]) < _mins(a["end"]), a
        assert a["end"] == b["start"], f"gap or overlap between {a['id']} and {b['id']}"


def test_a_buffer_separates_arriving_from_deep_work():
    """Arriving and starting are two different things. The buffer is NOT a
    work block - the planner must leave it empty rather than packing a task
    into the minutes you use to put your bag down."""
    d = _load()
    blocks = d["blocks"]
    i = next(i for i, b in enumerate(blocks) if b["id"] == "settle")
    assert blocks[i - 1]["kind"] == "transit", "the buffer follows the commute"
    assert blocks[i + 1]["kind"] == "work", "deep work starts after it"
    assert blocks[i]["kind"] != "work", "a buffer the planner can fill is not a buffer"
    span = _mins(blocks[i]["end"]) - _mins(blocks[i]["start"])
    assert 10 <= span <= 30, span


def test_meals_are_one_hour_and_five_to_six_hours_apart():
    """Breakfast sits inside the morning routine hour; lunch and dinner are their own hour."""
    d = _load()
    meals = [b for b in d["blocks"] if b["kind"] == "meal"]
    assert [m["id"] for m in meals] == ["lunch", "dinner"]
    for m in meals:
        assert _mins(m["end"]) - _mins(m["start"]) == 60, m
    breakfast = next(b for b in d["blocks"] if b["id"] == "morning")
    starts = [_mins(breakfast["start"])] + [_mins(m["start"]) for m in meals]
    lo, hi = d["meal_spacing_hours"]["min"] * 60, d["meal_spacing_hours"]["max"] * 60
    for a, b in zip(starts, starts[1:]):
        assert lo <= b - a <= hi, f"meal spacing {b - a} min outside {lo}-{hi}"


def test_reminders_hang_off_real_blocks():
    d = _load()
    ids = {b["id"] for b in d["blocks"]}
    for r in d.get("reminders", []):
        assert r["block"] in ids, r
        assert r["when"] in ("start", "end"), r
        assert r["label"].strip(), r


def test_evening_work_is_light_only():
    d = _load()
    work = [b for b in d["blocks"] if b["kind"] == "work"]
    assert work[-1]["mode"] == "light", "no deep work after dinner"
    assert all(b.get("mode", "focus") == "focus" for b in work[:-1])
    p = d["planning"]
    assert p["light_max_task_minutes"] <= 30
    assert p["max_planned_task_hours"] <= 8
    assert 60 <= p["focus_break_after_minutes"] <= 120


def test_automation_stays_clear_of_the_planning_hour_and_rest():
    """Morning teams finish before they wake; intraday checks run only while they
    are at work - from arrival (the settle-in buffer) to the end of light work,
    never during the wind-down."""
    d = _load()
    a = d["automation"]
    by_id = {b["id"]: b for b in d["blocks"]}
    work = [b for b in d["blocks"] if b["kind"] == "work"]
    arrival = _mins(by_id["commute"]["end"])
    first_focus = _mins(work[0]["start"])
    work_end = work[-1]["end"]
    assert _mins(a["morning_run"]) <= _mins(d["wake"]) - 60, "morning run needs an hour before wake"
    assert _mins(a["reflection"]) < _mins(d["wake"])
    for key in ("intraday_admin", "heartbeat", "slack_monitor"):
        w = a[key]
        assert arrival <= _mins(w["start"]) <= first_focus, f"{key} starts outside the work day"
        assert w["until"] == work_end, key
    assert _mins(a["evening_run"]) >= _mins(d["day_end"])
    assert _mins(a["wiki"]) > _mins(a["evening_run"])


def test_external_automation_is_listed_because_it_cannot_be_re_registered():
    """Automation outside this repo (Codex app) is named here as a checklist.
    setup_scheduler.ps1 cannot retime it, so the only defence against it drifting
    back into their deep-work block is writing down what it should be."""
    d = _load()
    if "external" not in d["automation"]:
        return
    external = d["automation"]["external"]
    assert external, "if nothing external remains, delete the key rather than leaving it empty"
    for item in external:
        assert item["action"] in ("retire", "retime")
        assert item["reason"], item["id"]
        assert "repo" in item["where"] or "app" in item["where"]
        if item["action"] == "retime":
            assert HHMM_RE.match(item["at"]), item["id"]
        else:
            assert HHMM_RE.match(item["if_kept"]), item["id"]


def test_scheduler_reads_the_schedule_and_hard_codes_no_hour():
    src = SCHEDULER.read_text(encoding="utf-8")
    assert "day-schedule.json" in src
    code = "\n".join(
        line for line in src.splitlines()
        if not line.lstrip().startswith("#") and "Write-Host" not in line
    )
    # Every -At is a value from the JSON, never a literal like 7am or "09:00".
    for m in re.finditer(r"-At\s+(\S+)", code):
        assert m.group(1).startswith("$"), f"literal trigger time in setup_scheduler.ps1: {m.group(0)}"
    assert not re.search(r"-RepetitionDuration \(New-TimeSpan -Hours \d", code), "literal repetition window"
    for key in ("morning_run", "evening_run", "reflection", "wiki", "intraday_admin", "heartbeat", "slack_monitor"):
        assert f"$automation.{key}" in code, key


def test_heartbeat_active_hours_come_from_the_work_blocks():
    import heartbeat  # noqa: WPS433

    d = _load()
    work = [b for b in d["blocks"] if b["kind"] == "work"]
    expected = (int(work[0]["start"][:2]), int(work[-1]["end"][:2]))
    assert heartbeat.default_active_hours() == expected


def test_team_run_at_matches_the_windows():
    """agent_day.py splits teams by run_at hour (<12 morning); the manifests must
    name the same hours the scheduler fires at, or the /teams cadence label lies."""
    d = _load()
    a = d["automation"]
    for f in TEAMS.glob("*.json"):
        m = json.loads(f.read_text(encoding="utf-8"))
        if not m.get("enabled") or not m.get("producer"):
            continue
        run_at = m["run_at"]
        hour = int(run_at.split(":")[0])
        if hour < 12:
            assert run_at == a["morning_run"], f"{f.name}: morning team run_at {run_at} != {a['morning_run']}"
        else:
            assert run_at == a["evening_run"], f"{f.name}: evening team run_at {run_at} != {a['evening_run']}"


def main() -> int:
    """Same plain runner as the other test files here: no pytest dependency."""
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as exc:  # noqa: PERF203
            failed += 1
            print(f"FAIL {fn.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"ERROR {fn.__name__}: {type(exc).__name__}: {exc}")
    total = len(tests)
    print(f"\n{total - failed}/{total} day-schedule tests passed." if not failed
          else f"\n{failed} of {total} day-schedule tests FAILED.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
