"""Regression tests for relationship confirmation and reply-tone learning."""

import tempfile
from pathlib import Path

import sys

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import draft_feedback  # noqa: E402


def check(label, condition, detail=""):
    mark = "PASS" if condition else "FAIL"
    print(f"  [{mark}] {label}" + (f": {detail}" if detail else ""))
    if not condition:
        raise AssertionError(label)


def draft() -> str:
    return """---
type: slack
source_id: D123:456.7
recipient: New Person
subject: Slack DM
relationship_group: Collaborator
relationship_status: inferred
relationship_rationale: Respectful default because evidence was limited.
status: active
---

## Original Message

Can we meet tomorrow?

## Draft Reply

Thanks for reaching out. I would be happy to meet tomorrow.
"""


def main() -> int:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        active = root / "active"
        expired = root / "expired"
        feedback = root / "draft-feedback.jsonl"
        active.mkdir()
        name = "2026-07-30_slack_new-person.md"
        source = active / name
        source.write_text(draft(), encoding="utf-8")

        original = (
            draft_feedback.ACTIVE,
            draft_feedback.EXPIRED,
            draft_feedback.FEEDBACK,
        )
        draft_feedback.ACTIVE = active
        draft_feedback.EXPIRED = expired
        draft_feedback.FEEDBACK = feedback
        try:
            result = draft_feedback.classify(name, "Colleague")
            raw = source.read_text(encoding="utf-8")
            check("classification is confirmed", result["status"] == "confirmed")
            check("confirmed group is written to the draft",
                  "relationship_group: Colleague" in raw)
            check("confirmation provenance is written",
                  "relationship_status: confirmed" in raw
                  and "relationship_confirmed_by: owner" in raw)
            check("confirmed relationship is reusable",
                  draft_feedback.confirmed_group("New Person") == "Colleague")

            edited = "Tomorrow works! What time is best for you?"
            edit_result = draft_feedback.edit(name, edited)
            raw = source.read_text(encoding="utf-8")
            check("reply edit is saved", edited in raw)
            check("reply edit becomes a lesson", edit_result["learned"] is True)
            block = draft_feedback.prompt_block("New Person")
            check("future prompt uses the confirmed group",
                  "confirmed as Colleague" in block)
            check("future prompt includes the owner's version",
                  edited in block and "THEIR VERSION" in block)

            expired.mkdir()
            collision = expired / name
            collision.write_text("older archived draft", encoding="utf-8")
            dismissed = draft_feedback.dismiss(name)
            check("dismissal removes the draft from the active queue",
                  not source.exists())
            check("dismissal preserves an older same-name archive",
                  collision.read_text(encoding="utf-8") == "older archived draft")
            archived = expired / dismissed["filename"]
            check("dismissal creates a collision-safe archive",
                  archived.exists() and archived != collision)
            check("dismissed draft content is retained",
                  edited in archived.read_text(encoding="utf-8"))

            first_bulk = active / "2026-07-31_slack_first.md"
            second_bulk = active / "2026-07-31_email_second.md"
            first_bulk.write_text(draft(), encoding="utf-8")
            second_bulk.write_text(
                draft().replace("type: slack", "type: email"),
                encoding="utf-8",
            )
            bulk = draft_feedback.dismiss_all()
            check("bulk dismissal archives every active draft",
                  bulk["ok"] is True and bulk["archived"] == 2)
            check("bulk dismissal clears the active draft queue",
                  list(active.glob("*.md")) == [])
            check("bulk dismissal preserves every draft in expired",
                  all((expired / filename).exists()
                      for filename in bulk["filenames"]))
        finally:
            (
                draft_feedback.ACTIVE,
                draft_feedback.EXPIRED,
                draft_feedback.FEEDBACK,
            ) = original

    print("\nAll draft-feedback tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
