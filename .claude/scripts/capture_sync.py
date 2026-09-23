"""Bridge Agent OS capture decisions into the Prisma dashboard.

The agent pipeline owns reasoning; Prisma owns current operational state. This
module is the narrow transaction boundary between them:

  local triage result -> CaptureAutomation.localDecision
  verifier verdict    -> CaptureAutomation.verifiedDecision
  approved apply      -> Task/Note/Resource + InboxItem + provenance events

It uses SQLite directly so the scheduled agent does not depend on the Next
server being online. Every write is transactional and idempotent. No source is
deleted, and external calendar writes remain in admin.schedule_proposal.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shared import REPO_ROOT, STATE_DIR, atomic_write_json, log_line  # noqa: E402

DB = REPO_ROOT / "prisma" / "dev.db"
TZ = ZoneInfo("America/Los_Angeles")
TERMINAL = {"applied", "overridden"}
TASKFLOW = STATE_DIR / "agent-taskflow.json"


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _now_ms() -> int:
    return int(datetime.now().timestamp() * 1000)


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=30000")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def _event(con, automation_id: str, event_type: str, actor: str,
           payload=None) -> None:
    con.execute(
        """INSERT INTO AutomationEvent
           (id, automationId, type, actor, payload, createdAt)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (_id("aevt"), automation_id, event_type, actor,
         _json(payload) if payload is not None else None, _now_ms()),
    )


def _automation(con, automation_id: str):
    return con.execute(
        """SELECT a.*, i.status AS inboxStatus, i.rawText, i.parsedTitle,
                  i.type AS inboxType, i.sourceUrl, i.dueDate,
                  i.projectId AS inboxProjectId, i.areaId AS inboxAreaId
           FROM CaptureAutomation a
           JOIN InboxItem i ON i.id = a.inboxItemId
           WHERE a.id = ?""",
        (automation_id,),
    ).fetchone()


def record_local(job: dict, result: dict) -> None:
    payload = job.get("payload") or {}
    automation_id = payload.get("automationId")
    if not automation_id:
        return
    try:
        with _connect() as con:
            row = _automation(con, automation_id)
            if not row or row["state"] in TERMINAL:
                return
            confidence = result.get("confidence")
            con.execute(
                """UPDATE CaptureAutomation
                   SET state='verifying', localDecision=?, confidence=?,
                       error=NULL, updatedAt=?
                   WHERE id=?""",
                (_json(result), float(confidence) if isinstance(confidence, (int, float))
                 else None, _now_ms(), automation_id),
            )
            _event(con, automation_id, "local_triage_completed", "ollama", {
                "jobId": job.get("job"),
                "decision": result,
            })
    except sqlite3.Error as exc:
        log_line("capture-automation", f"record_local failed: {exc!r}")


def record_verifier_queued(automation_id: str, verifier_job_id: str) -> None:
    try:
        with _connect() as con:
            row = _automation(con, automation_id)
            if not row or row["state"] in TERMINAL:
                return
            con.execute(
                """UPDATE CaptureAutomation
                   SET state='verifying', verifierJobId=?, updatedAt=?
                   WHERE id=?""",
                (verifier_job_id, _now_ms(), automation_id),
            )
            _event(con, automation_id, "verification_queued", "agent-os", {
                "jobId": verifier_job_id,
            })
    except sqlite3.Error as exc:
        log_line("capture-automation", f"record_verifier_queued failed: {exc!r}")


def record_verdict(source_job: dict, verdict: dict, proposal: dict) -> None:
    payload = source_job.get("payload") or {}
    automation_id = payload.get("automationId")
    if not automation_id:
        return
    name = verdict.get("verdict", "uncertain")
    state = "ready" if name == "confirm" else "needs_review"
    try:
        with _connect() as con:
            row = _automation(con, automation_id)
            if not row or row["state"] in TERMINAL:
                return
            con.execute(
                """UPDATE CaptureAutomation
                   SET state=?, verifiedDecision=?, effectiveDecision=?,
                       requiresReview=?, error=NULL, updatedAt=?
                   WHERE id=?""",
                (state, _json(verdict), _json(proposal),
                 0 if name == "confirm" else 1, _now_ms(), automation_id),
            )
            _event(con, automation_id, "verification_completed",
                   "claude-review", {
                       "verdict": name,
                       "note": verdict.get("note", ""),
                       "actionsVerdict": verdict.get("actions_verdict"),
                   })
    except sqlite3.Error as exc:
        log_line("capture-automation", f"record_verdict failed: {exc!r}")


