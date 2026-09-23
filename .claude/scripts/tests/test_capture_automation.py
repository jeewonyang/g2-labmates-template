"""Regression tests for the capture-to-Prisma transaction bridge.

Uses one in-memory SQLite connection: no vault files, real inbox records, or
external models are touched.
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import capture_sync  # noqa: E402


def check(condition, label):
    if not condition:
        raise AssertionError(label)
    print(f"PASS {label}")


con = sqlite3.connect(":memory:")
con.row_factory = sqlite3.Row
con.executescript(
    """
    CREATE TABLE InboxItem (
      id TEXT PRIMARY KEY, type TEXT, rawText TEXT, parsedTitle TEXT,
      sourceUrl TEXT, dueDate INTEGER, projectId TEXT, areaId TEXT,
      status TEXT, processedIntoType TEXT, processedIntoId TEXT,
      updatedAt INTEGER
    );
    CREATE TABLE CaptureAutomation (
      id TEXT PRIMARY KEY, inboxItemId TEXT UNIQUE, state TEXT, mode TEXT,
      localJobId TEXT, verifierJobId TEXT, localDecision TEXT,
      verifiedDecision TEXT, effectiveDecision TEXT, confidence REAL,
      requiresReview INTEGER, error TEXT, destinationPath TEXT,
      completedAt INTEGER, updatedAt INTEGER
    );
    CREATE TABLE AutomationEvent (
      id TEXT PRIMARY KEY, automationId TEXT, type TEXT, actor TEXT,
      payload TEXT, createdAt INTEGER
    );
    CREATE TABLE Project (
      id TEXT PRIMARY KEY, title TEXT, archivedAt INTEGER, nextActionId TEXT,
      updatedAt INTEGER
    );
    CREATE TABLE Area (
      id TEXT PRIMARY KEY, title TEXT, archivedAt INTEGER
    );
    CREATE TABLE Task (
      id TEXT PRIMARY KEY, title TEXT, description TEXT, status TEXT,
      previousStatus TEXT, priority TEXT, context TEXT, isHighlight INTEGER,
      dueDate INTEGER, scheduledDate INTEGER, completedAt INTEGER,
      projectId TEXT, areaId TEXT, parentTaskId TEXT, createdAt INTEGER,
      updatedAt INTEGER, archivedAt INTEGER
    );
    CREATE TABLE Note (
      id TEXT PRIMARY KEY, title TEXT, contentMarkdown TEXT, type TEXT,
      pinned INTEGER, sourceUrl TEXT, date INTEGER, projectId TEXT,
      areaId TEXT, resourceId TEXT, createdAt INTEGER, updatedAt INTEGER,
      archivedAt INTEGER
    );
    CREATE TABLE Resource (
      id TEXT PRIMARY KEY, title TEXT, type TEXT, url TEXT, summary TEXT,
      status TEXT, projectId TEXT, areaId TEXT, createdAt INTEGER,
      updatedAt INTEGER, archivedAt INTEGER
    );
    CREATE TABLE EntityLink (
      id TEXT PRIMARY KEY, fromType TEXT, fromId TEXT, toType TEXT, toId TEXT,
      kind TEXT, createdAt INTEGER,
      UNIQUE(fromType,fromId,toType,toId,kind)
    );
    """
)

# sqlite3.Connection's context manager commits/rolls back but does not close,
# so every bridge call sees the same in-memory database.
capture_sync._connect = lambda: con
capture_sync.refresh_taskflow_snapshot = lambda: {}

now = capture_sync._now_ms()
con.execute(
    """INSERT INTO InboxItem
       VALUES ('inbox-1','unknown','Schedule focused writing tomorrow at 2pm',
               'Focused writing',NULL,NULL,NULL,NULL,'inbox',NULL,NULL,?)""",
    (now,),
)
con.execute(
    """INSERT INTO CaptureAutomation
       VALUES ('auto-1','inbox-1','ready','automatic',NULL,NULL,NULL,NULL,NULL,
               NULL,0,NULL,NULL,NULL,?)""",
    (now,),
)
con.commit()

job = {
    "job": "1000000000000-deadbeef",
    "payload": {"automationId": "auto-1", "inboxItemId": "inbox-1"},
}
decision = {
    "vault": "G2OS-Staging",
    "bucket": "20_Areas",
    "actions": [{
        "kind": "task",
        "title": "Focused writing",
        "details": "Write without distractions.",
        "priority": "high",
        "context": "computer",
        "due_date": "2026-07-28",
        "scheduled_date": "2026-07-28T14:00:00-07:00",
        "project": None,
        "area": None,
        "confidence": 0.94,
    }],
}

first = capture_sync.apply_capture(
    job, decision, "VAULT/G2OS-Staging/20_Areas/inbox-1.md")
check(first["applied"], "an approved capture applies")
check(con.execute("SELECT count(*) FROM Task").fetchone()[0] == 1,
      "one task is created")
check(con.execute("SELECT status FROM Task").fetchone()[0] == "scheduled",
      "a timed action becomes scheduled")
check(con.execute(
    "SELECT status FROM InboxItem WHERE id='inbox-1'").fetchone()[0] == "processed",
    "the inbox item is processed in the same transaction")
check(con.execute(
    "SELECT state FROM CaptureAutomation WHERE id='auto-1'").fetchone()[0] == "applied",
    "automation state is applied")

second = capture_sync.apply_capture(
    job, decision, "VAULT/G2OS-Staging/20_Areas/inbox-1.md")
check(second.get("deduplicated") is True, "retries are idempotent")
check(con.execute("SELECT count(*) FROM Task").fetchone()[0] == 1,
      "a retry creates no duplicate task")

con.execute(
    """INSERT INTO InboxItem
       VALUES ('inbox-2','note','Manual thought','Manual thought',NULL,NULL,
               NULL,NULL,'processed','note','manual-note',?)""",
    (now,),
)
con.execute(
    """INSERT INTO CaptureAutomation
       VALUES ('auto-2','inbox-2','overridden','manual',NULL,NULL,NULL,NULL,NULL,
               NULL,0,NULL,NULL,?,?)""",
    (now, now),
)
con.commit()
manual = capture_sync.apply_capture(
    {"job": "1000000000001-deadbeef",
     "payload": {"automationId": "auto-2", "inboxItemId": "inbox-2"}},
    decision,
    "ignored",
)
check(manual["applied"] is False, "manual overrides block automatic apply")
check(con.execute("SELECT count(*) FROM Task").fetchone()[0] == 1,
      "manual override creates no hidden duplicate")

corrected = capture_sync.correct_applied_capture(
    "inbox-1",
    {
        "kind": "note",
        "title": "Focused writing note",
        "details": "Corrected classification.",
    },
    actor="test",
)
check(corrected["corrected"], "an applied capture can be corrected")
check(con.execute(
    "SELECT archivedAt FROM Task WHERE id=?", (first["created"][0]["id"],)
).fetchone()[0] is not None, "the erroneous entity is recoverably archived")
check(con.execute("SELECT count(*) FROM Note").fetchone()[0] == 1,
      "the corrected entity is created")
check(con.execute(
    "SELECT processedIntoType FROM InboxItem WHERE id='inbox-1'"
).fetchone()[0] == "note", "the immutable capture points to the correction")
check(con.execute(
    "SELECT count(*) FROM AutomationEvent WHERE type='corrected'"
).fetchone()[0] == 1, "the correction is recorded in provenance")

print("\nAll capture automation tests passed.")
