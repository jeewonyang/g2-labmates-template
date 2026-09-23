"""Regression tests for Slack request detection and idempotent task creation."""

import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import capture_sync  # noqa: E402
import slack_followup  # noqa: E402
from jobs import draft_reply  # noqa: E402
from integrations.slack_integration import SlackMessage  # noqa: E402
from shared import now  # noqa: E402


def check(condition, label):
    if not condition:
        raise AssertionError(label)
    print(f"PASS {label}")


def message(
    text: str,
    ts: str = "1785202258.850199",
    channel_id: str = "D0EXAMPLE1",
    user_id: str = "U0EXAMPLE1",
    user_name: str = "Dr. Ada Advisor",
    is_from_me: bool = False,
) -> SlackMessage:
    return SlackMessage(
        channel_id=channel_id,
        channel_name="(dm)",
        user_id=user_id,
        user_name=user_name,
        text=text,
        ts=ts,
        is_dm=True,
        mentions_me=False,
        is_from_me=is_from_me,
    )


plan = slack_followup.plan(message(
    "Hi the owner - a few small edits in MS and resolved comment in SI. "
    "Are you able to accept and submit?"
))
check(plan is not None, "direct PI request is actionable")
check("manuscript/SI edits" in plan["title"],
      "short request is expanded into a useful Today title")
check(plan["priority"] == "urgent", "PI requests are urgent")
check(plan.pop("reply_only") is False,
      "a PI burst keeps the loud Today-and-toast path")
check(slack_followup.plan(message("Thanks!")) is None,
      "acknowledgement-only DMs do not create tasks")

# Replying is not itself a high-priority task (the owner, 2026-08-31): a burst
# with no extracted request becomes a quiet low-priority backlog task and the
# reply lives in the Slack draft.
reply_only_plan = slack_followup.plan(message(
    "What did you think of the seminar yesterday?",
    channel_id="D-OTHER",
    user_id="U-OTHER",
    user_name="Other Person",
))
check(reply_only_plan is not None, "a plain question is still actionable")
check(reply_only_plan["priority"] == "low",
      "a reply-only burst is low priority, not high")
check(reply_only_plan["reply_only"] is True,
      "a reply-only burst is marked for the quiet path")
request_plan = slack_followup.plan(message(
    "Could you send me the calibration data?",
    channel_id="D-OTHER",
    user_id="U-OTHER",
    user_name="Other Person",
))
check(request_plan["priority"] == "high" and request_plan["reply_only"] is False,
      "an extracted request keeps its priority and the loud path")

burst = slack_followup.batch_messages([
    message("Third thought", ts="1300.0"),
    message("First thought", ts="1000.0"),
    message("Second thought", ts="1120.0"),
])
check(len(burst) == 1, "back-to-back messages from one person form one burst")
check(
    burst[0].text == "First thought\n\nSecond thought\n\nThird thought",
    "burst context is chronological and complete",
)
separated = slack_followup.batch_messages([
    message("Earlier conversation", ts="1000.0"),
    message("Later conversation", ts="1401.0"),
    message(
        "Different person",
        ts="1100.0",
        channel_id="D-OTHER",
        user_id="U-OTHER",
        user_name="Other Person",
    ),
])
check(len(separated) == 3,
      "long gaps and different people remain separate reply contexts")

answered = slack_followup.unanswered_messages([
    message("Could you review this?", ts="1000.0"),
    message(
        "Done - I reviewed it.",
        ts="1100.0",
        user_id="U-ME",
        user_name="the owner",
        is_from_me=True,
    ),
])
check(answered == [], "a later self reply closes the incoming DM request")
after_reply = slack_followup.unanswered_messages([
    message("Earlier request", ts="1000.0"),
    message(
        "Handled.",
        ts="1100.0",
        user_id="U-ME",
        user_name="the owner",
        is_from_me=True,
    ),
    message("One more question?", ts="1200.0"),
])
check(
    [incoming.text for incoming in after_reply] == ["One more question?"],
    "a message received after the self reply still needs follow-up",
)


class FakeSlackClient:
    def auth_test(self):
        return {"user_id": "U-ME", "user": "the owner"}

    def conversations_list(self, **kwargs):
        return {
            "channels": [{"id": "D-SYNTHETIC", "is_im": True}],
            "response_metadata": {},
        }

    def conversations_history(self, **kwargs):
        return {
            "messages": [
                {"type": "message", "user": "U-ME", "text": "Handled.",
                 "ts": "1100.0"},
                {"type": "message", "user": "U-OTHER", "text": "Review?",
                 "ts": "1000.0"},
            ],
            "response_metadata": {},
        }

    def users_info(self, *, user):
        return {"user": {"real_name": user}}