def record_reclassification(source_job: dict, replacement_job_id: str,
                            folder: str, *, actor: str) -> None:
    """Point a capture at the second local pass after reviewed folder creation."""
    payload = source_job.get("payload") or {}
    automation_id = payload.get("automationId")
    if not automation_id:
        return
    try:
        with _connect() as con:
            row = _automation(con, automation_id)
            if not row or row["state"] in TERMINAL:
                return
            con.execute(
                """UPDATE CaptureAutomation
                   SET state='local_triage', localJobId=?, verifierJobId=NULL,
                       requiresReview=0, error=NULL, updatedAt=?
                   WHERE id=?""",
                (replacement_job_id, _now_ms(), automation_id),
            )
            _event(
                con, automation_id, "folder_created_reclassification_queued",
                actor, {
                    "previousJobId": source_job.get("job"),
                    "jobId": replacement_job_id,
                    "folder": folder,
                },
            )
    except sqlite3.Error as exc:
        log_line("capture-automation",
                 f"record_reclassification failed: {exc!r}")


def record_failure(job: dict, error: str) -> None:
    automation_id = (job.get("payload") or {}).get("automationId")
    if not automation_id:
        return
    try:
        with _connect() as con:
            row = _automation(con, automation_id)
            if not row or row["state"] in TERMINAL:
                return
            con.execute(
                """UPDATE CaptureAutomation
                   SET state='failed', error=?, updatedAt=?
                   WHERE id=?""",
                (str(error)[:2000], _now_ms(), automation_id),
            )
            _event(con, automation_id, "failed", "agent-os",
                   {"error": str(error)[:1000]})
    except sqlite3.Error as exc:
        log_line("capture-automation", f"record_failure failed: {exc!r}")


def _parse_date(value) -> int | None:
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    try:
        if len(text) == 10:
            dt = datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=TZ)
        else:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=TZ)
        return int(dt.timestamp() * 1000)
    except ValueError:
        return None


def _match_entity(con, table: str, hint, fallback_id) -> str | None:
    if fallback_id:
        found = con.execute(
            f"SELECT id FROM {table} WHERE id=? AND archivedAt IS NULL",
            (fallback_id,),
        ).fetchone()
        if found:
            return found["id"]
    if not hint or not isinstance(hint, str):
        return None
    exact = con.execute(
        f"""SELECT id FROM {table}
            WHERE lower(title)=lower(?) AND archivedAt IS NULL LIMIT 2""",
        (hint.strip(),),
    ).fetchall()
    return exact[0]["id"] if len(exact) == 1 else None


def refresh_taskflow_snapshot() -> dict:
    """Publish the current Prisma taskflow for every agent runtime.

    The snapshot is operational metadata only: titles, dates, relationships,
    and automation states. It never includes inbox raw text or note bodies.
    """
    with _connect() as con:
        projects = [
            dict(row) for row in con.execute(
                """SELECT p.id, p.title, p.status, p.priority, p.targetDate,
                          p.nextActionId, t.title AS nextAction
                   FROM Project p
                   LEFT JOIN Task t ON t.id = p.nextActionId
                   WHERE p.archivedAt IS NULL AND p.status='active'
                   ORDER BY p.updatedAt DESC LIMIT 50"""
            ).fetchall()
        ]
        tasks = [
            dict(row) for row in con.execute(
                """SELECT t.id, t.title, t.status, t.priority, t.context,
                          t.dueDate, t.scheduledDate, t.projectId,
                          p.title AS project
                   FROM Task t
                   LEFT JOIN Project p ON p.id = t.projectId
                   WHERE t.archivedAt IS NULL
                     AND t.status NOT IN ('completed','canceled')
                   ORDER BY t.isHighlight DESC,
                            coalesce(t.dueDate,t.scheduledDate,9223372036854775807),
                            t.updatedAt DESC LIMIT 100"""
            ).fetchall()
        ]
        states = {
            row["state"]: row["n"] for row in con.execute(
                """SELECT state, count(*) AS n FROM CaptureAutomation
                   GROUP BY state"""
            ).fetchall()
        }
    snapshot = {
        "generatedAt": datetime.now(TZ).isoformat(timespec="seconds"),
        "timezone": "America/Los_Angeles",
        "automation": states,
        "activeProjects": projects,
        "openTasks": tasks,
    }
    atomic_write_json(TASKFLOW, snapshot)
    return snapshot


