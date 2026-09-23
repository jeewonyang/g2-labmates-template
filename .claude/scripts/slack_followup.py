"""Turn unanswered Slack requests into visible, internal next actions.

Slack remains read-only. This monitor never posts, reacts, marks messages read,
or changes Slack state. It:

1. reads every new one-to-one DM independently of Slack read state;
2. observes the owner's own replies without changing Slack state;
3. drops incoming messages that already have a later reply from the owner;
4. groups each person's remaining back-to-back messages into one burst;
5. enqueues one reply draft per unanswered burst that could need the owner's input
   (acknowledgement-only bursts are skipped deterministically, and the
   draft.reply model applies the fuller 2026-08-27 bar: only messages that
   require their specific answer or input produce a draft);
6. deterministically recognizes questions/requests;
7. creates an idempotent Prisma task when actionable - scheduled for Today
   with a Windows toast when a concrete request was extracted or the sender
   is an urgent sender (their PI), else a quiet low-priority backlog task with no toast, because
   a plain reply lives in the Slack draft (the owner, 2026-08-31). The
   deterministic task is the commitment record either way, so a second
   commitment-extraction job would duplicate work and leave a misleading
   queued row.

The immediate task and toast do not need a model or approval. Agent-generated
reply text remains a draft and stays behind the existing review gate.

Usage:
  python .claude/scripts/slack_followup.py
  python .claude/scripts/slack_followup.py --dry-run
"""

from __future__ import annotations

import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import capture_sync  # noqa: E402
import ledger  # noqa: E402
import notify  # noqa: E402
from integrations import slack_integration as slack  # noqa: E402
from sanitize import sanitize  # noqa: E402
from shared import STATE_DIR, atomic_write_json, log_line, now, read_json  # noqa: E402

STATE_FILE = STATE_DIR / "slack-followup-state.json"
LOOKBACK_HOURS = 72.0
SAFETY_OVERLAP_SECONDS = 60.0
MAX_SEEN = 1000
# Slack users often split one thought across several sends. Messages from the
# same one-to-one DM with no more than this gap belong to one reply context.
BATCH_GAP_SECONDS = 5 * 60.0
# Senders whose unanswered requests are urgent rather than merely high priority
# (an advisor, a manager). Matched case-insensitively against the sender name.
# Customize with SECONDBRAIN_URGENT_SENDERS as a comma-separated list, or edit
# the default below; see USER.md for the owner's key people.
URGENT_SENDER_KEYWORDS = tuple(
    part.strip().casefold()
    for part in os.environ.get("SECONDBRAIN_URGENT_SENDERS",
                               "ada advisor").split(",")
    if part.strip()
)

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ACK_ONLY = re.compile(
    r"^\s*(?:thanks?|thank you|thx|got it|sounds good|great|perfect|"
    r"okay|ok|noted|will do|👍|🙏)[\s.!?,]*$",
    re.IGNORECASE,
)
_REQUEST = re.compile(
    r"(?:"
    r"are you able to|would you(?: be able to)?|could you|can you|"
    r"will you|please|when can you|do you (?:have|know|think|want)|"
    r"what do you|should we|shall we"
    r")\s+(.+?)(?:[?.!]|\n|$)",
    re.IGNORECASE | re.DOTALL,
)


def _is_urgent_sender(sender: str) -> bool:
    name = (sender or "").casefold()
    return any(keyword in name for keyword in URGENT_SENDER_KEYWORDS)


def _field(value: str, limit: int = 240) -> str:
    return _CTRL.sub("", (value or "").replace("\n", " ").replace("\r", " ")) \
        .strip()[:limit]


def source_id(message) -> str:
    return f"{message.channel_id}:{message.ts}"


def source_ids(message) -> list[str]:
    messages = getattr(message, "messages", None)
    if messages:
        return [source_id(item) for item in messages]
    return [source_id(message)]


def _epoch(message) -> float:
    try:
        return float(message.ts)
    except (TypeError, ValueError):
        return 0.0


@dataclass
class IncomingBatch:
    """One reply context assembled from a chronological DM burst."""

    messages: tuple

    @property
    def latest(self):
        return self.messages[-1]

    @property
    def channel_id(self):
        return self.latest.channel_id

    @property
    def channel_name(self):
        return self.latest.channel_name

    @property
    def user_id(self):
        return self.latest.user_id

    @property
    def user_name(self):
        return self.latest.user_name

    @property
    def text(self):
        return "\n\n".join(
            str(message.text or "").strip() for message in self.messages
            if str(message.text or "").strip()
        )

    @property
    def ts(self):
        return self.latest.ts

    @property
    def is_dm(self):
        return all(message.is_dm for message in self.messages)

    @property
    def mentions_me(self):
        return any(message.mentions_me for message in self.messages)

    @property
    def thread_ts(self):
        values = {message.thread_ts for message in self.messages}
        return values.pop() if len(values) == 1 else None


