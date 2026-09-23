"""Regression tests for admin.schedule_proposal's apply(): the calendar write
plus the planner mirror (the owner, 2026-09-01 - an approved event must land on
the owner's planner, and a planner failure must never fail the job after the calendar
event already exists).

Run: python .claude/scripts/tests/test_schedule_proposal.py
"""

import sqlite3
import sys
import tempfile
import types
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import capture_sync  # noqa: E402
from jobs import admin_schedule_proposal as sp  # noqa: E402


def check(condition, label):
    if not condition:
        raise AssertionError(label)
    print(f"PASS {label}")


# --- fakes: calendar write, Prisma DB, vault log --------------------------

calendar_calls = []


def fake_create_event(**kwargs):
    calendar_calls.append(kwargs)
    if kwargs.get("summary") == "BROKEN":
        raise RuntimeError("synthetic calendar failure")
    return f"https://calendar.example/{len(calendar_calls)}"


# apply() imports lazily via `from integrations.calendar_integration import
# create_event`, so a namespace planted in sys.modules intercepts it without
# needing the Google client libraries installed.
sys.modules["integrations.calendar_integration"] = types.SimpleNamespace(
    create_event=fake_create_event)

con = sqlite3.connect(":memory:")
con.row_factory = sqlite3.Row
con.execute(
    """CREATE TABLE Task (
       id TEXT PRIMARY KEY, title TEXT, description TEXT, status TEXT,
       previousStatus TEXT, priority TEXT, context TEXT, isHighlight INTEGER,
       dueDate INTEGER, scheduledDate INTEGER, completedAt INTEGER,
       projectId TEXT, areaId TEXT, parentTaskId TEXT, createdAt INTEGER,
       updatedAt INTEGER, archivedAt INTEGER
    )"""
)
capture_sync._connect = lambda: con
capture_sync.refresh_taskflow_snapshot = lambda: {}

tmp_vault = Path(tempfile.mkdtemp())
sp.MEMORY = tmp_vault
sp.append_to_daily_log = lambda *a, **k: None


def job(jid="job_sptest01"):
    return {"job": jid,
            "payload": {"sender": "Dr. Ada Advisor", "subject": "F31 timing"}}


TIMED = {"summary": "Chat with Dr. Advisor", "start": "2026-09-03T14:00:00-07:00",
         "end": "2026-09-03T15:00:00-07:00", "confidence": 0.9,
         "source_quote": "Wednesday at 2pm"}
DEADLINE = {"summary": "DUE: F31 progress report", "start": "2026-09-05",
            "end": "2026-09-06", "all_day": True, "confidence": 0.9,
            "source_quote": "due September 5"}


# --- an approved proposal creates the events AND the planner rows ---------

sp.apply(job(), {"should_schedule": True, "events": [TIMED, DEADLINE]})

check(len(calendar_calls) == 2, "both approved events reach the calendar")

timed_row = con.execute(
    "SELECT * FROM Task WHERE title = ?", (TIMED["summary"],)).fetchone()
check(timed_row is not None, "a timed event lands in the planner")
check(timed_row["status"] == "scheduled" and timed_row["dueDate"] is None,
      "a timed event is a scheduled task, not a due one")
expected_ms = int(datetime.fromisoformat(TIMED["start"]).timestamp() * 1000)
check(timed_row["scheduledDate"] == expected_ms,
      "the planner task keeps the event's start time")
check("https://calendar.example/" in (timed_row["description"] or ""),
      "the planner task links back to the calendar event")

due_row = con.execute(
    "SELECT * FROM Task WHERE title = ?", (DEADLINE["summary"],)).fetchone()
check(due_row is not None, "an all-day DUE event lands in the planner")
check(due_row["dueDate"] is not None and due_row["scheduledDate"] is None,
      "a deadline carries dueDate, not a time slot")

log = tmp_vault / "admin" / "calendar-writes.md"
check(log.exists() and "planner" in log.read_text(encoding="utf-8"),
      "the audit log records the planner outcome")

# A re-apply of the same job may duplicate the calendar event (known
# non-idempotency, guarded by APPLY_LOCK) but must never duplicate the task.
sp.apply(job(), {"should_schedule": True, "events": [TIMED, DEADLINE]})
check(con.execute("SELECT count(*) FROM Task").fetchone()[0] == 2,
      "the agent-source marker keeps the planner mirror idempotent")


# --- one failing calendar event does not lose the rest --------------------

calendar_calls.clear()
broken = dict(TIMED, summary="BROKEN")
ok = dict(TIMED, summary="Survivor meeting")
try:
    sp.apply(job("job_sptest02"),
             {"should_schedule": True, "events": [broken, ok]})
    raised = False
except RuntimeError:
    raised = True
check(raised, "a failed calendar write still fails the job loudly")
check(con.execute("SELECT count(*) FROM Task WHERE title='Survivor meeting'")
      .fetchone()[0] == 1,
      "the surviving event still lands in the planner")
check(con.execute("SELECT count(*) FROM Task WHERE title='BROKEN'")
      .fetchone()[0] == 0,
      "no planner row for an event that never reached the calendar")


# --- a planner failure never fails the job after the calendar write -------

original = capture_sync.create_external_followup_task
capture_sync.create_external_followup_task = (
    lambda **kw: (_ for _ in ()).throw(RuntimeError("planner down")))
try:
    sp.apply(job("job_sptest03"),
             {"should_schedule": True,
              "events": [dict(TIMED, summary="Planner-down meeting")]})
finally:
    capture_sync.create_external_followup_task = original
check("planner mirror FAILED" in log.read_text(encoding="utf-8"),
      "a planner failure is recorded, not raised - the event already exists")


# --- low-confidence events are dropped before the proposal is stored ------

filtered = {"should_schedule": True, "rationale": "two candidates",
            "events": [dict(TIMED, summary="Real meeting", confidence=0.9),
                       dict(TIMED, summary="Maybe webinar", confidence=0.3)]}
sp.on_result(job("job_sptest04"), filtered)
check([e["summary"] for e in filtered["events"]] == ["Real meeting"],
      "a sub-threshold event is dropped before review")
check("dropped before review" in filtered["rationale"],
      "the drop is stated in the rationale the owner reviews")

all_low = {"should_schedule": True, "rationale": "",
           "events": [dict(TIMED, confidence=0.2)]}
sp.on_result(job("job_sptest05"), all_low)
check(all_low["events"] == [] and sp.needs_human(all_low) is False,
      "a proposal with only low-confidence events auto-completes")

no_conf = {"should_schedule": True, "rationale": "",
           "events": [{k: v for k, v in TIMED.items() if k != "confidence"}]}
sp.on_result(job("job_sptest06"), no_conf)
check(len(no_conf["events"]) == 1,
      "an event with no parseable confidence is kept for review, not dropped")


print("\nall schedule-proposal checks passed")