def _insert_task(con, row, action: dict) -> str:
    now = _now_ms()
    task_id = _id("task")
    scheduled = _parse_date(action.get("scheduled_date"))
    due = _parse_date(action.get("due_date")) or row["dueDate"]
    project_id = _match_entity(
        con, "Project", action.get("project"), row["inboxProjectId"])
    area_id = _match_entity(
        con, "Area", action.get("area"), row["inboxAreaId"])
    status = "scheduled" if scheduled is not None else "next"
    priority = action.get("priority")
    if priority not in {"low", "medium", "high", "urgent"}:
        priority = "medium"
    con.execute(
        """INSERT INTO Task
           (id,title,description,status,previousStatus,priority,context,isHighlight,dueDate,
            scheduledDate,completedAt,projectId,areaId,parentTaskId,createdAt,
            updatedAt,archivedAt)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (task_id, str(action.get("title") or row["parsedTitle"] or "Untitled")[:300],
         str(action.get("details") or row["rawText"])[:10000],
         status, None, priority, str(action.get("context") or "")[:60] or None, 0,
         due, scheduled, None, project_id, area_id, None, now, now, None),
    )
    if project_id:
        con.execute(
            """UPDATE Project SET nextActionId=?, updatedAt=?
               WHERE id=? AND nextActionId IS NULL""",
            (task_id, now, project_id),
        )
    return task_id


def create_external_followup_task(
        *, source: str, source_id: str, title: str, description: str,
        priority: str = "medium", context: str | None = None,
        scheduled_at: datetime | None = None,
        due_at: datetime | None = None) -> dict:
    """Create one idempotent internal task for an external incoming request.

    This is the scheduled-agent counterpart to the capture bridge. Slack and
    other read-only monitors may create a dashboard action without fabricating
    an InboxItem or waiting for a cloud model. The opaque source marker is
    stored in the description because Task has no source-id column; it makes
    retries safe and keeps the origin visible without enabling any outbound
    action.
    """
    safe_source = "".join(ch for ch in str(source) if ch.isalnum() or ch in "-_")[:40]
    safe_id = "".join(
        ch for ch in str(source_id) if ch.isalnum() or ch in "-_.:"
    )[:240]
    if not safe_source or not safe_id:
        raise ValueError("source and source_id are required")
    marker = f"[agent-source:{safe_source}:{safe_id}]"
    now_ms = _now_ms()
    scheduled_ms = int(scheduled_at.timestamp() * 1000) if scheduled_at else None
    # A deadline-shaped follow-up (an approved DUE calendar entry) carries a
    # dueDate instead of a scheduledDate, so it reads as due, not as a slot.
    due_ms = int(due_at.timestamp() * 1000) if due_at else None
    if priority not in {"low", "medium", "high", "urgent"}:
        priority = "medium"

    with _connect() as con:
        existing = con.execute(
            """SELECT id, title FROM Task
               WHERE archivedAt IS NULL AND description LIKE ?
               ORDER BY createdAt DESC LIMIT 1""",
            (f"%{marker}%",),
        ).fetchone()
        if existing:
            return {
                "task_id": existing["id"],
                "title": existing["title"],
                "created": False,
            }

        task_id = _id("task")
        body = f"{str(description).strip()[:9500]}\n\n{marker}".strip()
        con.execute(
            """INSERT INTO Task
               (id,title,description,status,previousStatus,priority,context,
                isHighlight,dueDate,scheduledDate,completedAt,projectId,areaId,
                parentTaskId,createdAt,updatedAt,archivedAt)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                task_id, str(title).strip()[:300] or "External follow-up",
                body, "scheduled" if scheduled_ms is not None else "next",
                None, priority, str(context).strip()[:60] if context else None,
                0, due_ms, scheduled_ms, None, None, None, None,
                now_ms, now_ms, None,
            ),
        )

    refresh_taskflow_snapshot()
    return {"task_id": task_id, "title": str(title).strip()[:300], "created": True}