def batch_messages(messages) -> list[IncomingBatch]:
    """Group back-to-back messages in the same DM into reply-sized chunks.

    Slack returns newest-first, so sort chronologically before measuring gaps
    and joining text. Different people/channels never share a batch.
    """
    by_conversation = {}
    for message in messages:
        key = (message.channel_id, message.user_id)
        by_conversation.setdefault(key, []).append(message)

    batches = []
    for conversation in by_conversation.values():
        ordered = sorted(conversation, key=_epoch)
        current = []
        for message in ordered:
            if (
                current
                and _epoch(message) - _epoch(current[-1]) > BATCH_GAP_SECONDS
            ):
                batches.append(IncomingBatch(tuple(current)))
                current = []
            current.append(message)
        if current:
            batches.append(IncomingBatch(tuple(current)))
    return sorted(batches, key=lambda batch: _epoch(batch.latest))


def unanswered_messages(messages) -> list:
    """Return incoming DM messages after the latest reply in each conversation.

    ``messages_since(include_own=True)`` supplies both sides of the DM. A
    self-authored message is a response boundary: earlier incoming messages in
    that one-to-one conversation no longer need a task or reply draft. Later
    incoming messages remain eligible.
    """
    by_channel = {}
    for message in messages:
        by_channel.setdefault(message.channel_id, []).append(message)

    unanswered = []
    for conversation in by_channel.values():
        pending = []
        for message in sorted(conversation, key=_epoch):
            if getattr(message, "is_from_me", False):
                pending = []
            else:
                pending.append(message)
        unanswered.extend(pending)
    return sorted(unanswered, key=_epoch)


def needs_reply_draft(text: str) -> bool:
    """Whether a burst could need the owner's input at all.

    Deterministic pre-filter only: a pure acknowledgement ("Thanks!",
    "sounds good") never needs a reply, so it should not even spend a model
    call. Everything else is enqueued and the draft.reply prompt makes the
    real call (the owner, 2026-08-27: draft only what requires their specific
    answer or input).
    """
    stripped = (text or "").strip()
    return bool(stripped) and not _ACK_ONLY.fullmatch(stripped)


def _imperative(text: str) -> str | None:
    """Extract a concise requested action without model inference."""
    match = _REQUEST.search(text or "")
    if not match:
        return None
    action = re.sub(r"\s+", " ", match.group(1)).strip(" .?!")
    return action[:180] or None


def plan(message) -> dict | None:
    """Return a Today-task plan for an actionable unanswered message."""
    text = _field(message.text, 4000)
    if not text or _ACK_ONLY.fullmatch(text):
        return None

    requested = _imperative(text)
    if not requested and "?" not in text and not message.mentions_me:
        return None

    sender = _field(message.user_name or message.user_id, 100) or "sender"
    first = sender.split()[0]
    lower = text.lower()

    # This common manuscript handoff is made explicit because "accept and
    # submit" alone hides the object when shown on Today.
    if requested and "accept and submit" in requested.lower() \
            and (" in ms" in lower or "manuscript" in lower):
        title = f"Review {first}'s manuscript/SI edits, accept changes, and submit"
        next_step = (
            f"Review the manuscript edits and resolved SI comment from {sender}; "
            "accept the changes, submit the revised package, then reply with status."
        )
    elif requested:
        action = requested[0].upper() + requested[1:]
        title = f"{action} — then reply to {first}"
        next_step = f"Handle this request from {sender}, then reply with the outcome."
    else:
        title = f"Reply to {first} on Slack"
        next_step = f"Answer the open question from {sender}."

    # Replying is not itself a high-priority task (the owner, 2026-08-31): the
    # reply lives in the Slack draft, so a burst with no extracted request
    # becomes a quiet low-priority backlog task ("next", undated, no toast)
    # instead of a scheduled Today row. A concrete request keeps the loud
    # path, and anything from an urgent sender (their PI, per
    # URGENT_SENDER_KEYWORDS) stays urgent either way.
    from_pi = _is_urgent_sender(sender)
    return {
        "title": title[:300],
        "description": (
            f"Next step: {next_step}\n\n"
            f"Slack message from {sender}:\n{text}"
        ),
        "priority": "urgent" if from_pi else ("high" if requested else "low"),
        "context": "computer",
        "reply_only": not requested and not from_pi,
    }


def _job_exists(kind: str, sid: str) -> bool:
    for job in ledger.fold().values():
        if job.get("kind") != kind:
            continue
        payload = job.get("payload") or {}
        if payload.get("source_id") == sid:
            return True
    return False


