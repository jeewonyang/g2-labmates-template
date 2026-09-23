"""Heartbeat, ledger-native: enqueue one job per actionable item.

The original heartbeat built a single mega-prompt covering every delta and made
one SDK call. That coupled unrelated work: a malformed Gmail item could poison
the whole run, retry meant redoing everything, and per-message cost was
invisible.

This produces jobs instead. The deterministic stages are reused unchanged from
heartbeat.py - gather, snapshot, diff - and every item still passes through
sanitize.py before it becomes a payload. The trust boundary moves earlier; it
does not disappear. Untrusted content lands in a payload as DATA, and
draft_reply.py restates the boundary in its own prompt.

  python .claude/scripts/heartbeat_produce.py --dry-run   # show what it would enqueue
  python .claude/scripts/heartbeat_produce.py             # enqueue (respects active hours)
  python .claude/scripts/heartbeat_produce.py --force     # ignore active hours

Then drain: python .claude/scripts/dispatch.py --once
"""

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Recursion guard, same as every other SDK/CLI entry point.
os.environ.setdefault("CLAUDE_INVOKED_BY", "heartbeat-produce")

import heartbeat  # noqa: E402  (reuses gather/snapshot/diff/active-hours)
import ledger  # noqa: E402
from sanitize import sanitize  # noqa: E402
from shared import log_line, now, read_json  # noqa: E402

# Which integrations produce reply drafts. Calendar and papers are informational
# - they belong in the daily log, not in a reply queue.
DRAFTABLE = {"gmail"}
MAX_PER_INTEGRATION = 15
MAX_SELF_SENT = 20
MAX_GMAIL_BODY_CHARS = 12_000


_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _field(text: str, limit: int = 200) -> str:
    """Clean a SHORT structured field - sender, subject.

    Deliberately not sanitize(): that wraps its input in an <external_data>
    block, which is right for free text going into a prompt but wrong here.
    These values become a draft's filename slug and YAML frontmatter, so a
    wrapper would end up embedded in both. Strip control characters, collapse
    newlines (which would break frontmatter), and truncate.
    """
    return _CTRL.sub("", (text or "").replace("\n", " ").replace("\r", " ")).strip()[:limit]


def _gmail_payload(m) -> dict:
    """Sanitize before the content ever becomes a job payload."""
    from integrations import gmail_integration as gm

    source_text = getattr(m, "body", "") or getattr(m, "snippet", "") or ""
    body, flags = sanitize(source_text[:MAX_GMAIL_BODY_CHARS], source="gmail")
    attachment_names = [
        _field(name, 240)
        for name in (getattr(m, "attachment_names", []) or [])[:20]
        if _field(name, 240)
    ]
    outer_sender = _field(getattr(m, "sender", ""))
    self_sent = gm.is_self_sender(outer_sender)
    forwarded = {}
    if self_sent:
        structured_sender = getattr(m, "forwarded_sender", "") or ""
        if structured_sender:
            forwarded = {
                "from": structured_sender,
                "subject": getattr(m, "forwarded_subject", "") or "",
            }
        else:
            forwarded = gm.extract_forwarded_headers(source_text)
    sender = _field(forwarded.get("from", "")) or outer_sender
    subject = (
        _field(forwarded.get("subject", ""))
        or _field(getattr(m, "subject", ""))
    )
    return {
        "source": "email",
        "source_id": _field(getattr(m, "id", ""), 120),
        "thread_id": _field(getattr(m, "thread_id", ""), 120),
        "sender": sender,
        "outer_sender": outer_sender,
        "subject": subject,
        "date": _field(getattr(m, "date", ""), 200),
        "body": body,                 # wrapped: this is free text for the prompt
        "attachment_names": attachment_names,
        "self_sent": self_sent,
        "forwarded_sender_found": gm.is_replyable_forwarded_sender(
            forwarded.get("from", "")
        ),
        "raw_data_hint": _raw_data_hint(
            getattr(m, "subject", ""), source_text, attachment_names),
        "sanitize_flags": list(flags) if flags else [],
    }


_RAW_DATA_EXTENSIONS = {
    ".csv", ".tsv", ".xlsx", ".xls", ".json", ".zip", ".gz", ".fcs",
    ".tif", ".tiff", ".nd2", ".czi", ".mat", ".h5", ".hdf5", ".fastq",
    ".fastq.gz", ".fasta", ".fa", ".txt",
}
_RAW_DATA_TERMS = re.compile(
    r"\b(?:raw data|dataset|data file|source data|process (?:this|the) data"
    r"|analy[sz]e (?:this|the) data|attached results?)\b",
    re.IGNORECASE,
)


def _raw_data_hint(subject: str, body: str,
                   attachment_names: list[str]) -> bool:
    """Cheap routing hint; the extraction job still proposes the exact action."""
    for name in attachment_names:
        lower = name.lower()
        if any(lower.endswith(ext) for ext in _RAW_DATA_EXTENSIONS):
            return True
    return bool(_RAW_DATA_TERMS.search(f"{subject or ''}\n{body or ''}"))


def should_draft_reply(payload: dict) -> bool:
    """Draft ordinary mail and self-forwarded mail with an original sender."""
    if not payload.get("self_sent"):
        return True
    return bool(payload.get("forwarded_sender_found"))


def collect(data: dict, delta: dict) -> list[dict]:
    """Turn Gmail deltas into Admin payloads, prioritizing self-sent intake."""
    out = []
    for integ, ids in delta.items():
        if integ not in DRAFTABLE:
            continue
        wanted = set(ids)
        items = [m for m in data.get(integ, []) if getattr(m, "id", None) in wanted]
        payloads = [_gmail_payload(m) for m in items]
        self_payloads = [
            p for p in payloads if p.get("self_sent")
        ][:MAX_SELF_SENT]
        other_payloads = [
            p for p in payloads if not p.get("self_sent")
        ][:MAX_PER_INTEGRATION]
        out.extend(self_payloads + other_payloads)
    return out


