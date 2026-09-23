"""Google Calendar integration (personal account): read events, and insert them.

Read was the whole of this module until 2026-07-26, when the owner authorized
event creation as the second permitted outbound write in the system (the first
being Gmail draft creation). See create_event() for the constraints that make
that safe, and CLAUDE.md's Advisor-mode rule for the authorization itself.

Insert only. There is deliberately no update, move, or delete function here:
adding one would put the never-delete rule and their existing calendar at the
mercy of a model's judgment about which event to overwrite.
"""

import re
import sys
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integrations.google_auth import build_service, require_scope  # noqa: E402
from shared import log_line, now, with_retry  # noqa: E402

TIMEZONE = "America/Los_Angeles"

# RFC3339 with a required offset, or a bare date for all-day events. Validated
# before the call so a malformed model output fails locally with a clear message
# instead of as an opaque 400 from Google.
_RFC3339 = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass
class CalendarEvent:
    id: str
    summary: str
    start: str
    end: str
    location: str
    all_day: bool


def upcoming_events(hours_ahead: int = 24, max_results: int = 20
                   ) -> list[CalendarEvent]:
    svc = build_service("calendar", "v3")
    time_min = now()
    time_max = time_min + timedelta(hours=hours_ahead)
    resp = with_retry(lambda: svc.events().list(
        calendarId="primary",
        timeMin=time_min.isoformat(), timeMax=time_max.isoformat(),
        singleEvents=True, orderBy="startTime", maxResults=max_results).execute())
    out = []
    for e in resp.get("items", []):
        start = e.get("start", {})
        end = e.get("end", {})
        out.append(CalendarEvent(
            id=e.get("id", ""), summary=e.get("summary", "(no title)"),
            start=start.get("dateTime", start.get("date", "")),
            end=end.get("dateTime", end.get("date", "")),
            location=e.get("location", ""), all_day="date" in start))
    return out


def create_event(*, summary: str, start: str, end: str, description: str = "",
                 location: str = "", all_day: bool = False,
                 calendar_id: str = "primary") -> str:
    """Insert one event. Returns its htmlLink. THE SECOND OUTBOUND WRITE.

    Only ever reached from admin_schedule_proposal.apply(), which apply_jobs.py
    calls exclusively for jobs already in the `approved` state - so every event
    created here was confirmed by the owner on /ops. Nothing in a job body can
    reach this function.

    Validates times locally rather than letting Google reject them, because the
    caller is a model: a malformed `start` should surface as "the model emitted
    a bad timestamp", not as a generic HTTP 400 three layers down.
    """
    if not summary.strip():
        raise ValueError("event summary is required")

    checker, key = (_DATE, "date") if all_day else (_RFC3339, "dateTime")
    for label, value in (("start", start), ("end", end)):
        if not checker.match(value or ""):
            raise ValueError(
                f"{label}={value!r} is not valid for "
                f"{'an all-day' if all_day else 'a timed'} event "
                f"(expected {'YYYY-MM-DD' if all_day else 'RFC3339 with offset'})")
    if end <= start:
        raise ValueError(f"end ({end}) must be after start ({start})")

    # Checked after local validation so a bad timestamp still reports as a bad
    # timestamp, and before the call so a missing scope reports as a missing
    # scope rather than an opaque 403 from Google.
    require_scope("https://www.googleapis.com/auth/calendar.events",
                  "Creating calendar events")

    body = {
        "summary": summary,
        "description": description,
        "location": location,
        "start": {key: start},
        "end": {key: end},
    }
    if not all_day:
        body["start"]["timeZone"] = TIMEZONE
        body["end"]["timeZone"] = TIMEZONE

    created = with_retry(lambda: svc_events().insert(
        calendarId=calendar_id, body=body).execute())

    link = created.get("htmlLink", "")
    log_line("calendar", f"created event {created.get('id', '?')} "
                         f"{start} {summary!r}")
    return link


def svc_events():
    return build_service("calendar", "v3").events()


def format_context(events: list[CalendarEvent]) -> str:
    if not events:
        return "No upcoming events."
    lines = [f"{len(events)} upcoming event(s):"]
    for e in events:
        when = e.start[:10] if e.all_day else e.start[:16].replace("T", " ")
        loc = f" @ {e.location}" if e.location else ""
        lines.append(f"- {when} {e.summary}{loc}")
    return "\n".join(lines)