def _insert_note(con, row, action: dict) -> str:
    now = _now_ms()
    note_id = _id("note")
    project_id = _match_entity(
        con, "Project", action.get("project"), row["inboxProjectId"])
    area_id = _match_entity(
        con, "Area", action.get("area"), row["inboxAreaId"])
    note_type = "journal" if row["inboxType"] == "journal" else "fleeting"
    con.execute(
        """INSERT INTO Note
           (id,title,contentMarkdown,type,pinned,sourceUrl,date,projectId,areaId,
            resourceId,createdAt,updatedAt,archivedAt)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (note_id, str(action.get("title") or row["parsedTitle"] or "Untitled")[:300],
         str(action.get("details") or row["rawText"])[:200000],
         note_type, 0, row["sourceUrl"], None, project_id, area_id, None,
         now, now, None),
    )
    return note_id


def _insert_resource(con, row, action: dict) -> str:
    now = _now_ms()
    resource_id = _id("resource")
    project_id = _match_entity(
        con, "Project", action.get("project"), row["inboxProjectId"])
    area_id = _match_entity(
        con, "Area", action.get("area"), row["inboxAreaId"])
    con.execute(
        """INSERT INTO Resource
           (id,title,type,url,summary,status,projectId,areaId,createdAt,updatedAt,
            archivedAt)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (resource_id,
         str(action.get("title") or row["parsedTitle"] or "Untitled")[:300],
         "article" if row["sourceUrl"] else "other", row["sourceUrl"],
         str(action.get("details") or row["rawText"])[:20000],
         "saved", project_id, area_id, now, now, None),
    )
    return resource_id


