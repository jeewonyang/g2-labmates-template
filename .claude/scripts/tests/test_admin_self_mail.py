"""Regression tests for self-forwarded Gmail intake.

Run directly:
  python .claude/scripts/tests/test_admin_self_mail.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import heartbeat_produce  # noqa: E402
from integrations.gmail_integration import (  # noqa: E402
    EmailMessage,
    _embedded_message_headers,
    extract_forwarded_headers,
    is_self_sender,
)
from jobs import admin_extract_commitments  # noqa: E402


def _message(**overrides) -> EmailMessage:
    values = {
        "id": "msg-1",
        "thread_id": "thread-1",
        "sender": "The Owner <you@work.example.edu>",
        "subject": "Raw data from today's experiment",
        "date": "Tue, 28 Jul 2026 09:00:00 -0700",
        "snippet": "Please process this data.",
        "unread": False,
        "attachment_names": ["screen_results.csv"],
        "body": "Please process this data.",
    }
    values.update(overrides)
    return EmailMessage(**values)


def test_self_sender_aliases() -> None:
    assert is_self_sender("The Owner <you@work.example.edu>")
    assert is_self_sender("you@example.com")
    assert not is_self_sender("collaborator@example.org")


def test_self_sent_raw_data_payload() -> None:
    payload = heartbeat_produce._gmail_payload(_message())
    assert payload["self_sent"] is True
    assert payload["raw_data_hint"] is True
    assert payload["attachment_names"] == ["screen_results.csv"]
    assert heartbeat_produce.should_draft_reply(payload) is False


def test_forwarded_sender_becomes_reply_target() -> None:
    body = """FYI

---------- Forwarded message ---------
From: Dr. Ada Lovelace <ada@example.org>
Date: Tue, 28 Jul 2026 08:30:00 -0700
Subject: Can you review the analysis?
To: The Owner <you@work.example.edu>

Could you review the analysis by Friday?
"""
    headers = extract_forwarded_headers(body)
    assert headers == {
        "from": "Dr. Ada Lovelace <ada@example.org>",
        "subject": "Can you review the analysis?",
    }
    payload = heartbeat_produce._gmail_payload(_message(body=body))
    assert payload["self_sent"] is True
    assert payload["forwarded_sender_found"] is True
    assert payload["sender"] == "Dr. Ada Lovelace <ada@example.org>"
    assert payload["subject"] == "Can you review the analysis?"
    assert heartbeat_produce.should_draft_reply(payload) is True


def test_embedded_rfc822_headers_take_priority() -> None:
    payload_tree = {
        "mimeType": "multipart/mixed",
        "parts": [{
            "mimeType": "message/rfc822",
            "headers": [
                {"name": "From", "value": "Grace Hopper <grace@example.org>"},
                {"name": "Subject", "value": "Review request"},
            ],
        }],
    }
    assert _embedded_message_headers(payload_tree) == {
        "from": "Grace Hopper <grace@example.org>",
        "subject": "Review request",
    }
    message = _message(
        body="See attached forwarded email.",
        forwarded_sender="Grace Hopper <grace@example.org>",
        forwarded_subject="Review request",
    )
    payload = heartbeat_produce._gmail_payload(message)
    assert payload["sender"] == "Grace Hopper <grace@example.org>"
    assert payload["subject"] == "Review request"
    assert payload["forwarded_sender_found"] is True


def test_self_sent_is_prioritized_and_not_capped_with_regular_mail() -> None:
    self_message = _message()
    regular = [
        _message(
            id=f"regular-{i}",
            sender="Collaborator <collaborator@example.org>",
            subject=f"Question {i}",
            snippet="Can you review this?",
            body="",
            attachment_names=[],
        )
        for i in range(heartbeat_produce.MAX_PER_INTEGRATION + 3)
    ]
    messages = regular + [self_message]
    delta = {"gmail": [m.id for m in messages]}
    payloads = heartbeat_produce.collect({"gmail": messages}, delta)

    assert payloads[0]["source_id"] == "msg-1"
    assert len(payloads) == 1 + heartbeat_produce.MAX_PER_INTEGRATION


def test_prompt_requires_a_self_capture_action_without_executing_it() -> None:
    payload = heartbeat_produce._gmail_payload(_message())
    prompt = admin_extract_commitments.build_prompt(payload)
    assert "It does not need a reply, but it DOES need an" in prompt
    assert "process or analyze" in prompt
    assert "never execute them" in prompt
    assert "screen_results.csv" in prompt


def test_extraction_never_queues_review() -> None:
    # Extractions no longer review at all (the owner, 2026-09-02): the only
    # effect is an internal note, filed by on_result, so there is nothing an
    # approval could gate - the same reasoning as draft.reply. Review-required
    # was already relaxed for empty results on 2026-08-31; this drops it for
    # non-empty ones too.
    assert admin_extract_commitments.REVIEW_REQUIRED is False
    assert admin_extract_commitments.needs_human({"commitments": [], "has_deadline": False}) is False
    assert admin_extract_commitments.needs_human(None) is False
    assert admin_extract_commitments.needs_human(
        {"commitments": [{"what": "Send the dataset", "direction": "she_owes",
                          "confidence": 0.9, "source_quote": "send the dataset"}],
         "has_deadline": False}
    ) is False


def test_extraction_files_itself_on_result() -> None:
    import tempfile

    daily_log_calls = []
    original_memory = admin_extract_commitments.MEMORY
    original_log = admin_extract_commitments.append_to_daily_log
    with tempfile.TemporaryDirectory() as temp:
        admin_extract_commitments.MEMORY = Path(temp)
        admin_extract_commitments.append_to_daily_log = (
            lambda title, body: daily_log_calls.append((title, body)))
        try:
            admin_extract_commitments.on_result(
                {"job": "job_test", "payload": {
                    "sender": "PI", "subject": "Report timing"}},
                {"commitments": [
                    {"what": "Send the progress report",
                     "direction": "she_owes", "due": "2026-09-05",
                     "urgency": "urgent", "confidence": 0.9,
                     "source_quote": "report due Friday"}],
                 "has_deadline": True},
            )
            # An empty extraction files nothing - no log entry, no ledger file.
            admin_extract_commitments.on_result(
                {"job": "job_test2", "payload": {"sender": "listserv"}},
                {"commitments": [], "has_deadline": False},
            )
        finally:
            admin_extract_commitments.MEMORY = original_memory
            admin_extract_commitments.append_to_daily_log = original_log

        ledger_files = list((Path(temp) / "admin" / "commitments").glob("*.md"))
        assert len(ledger_files) == 1
        content = ledger_files[0].read_text(encoding="utf-8")
        assert "Send the progress report" in content
        assert "report due Friday" in content
    assert len(daily_log_calls) == 1
    assert daily_log_calls[0][0] == "Commitments (auto-filed)"

    # apply() must stay inert: the note is already filed by on_result, and a
    # stray approved-state replay must not double-file it.
    assert admin_extract_commitments.apply({}, {"commitments": [{}]}) is None


if __name__ == "__main__":
    test_self_sender_aliases()
    test_self_sent_raw_data_payload()
    test_forwarded_sender_becomes_reply_target()
    test_embedded_rfc822_headers_take_priority()
    test_self_sent_is_prioritized_and_not_capped_with_regular_mail()
    test_prompt_requires_a_self_capture_action_without_executing_it()
    test_extraction_never_queues_review()
    test_extraction_files_itself_on_result()
    print("PASS 8 self-forwarded Gmail intake tests")