# A message earns an admin.schedule_proposal job only if it plausibly contains a
# date or time. Cheap, deterministic, and transparent - the alternative is
# spending a model call per message to discover that most mail has no date in
# it. False positives are harmless (the job returns should_schedule false and
# auto-completes without ever reaching the review queue - see
# admin_schedule_proposal.needs_human); false negatives just mean no calendar
# suggestion for that message.
_DATEISH = re.compile(
    r"\b(?:mon|tues|wednes|thurs|fri|satur|sun)day\b"
    r"|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}\b"
    r"|\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b"
    r"|\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b"
    r"|\b(?:tomorrow|next week|this week|deadline|due date|rsvp)\b"
    r"|\b(?:meeting|seminar|schedule[ds]?|reschedul|appointment|calendar invite)\b",
    re.IGNORECASE)


def looks_scheduleable(payload: dict) -> bool:
    return bool(_DATEISH.search(
        f"{payload.get('subject', '')} {payload.get('body', '')}"))


def _calendar_context(data: dict) -> list[dict]:
    """The owner's upcoming events, so a proposal can avoid duplicating one."""
    out = []
    for e in data.get("calendar", []) or []:
        out.append({
            "summary": _field(getattr(e, "summary", ""), 120),
            "start": getattr(e, "start", ""),
            "end": getattr(e, "end", ""),
        })
    return out


def should_reflect() -> str | None:
    """Once per calendar day, same guard the old maybe_reflect() used."""
    state = read_json(heartbeat.STATE_FILE, {}) or {}
    today = f"{now():%Y-%m-%d}"
    if state.get("reflection_date") == today:
        return None
    from jobs import memory_reflect_job
    return memory_reflect_job.default_date()


def main() -> int:
    force = "--force" in sys.argv
    dry = "--dry-run" in sys.argv

    if not force and not heartbeat.within_active_hours():
        print("outside active hours (use --force to override)")
        return 0

    data, errors = heartbeat.gather()
    for e in errors:
        log_line("heartbeat", f"produce: gather error {e}")

    snapshot = heartbeat.build_snapshot(
        data.get("gmail", []), data.get("calendar", []),
        data.get("github", []), data.get("papers", []))
    previous = (read_json(heartbeat.STATE_FILE, {}) or {}).get("snapshot", {})
    delta = heartbeat.diff_snapshot(snapshot, previous)

    payloads = collect(data, delta)
    reflect_date = should_reflect()

    calendar_ctx = _calendar_context(data)
    scheduleable = [p for p in payloads if looks_scheduleable(p)]
    replyable = [p for p in payloads if should_draft_reply(p)]
    self_sent = [p for p in payloads if p.get("self_sent")]
    raw_data = [p for p in self_sent if p.get("raw_data_hint")]

    if dry:
        print(f"gather errors     : {len(errors)}")
        for integ, ids in delta.items():
            print(f"  delta {integ:16s} {len(ids)} new")
        print(f"self-sent intake  : {len(self_sent)} "
              f"({len(raw_data)} raw-data hint)")
        print(f"draft.reply jobs  : {len(replyable)}")
        for p in payloads[:5]:
            print(f"    {p['sender'][:38]:40s} {p['subject'][:44]}")
        print(f"admin.extract_commitments : {len(payloads)}")
        print(f"admin.schedule_proposal   : {len(scheduleable)} "
              f"(date-bearing of {len(payloads)})")
        print(f"memory.reflect    : {reflect_date or '(already ran today)'}")
        return 0

    created = 0
    for p in payloads:
        if should_draft_reply(p):
            ledger.create("draft.reply", p, runtime="claude",
                          sensitivity="internal")
            created += 1
        # Same message, different question: what does this obligate them to do?
        ledger.create("admin.extract_commitments", p,
                      runtime="claude", sensitivity="internal")
        created += 1
        if looks_scheduleable(p):
            ledger.create("admin.schedule_proposal",
                          dict(p, upcoming_events=calendar_ctx),
                          runtime="claude", sensitivity="internal")
            created += 1
    if reflect_date:
        ledger.create("memory.reflect", {"date": reflect_date},
                      runtime="claude", sensitivity="internal")
        created += 1

    # Only advance state once the jobs exist, so a crash re-produces rather
    # than silently skipping a delta.
    heartbeat._save_state(snapshot, data)
    if reflect_date:
        from shared import STATE_DIR, atomic_write_json
        st = read_json(heartbeat.STATE_FILE, {}) or {}
        st["reflection_date"] = f"{now():%Y-%m-%d}"
        atomic_write_json(heartbeat.STATE_FILE, st)
        _ = STATE_DIR  # keep the import meaningful if the path ever moves

    log_line("heartbeat", f"produce: enqueued {created} jobs "
                          f"({len(replyable)} draft.reply, "
                          f"{len(payloads)} extract_commitments, "
                          f"{len(scheduleable)} schedule_proposal, "
                          f"{len(self_sent)} self-sent intake)")
    print(f"enqueued {created} jobs ({len(replyable)} draft.reply, "
          f"{len(payloads)} admin.extract_commitments, "
          f"{len(scheduleable)} admin.schedule_proposal"
          f", {len(self_sent)} self-sent intake"
          f"{', 1 memory.reflect' if reflect_date else ''})")
    print("drain with: python .claude/scripts/dispatch.py --once")
    return 0


if __name__ == "__main__":
    sys.exit(main())