def correct_applied_capture(inbox_id: str, action: dict, *,
                            actor: str = "owner") -> dict:
    """Replace an erroneous automated entity without deleting the old record.

    The prior Task/Note/Resource is soft-archived for recovery and provenance;
    the immutable InboxItem is repointed to the corrected entity in the same
    transaction.
    """
    kind = action.get("kind") if isinstance(action, dict) else None
    if kind not in {"task", "note", "resource"}:
        raise ValueError("correction kind must be task, note, or resource")

    with _connect() as con:
        con.execute("BEGIN IMMEDIATE")
        source = con.execute(
            """SELECT i.processedIntoType, i.processedIntoId,
                      a.id AS automationId, a.state, a.effectiveDecision
               FROM InboxItem i
               JOIN CaptureAutomation a ON a.inboxItemId=i.id
               WHERE i.id=?""",
            (inbox_id,),
        ).fetchone()
        if not source:
            con.rollback()
            raise ValueError("capture automation not found")
        if source["state"] != "applied":
            con.rollback()
            raise ValueError(f"capture is {source['state']}; expected applied")
        row = _automation(con, source["automationId"])
        if not row:
            con.rollback()
            raise ValueError("capture automation identity mismatch")

        old_type = source["processedIntoType"]
        old_id = source["processedIntoId"]
        if old_type in {"task", "note", "resource"} and old_id:
            table = {"task": "Task", "note": "Note", "resource": "Resource"}[old_type]
            con.execute(
                f"UPDATE {table} SET archivedAt=?, updatedAt=? "
                "WHERE id=? AND archivedAt IS NULL",
                (_now_ms(), _now_ms(), old_id),
            )

        if kind == "task":
            created_id = _insert_task(con, row, action)
        elif kind == "resource":
            created_id = _insert_resource(con, row, action)
        else:
            created_id = _insert_note(con, row, action)

        con.execute(
            """INSERT OR IGNORE INTO EntityLink
               (id,fromType,fromId,toType,toId,kind,createdAt)
               VALUES (?,?,?,?,?,?,?)""",
            (_id("link"), "inbox", inbox_id, kind, created_id,
             "corrected_automated_from", _now_ms()),
        )
        con.execute(
            """UPDATE InboxItem
               SET processedIntoType=?, processedIntoId=?, updatedAt=?
               WHERE id=?""",
            (kind, created_id, _now_ms(), inbox_id),
        )
        try:
            effective = json.loads(source["effectiveDecision"] or "{}")
        except (TypeError, json.JSONDecodeError):
            effective = {}
        if not isinstance(effective, dict):
            effective = {}
        effective["actions"] = [action]
        con.execute(
            """UPDATE CaptureAutomation
               SET effectiveDecision=?, requiresReview=0, error=NULL,
                   completedAt=?, updatedAt=? WHERE id=?""",
            (_json(effective), _now_ms(), _now_ms(), source["automationId"]),
        )
        _event(con, source["automationId"], "corrected", actor, {
            "from": {"type": old_type, "id": old_id},
            "to": {"type": kind, "id": created_id},
            "reason": "automated triage correction",
        })
        con.commit()

    try:
        refresh_taskflow_snapshot()
    except (OSError, sqlite3.Error) as exc:
        log_line("capture-automation", f"taskflow snapshot failed: {exc!r}")

    # Their correction is a teaching signal: "this capture became a note but
    # should have been a task" is exactly the tendency the classifier prompt
    # learns from. Best-effort - the Prisma correction above already committed.
    if actor == "owner" and old_type != kind:
        try:
            from triage import lessons
            lessons.record(
                "applied-capture-correction",
                title=row["parsedTitle"] or (row["rawText"] or "")[:80],
                old={"action_kind": old_type},
                new={"action_kind": kind},
                by=actor,
            )
        except Exception as exc:  # noqa: BLE001
            log_line("capture-automation", f"lesson record failed: {exc!r}")

    return {
        "corrected": True,
        "from": {"type": old_type, "id": old_id},
        "to": {"type": kind, "id": created_id},
    }