original_client = slack_followup.slack._client
try:
    slack_followup.slack._client = lambda: FakeSlackClient()
    default_activity = slack_followup.slack.messages_since(900.0)
    response_aware_activity = slack_followup.slack.messages_since(
        900.0, include_own=True)
finally:
    slack_followup.slack._client = original_client

check(len(default_activity) == 1 and not default_activity[0].is_from_me,
      "the shared Slack query still excludes self messages by default")
check(
    len(response_aware_activity) == 2
    and sum(item.is_from_me for item in response_aware_activity) == 1,
    "the follow-up query can identify a synthetic self reply",
)

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

first = capture_sync.create_external_followup_task(
    source="slack",
    source_id="D0EXAMPLE1:1785202258.850199",
    scheduled_at=now(),
    **plan,
)
second = capture_sync.create_external_followup_task(
    source="slack",
    source_id="D0EXAMPLE1:1785202258.850199",
    scheduled_at=now(),
    **plan,
)

check(first["created"] is True, "first scan creates a task")
check(second["created"] is False, "repeat scan reuses the source task")
check(con.execute("SELECT count(*) FROM Task").fetchone()[0] == 1,
      "source marker prevents duplicate tasks")
check(con.execute("SELECT status FROM Task").fetchone()[0] == "scheduled",
      "Slack follow-up appears on Today")

# The quiet path, exactly as main() calls it: reply_only popped, undated.
quiet_kwargs = {k: v for k, v in reply_only_plan.items() if k != "reply_only"}
quiet_task = capture_sync.create_external_followup_task(
    source="slack",
    source_id="D-OTHER:1785202258.850199",
    scheduled_at=None,
    **quiet_kwargs,
)
quiet_row = con.execute(
    "SELECT status, priority, scheduledDate FROM Task WHERE id = ?",
    (quiet_task["task_id"],),
).fetchone()
check(
    quiet_row["status"] == "next" and quiet_row["priority"] == "low"
    and quiet_row["scheduledDate"] is None,
    "a reply-only task is a low-priority undated backlog row, not a Today row",
)

created_kinds = []
created_payloads = []
original_fold = slack_followup.ledger.fold
original_create = slack_followup.ledger.create
try:
    slack_followup.ledger.fold = lambda: {}
    slack_followup.ledger.create = (
        lambda kind, payload, **kwargs:
        created_kinds.append(kind)
        or created_payloads.append(payload)
        or f"job-{kind}"
    )
    slack_followup._enqueue_agent_context(
        message("Thanks!"),
        None,
    )
    slack_followup._enqueue_agent_context(
        message("Are you able to accept and submit?"),
        {"task_id": first["task_id"], "title": plan["title"]},
    )
    combined = slack_followup.batch_messages([
        message("And one more detail", ts="1785202259.0"),
        message("Could you review this?", ts="1785202258.0"),
    ])[0]
    slack_followup._enqueue_agent_context(combined, None)
finally:
    slack_followup.ledger.fold = original_fold
    slack_followup.ledger.create = original_create

check(created_kinds == ["draft.reply", "draft.reply", "draft.reply"],
      "each DM context queues only reply-drafting work")
check(slack_followup.needs_reply_draft("Thanks!") is False,
      "acknowledgement-only bursts are gated out before enqueue")
check(slack_followup.needs_reply_draft("Could you review this?") is True,
      "a real request still queues a reply draft")
check(slack_followup.needs_reply_draft("") is False,
      "an empty burst queues nothing")
check(created_payloads[-1]["message_count"] == 2,
      "one burst produces one job carrying the message count")
check(created_payloads[-1]["source_ids"] == [
    "D0EXAMPLE1:1785202258.0",
    "D0EXAMPLE1:1785202259.0",
], "the batch job retains every constituent Slack source id")
check(
    "Could you review this?" in created_payloads[-1]["body"]
    and "And one more detail" in created_payloads[-1]["body"],
    "the batch job carries the full combined Slack text",
)

prompt = draft_reply.build_prompt({
    "source": "slack",
    "sender": "Sam Student",
    "subject": "Slack DM",
    "body": "Thanks!",
    "is_dm": True,
})
check("Only when a reply from the owner is genuinely needed" in prompt,
      "drafting is gated on the owner's input being required (2026-08-27 policy)")
check("a\nDM is not drafted just because it is a DM" in prompt,
      "the every-DM rule is gone: DMs are judged by the same bar")
check("When unsure whether their input is\nrequired, skip" in prompt,
      "ambiguous messages skip the draft instead of defaulting to one")
check("Sam Student = Mentee" in prompt,
      "the example mentee is classified as a mentee for tone")