def _enqueue_agent_context(message, task: dict | None = None) -> list[str]:
    sid = source_id(message)
    body, flags = sanitize(message.text or "", source="slack")
    payload = {
        "source": "slack",
        "source_id": sid,
        "source_ids": source_ids(message),
        "sender": _field(message.user_name or message.user_id, 200),
        "subject": f"Slack {'DM' if message.is_dm else 'mention'}",
        "body": body,
        "channel_id": _field(message.channel_id, 120),
        "message_ts": _field(message.ts, 120),
        "message_count": len(getattr(message, "messages", ()) or (message,)),
        "thread_ts": _field(message.thread_ts or "", 120),
        "is_dm": bool(message.is_dm),
        "task_id": (task or {}).get("task_id", ""),
        "next_action": (task or {}).get("title", ""),
        "sanitize_flags": list(flags) if flags else [],
    }
    created = []
    # The Today task above is already the durable, visible commitment. Queue
    # only the work that remains: preparing a reply draft. Earlier versions
    # also enqueued admin.extract_commitments, which duplicated the task and
    # stayed "created" after the draft was dismissed.
    for kind in ("draft.reply",):
        if _job_exists(kind, sid):
            continue
        created.append(ledger.create(
            kind, payload, runtime="claude", sensitivity="internal"))
    return created


def main() -> int:
    dry = "--dry-run" in sys.argv
    state = read_json(STATE_FILE, {}) or {}
    seen = set(state.get("seen", []))
    scan_started = time.time()
    oldest = float(
        state.get("last_scan_ts")
        or (scan_started - LOOKBACK_HOURS * 3600)
    )

    try:
        activity = [
            message for message in slack.messages_since(
                oldest,
                include_channels=False,
                include_group_dms=False,
                require_complete=True,
                include_own=True,
            )
            if message.is_dm
        ]
    except Exception as exc:
        log_line("slack-followup", f"scan failed: {exc!r}")
        print(f"Slack follow-up scan failed: {exc}", file=sys.stderr)
        return 1

    new_incoming = [
        message for message in activity
        if not getattr(message, "is_from_me", False)
        if source_id(message) not in seen
    ]
    unanswered_ids = {
        source_id(message) for message in unanswered_messages(activity)
    }
    new_messages = [
        message for message in new_incoming
        if source_id(message) in unanswered_ids
    ]
    batches = batch_messages(new_messages)
    actionable = [
        (batch, task_plan)
        for batch in batches
        if (task_plan := plan(batch)) is not None
    ]

    if dry:
        print(
            f"new DMs: {len(new_incoming)}; "
            f"already answered: {len(new_incoming) - len(new_messages)}; "
            f"actionable: {len(actionable)}; "
            f"reply drafts to queue: "
            f"{sum(1 for batch in batches if needs_reply_draft(batch.text))}"
        )
        for batch, task_plan in actionable:
            print(
                f"- {batch.user_name} ({len(batch.messages)} message(s)): "
                f"{task_plan['title']}"
            )
        return 0

    created_tasks = 0
    created_jobs = 0
    # Answered incoming messages are complete work too. Remember them so the
    # safety-overlap window cannot reconsider them on the next scan.
    evaluated = [source_id(message) for message in new_incoming]
    for batch in batches:
        sid = source_id(batch)
        task_plan = plan(batch)
        task = None
        reply_only = bool(task_plan.pop("reply_only", False)) if task_plan else False
        if task_plan:
            task = capture_sync.create_external_followup_task(
                source="slack",
                source_id=sid,
                # A reply-only burst stays off Today (status "next", undated);
                # the draft is where it lives (the owner, 2026-08-31).
                scheduled_at=None if reply_only else now(),
                **task_plan,
            )
        jobs = (
            _enqueue_agent_context(batch, task)
            if needs_reply_draft(batch.text)
            else []
        )
        created_jobs += len(jobs)
        if task and task["created"]:
            created_tasks += 1
            if not reply_only:
                notify.toast(
                    f"Slack next action — {batch.user_name}",
                    task["title"],
                )

    new_seen = (list(state.get("seen", [])) + evaluated)[-MAX_SEEN:]
    committed_ts = max(oldest, scan_started - SAFETY_OVERLAP_SECONDS)
    atomic_write_json(STATE_FILE, {
        "last_run": now().isoformat(timespec="seconds"),
        # Re-scan a small overlap next time. source_id/ledger idempotency turns
        # at-least-once polling into exactly one draft while protecting against
        # API timing and pagination boundaries.
        "last_scan_ts": f"{committed_ts:.6f}",
        "seen": new_seen,
    })
    log_line(
        "slack-followup",
        f"scan complete: {len(new_incoming)} new DMs, "
        f"{len(new_incoming) - len(new_messages)} already answered, "
        f"{len(batches)} burst(s), {created_tasks} task(s), "
        f"{created_jobs} agent job(s)",
    )
    print(
        f"Slack follow-up: {len(new_incoming)} new DMs; "
        f"{len(new_incoming) - len(new_messages)} already answered; "
        f"{len(batches)} burst(s); created {created_tasks} Today task(s), "
        f"{created_jobs} agent job(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