def apply_capture(job: dict, result: dict, destination_path: str | None) -> dict:
    payload = job.get("payload") or {}
    automation_id = payload.get("automationId")
    inbox_id = payload.get("inboxItemId")
    if not automation_id or not inbox_id:
        return {"applied": False, "reason": "not a G2 capture"}

    with _connect() as con:
        con.execute("BEGIN IMMEDIATE")
        row = _automation(con, automation_id)
        if not row or row["inboxItemId"] != inbox_id:
            con.rollback()
            raise ValueError("capture automation identity mismatch")
        if row["state"] == "applied":
            con.rollback()
            return {"applied": True, "deduplicated": True}
        if row["state"] == "overridden" or row["inboxStatus"] != "inbox":
            con.rollback()
            return {"applied": False, "reason": "manually handled"}

        actions = result.get("actions") if isinstance(result, dict) else None
        if not isinstance(actions, list):
            actions = []
        accepted = []
        for action in actions[:10]:
            if not isinstance(action, dict):
                continue
            kind = action.get("kind")
            confidence = action.get("confidence", 0)
            try:
                confidence = float(confidence)
            except (TypeError, ValueError):
                confidence = 0
            if kind in {"task", "note", "resource"} and confidence >= 0.65:
                accepted.append(action)

        # A capture is always knowledge even when it contains no actionable
        # commitment. Preserve it as a note rather than silently marking it done.
        if not accepted:
            accepted = [{
                "kind": "note",
                "title": row["parsedTitle"] or "Captured thought",
                "details": row["rawText"],
                "confidence": 1.0,
            }]

        created = []
        for action in accepted:
            kind = action["kind"]
            if kind == "task":
                entity_id = _insert_task(con, row, action)
            elif kind == "resource":
                entity_id = _insert_resource(con, row, action)
            else:
                entity_id = _insert_note(con, row, action)
            created.append({"type": kind, "id": entity_id,
                            "title": action.get("title")})
            con.execute(
                """INSERT OR IGNORE INTO EntityLink
                   (id,fromType,fromId,toType,toId,kind,createdAt)
                   VALUES (?,?,?,?,?,?,?)""",
                (_id("link"), "inbox", inbox_id, kind, entity_id,
                 "automated_from", _now_ms()),
            )

        primary = created[0]
        processed_type = primary["type"] if len(created) == 1 else "multiple"
        con.execute(
            """UPDATE InboxItem
               SET status='processed', processedIntoType=?, processedIntoId=?,
                   updatedAt=? WHERE id=? AND status='inbox'""",
            (processed_type, primary["id"], _now_ms(), inbox_id),
        )
        con.execute(
            """UPDATE CaptureAutomation
               SET state='applied', destinationPath=?, effectiveDecision=?,
                   requiresReview=0, error=NULL, completedAt=?, updatedAt=?
               WHERE id=?""",
            (destination_path, _json(result), _now_ms(), _now_ms(),
             automation_id),
        )
        _event(con, automation_id, "applied", "agent-os", {
            "destinationPath": destination_path,
            "created": created,
            "sourceJob": job.get("job"),
        })
        con.commit()
    try:
        refresh_taskflow_snapshot()
    except (OSError, sqlite3.Error) as exc:
        log_line("capture-automation", f"taskflow snapshot failed: {exc!r}")
    # External calendar writes keep their independent, explicit approval gate.
    # Only cloud-safe captures enqueue this metadata-only proposal; private or
    # confidential thoughts still get an internally scheduled G2 task but
    # never send their content to the cloud calendar reasoner.
    if result.get("vault") == "G2OS-Staging":
        for action in accepted:
            if not action.get("calendar_event") or not action.get("scheduled_date"):
                continue
            try:
                import ledger
                schedule_id = ledger.create(
                    "admin.schedule_proposal",
                    {
                        "source": "g2-capture-automation",
                        "sender": "the owner via G2",
                        "subject": action.get("title", ""),
                        "date": action.get("scheduled_date", ""),
                        "body": (
                            f"Create this event if the structured timing is definite.\n"
                            f"Title: {action.get('title', '')}\n"
                            f"Start: {action.get('scheduled_date', '')}\n"
                            f"Duration minutes: {action.get('duration_minutes') or 60}\n"
                            f"Context: {str(action.get('details') or '')[:1000]}"
                        ),
                        "upcoming_events": [],
                    },
                    runtime="claude",
                    sensitivity="internal",
                    parent=job.get("job"),
                )
                with _connect() as con:
                    _event(con, automation_id, "calendar_proposal_queued",
                           "agent-os", {"jobId": schedule_id})
            except Exception as exc:
                log_line("capture-automation",
                         f"calendar proposal enqueue failed: {exc!r}")
    return {"applied": True, "created": created}


def main() -> int:
    """Narrow CLI so the dashboard can invoke a correction as a subprocess.

    Only `correct` is exposed: the other entry points in this module are
    called in-process by the agent pipeline and need no shell surface.
    """
    if len(sys.argv) >= 4 and sys.argv[1] == "correct":
        actor = "owner"
        if "--by" in sys.argv:
            i = sys.argv.index("--by")
            if i + 1 < len(sys.argv):
                actor = sys.argv[i + 1]
        try:
            action = json.loads(sys.argv[3])
        except json.JSONDecodeError as exc:
            print(f"invalid action JSON: {exc}", file=sys.stderr)
            return 2
        try:
            out = correct_applied_capture(sys.argv[2], action, actor=actor)
        except (ValueError, sqlite3.Error) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(json.dumps(out, ensure_ascii=False))
        return 0
    print("usage: capture_sync.py correct <inbox-item-id> <action-json> "
          "[--by NAME]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