check("Mentee: casual and warm" in prompt,
      "relationship group selects the requested tone")
check("Never make a serious message playful" in prompt,
      "situational seriousness overrides relationship tone")

with tempfile.TemporaryDirectory() as state_dir:
    original_state_file = slack_followup.STATE_FILE
    original_messages_since = slack_followup.slack.messages_since
    original_enqueue = slack_followup._enqueue_agent_context
    original_argv = sys.argv
    scan_calls = []
    queued = []
    slack_followup.STATE_FILE = Path(state_dir) / "slack-followup-state.json"
    slack_followup.slack.messages_since = (
        lambda oldest, **kwargs:
        scan_calls.append((oldest, kwargs)) or [
            message("Last short message", ts="1785202258.850199"),
            message("Middle short message", ts="1785202200.000000"),
            message("First short message", ts="1785202150.000000"),
            message(
                "Already handled.",
                ts="1785202100.000000",
                channel_id="D-ANSWERED",
                user_id="U-ME",
                user_name="the owner",
                is_from_me=True,
            ),
            message(
                "Could you review this?",
                ts="1785202000.000000",
                channel_id="D-ANSWERED",
                user_id="U-OTHER",
                user_name="Other Person",
            ),
        ]
    )
    slack_followup._enqueue_agent_context = (
        lambda incoming, task=None:
        queued.append((incoming.text, len(incoming.messages), task))
        or ["job-draft.reply"]
    )
    try:
        sys.argv = ["slack_followup.py"]
        check(slack_followup.main() == 0,
              "read-independent DM scan completes")
        check(queued == [(
            "First short message\n\nMiddle short message\n\nLast short message",
            3,
            None,
        )], "one complete burst queues one reply draft")
        check(scan_calls[0][1]["require_complete"] is True,
              "DM cursor advances only after a complete scan")
        check(scan_calls[0][1]["include_group_dms"] is False,
              "background monitor scans one-to-one DMs only")
        check(scan_calls[0][1]["include_own"] is True,
              "background monitor requests self replies for answer detection")
        check(con.execute("SELECT count(*) FROM Task").fetchone()[0] == 2,
              "an already-answered Slack request creates no new task")
        check(slack_followup.main() == 0,
              "repeat DM scan completes")
        check(len(queued) == 1,
              "every source id in a burst prevents duplicate reply jobs")
    finally:
        sys.argv = original_argv
        slack_followup.STATE_FILE = original_state_file
        slack_followup.slack.messages_since = original_messages_since
        slack_followup._enqueue_agent_context = original_enqueue

with tempfile.TemporaryDirectory() as temp:
    draft_reply.MEMORY = Path(temp)
    draft_reply.on_result(
        {
            "job": "1785209167928522-61cc7f22",
            "payload": {
                "source": "slack",
                "source_id": "D0EXAMPLE1:1785202258.850199",
                "sender": "Dr. Ada Advisor",
                "subject": "Slack DM",
                "body": "Are you able to accept and submit?",
            },
        },
        {
            "should_draft": True,
            "reply": "Yes — I will review the edits and submit.",
            "subject": "Re: manuscript edits",
            "rationale": "Direct PI request",
            "urgency": "urgent",
            "relationship_group": "Mentor/PI",
            "relationship_rationale": "Ada Advisor is the owner's PI",
            "relationship_confidence": "high",
        },
    )
    generated = list((Path(temp) / "drafts" / "active").glob("*.md"))
    check(len(generated) == 1, "successful Slack reasoning writes a draft automatically")
    check("Yes — I will review" in generated[0].read_text(encoding="utf-8"),
          "generated Slack reply is preserved in the draft file")
    check("relationship_confidence: high" in
          generated[0].read_text(encoding="utf-8"),
          "relationship classification metadata is persisted")
    draft_reply.on_result(
        {
            "job": "duplicate-job",
            "payload": {
                "source": "slack",
                "source_id": "D0EXAMPLE1:1785202258.850199",
                "sender": "Dr. Ada Advisor",
                "subject": "Slack DM",
                "body": "Are you able to accept and submit?",
            },
        },
        {
            "should_draft": True,
            "reply": "Duplicate reply",
            "subject": "Re: manuscript edits",
            "rationale": "Duplicate",
            "urgency": "urgent",
            "relationship_group": "Mentor/PI",
            "relationship_rationale": "Known PI",
            "relationship_confidence": "high",
        },
    )
    check(len(list((Path(temp) / "drafts" / "active").glob("*.md"))) == 1,
          "source id prevents a duplicate draft file")
    check(draft_reply.REVIEW_REQUIRED is False,
          "internal draft creation does not wait in the approval queue")

print("\nAll Slack follow-up tests passed.")
