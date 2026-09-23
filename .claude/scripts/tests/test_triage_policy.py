"""Regression tests for automatic triage and local protection boundaries."""

import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import dispatch  # noqa: E402
import ledger  # noqa: E402
import capture_sync  # noqa: E402
from jobs import triage_classify  # noqa: E402
from triage import protection  # noqa: E402
from triage import review  # noqa: E402


def _classified(root: Path, name: str, proposal: dict) -> str:
    source = root / "VAULT" / "G2OS-Staging" / "00_Inbox" / name
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("ordinary document", encoding="utf-8")
    jid = ledger.create(
        "triage.classify", {"path": source.relative_to(root).as_posix()},
        runtime="ollama", sensitivity="private")
    ledger.claim_job(jid, "test")
    ledger.needs_review(jid, proposal)
    return jid


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        ledger.LEDGER_DIR = root / "ledger"
        ledger.EVENTS = ledger.LEDGER_DIR / "events.jsonl"
        ledger.SNAPSHOT = ledger.LEDGER_DIR / "snapshot.json"
        triage_classify.REPO_ROOT = root
        protection.REPO_ROOT = root
        (root / "VAULT" / "G2OS-Staging" / "20_Areas").mkdir(parents=True)

        capture = (root / "VAULT" / "Research-Private" / "00_Inbox"
                   / "G2-Captures" / "capture.md")
        capture.parent.mkdir(parents=True)
        capture.write_text(
            "---\ntype: g2-capture\n---\n\n"
            "# Collect brain & embed in OCT\n\n"
            "Collect brain & embed in OCT\n",
            encoding="utf-8",
        )
        capture_result = {
            "vault": "Research-Private",
            "bucket": "10_Projects",
            "project": "OCT",
            "folder": "OCT",
            "folder_mode": "create",
            "actions": [{
                "kind": "note",
                "title": "Collect brain & embed in OCT",
                "details": "An idea",
                "priority": "medium",
                "context": "Research-Private/10_Projects/OCT",
                "due_date": "2026-07-28",
                "scheduled_date": "2026-07-28T13:41:52-07:00",
                "duration_minutes": 0,
                "calendar_event": False,
                "project": "OCT",
                "area": "Research",
                "confidence": 0.95,
            }],
        }
        triage_classify.normalize_capture_result(
            {"payload": {"path": capture.relative_to(root).as_posix()}},
            capture_result,
        )
        action = capture_result["actions"][0]
        assert capture_result["bucket"] == "20_Areas"
        assert capture_result["folder_mode"] == "bucket-root"
        assert capture_result["folder"] is None
        assert capture_result["project"] is None
        assert action["kind"] == "task"
        assert action["context"] == "lab"
        assert action["due_date"] is None
        assert action["scheduled_date"] is None
        assert action["duration_minutes"] is None
        assert action["project"] is None

        base = {
            "vault": "G2OS-Staging",
            "bucket": "20_Areas",
            "project": None,
            "folder": None,
            "folder_mode": "bucket-root",
            "confidence": 0.9,
            "reason": "local content-based decision",
            "actions": [{"kind": "task", "title": "maybe do this"}],
        }

        protected_id = _classified(root, "passwords.txt", base)
        assert review._resolve_protected([ledger.get(protected_id)]) == []
        protected_job = ledger.get(protected_id)
        assert protected_job["status"] == "approved"
        assert protected_job["proposal"]["protection"] == "credentials"

        uncertain_id = _classified(root, "ordinary.md", base)
        item = review.build_review_item(ledger.get(uncertain_id))
        assert "path" not in item
        audit = {
            "job": "audit",
            "payload": {"items": [item]},
            "sensitivity": "internal",
        }
        assert dispatch.derive_sensitivity(audit) == "internal"

        review_id = ledger.create(
            "triage.review", {"items": [item]},
            runtime="claude", sensitivity="internal")
        ledger.claim_job(review_id, "test")
        ledger.complete(review_id, {"verdicts": [{
            "job": uncertain_id,
            "verdict": "uncertain",
            "vault": "leave-in-inbox",
            "bucket": "none",
            "project": None,
            "folder": None,
            "folder_mode": "bucket-root",
            "note": "metadata alone is ambiguous",
            "actions_verdict": "uncertain",
        }]})
        argv = sys.argv
        sys.argv = ["review.py", "process"]
        try:
            review.cmd_process()
        finally:
            sys.argv = argv

        uncertain_job = ledger.get(uncertain_id)
        assert uncertain_job["status"] == "approved"
        assert uncertain_job["proposal"]["vault"] == "G2OS-Staging"
        assert uncertain_job["proposal"]["actions"] == []

        action_source = (root / "VAULT" / "G2OS-Staging" / "00_Inbox"
                         / "capture-action.md")
        action_source.parent.mkdir(parents=True, exist_ok=True)
        action_source.write_text("Collect sample", encoding="utf-8")
        action_id = ledger.create(
            "triage.classify",
            {
                "path": action_source.relative_to(root).as_posix(),
                "automationId": "auto-action-review",
                "inboxItemId": "inbox-action-review",
            },
            runtime="ollama",
            sensitivity="private",
        )
        ledger.claim_job(action_id, "test")
        action_proposal = {
            **base,
            "title": "Collect sample",
            "actions": [{
                "kind": "note",
                "title": "Collect sample",
                "confidence": 0.95,
            }],
        }
        ledger.needs_review(action_id, action_proposal)
        action_item = review.build_review_item(ledger.get(action_id))
        action_review_id = ledger.create(
            "triage.review", {"items": [action_item]},
            runtime="claude", sensitivity="internal")
        ledger.claim_job(action_review_id, "test")
        ledger.complete(action_review_id, {"verdicts": [{
            "job": action_id,
            "verdict": "correct",
            "vault": "G2OS-Staging",
            "bucket": "20_Areas",
            "project": None,
            "folder": None,
            "folder_mode": "bucket-root",
            "note": "Destination is fine; action type is questionable.",
            "actions_verdict": "uncertain",
        }]})
        recorded = []
        original_record_verdict = capture_sync.record_verdict
        capture_sync.record_verdict = (
            lambda job, verdict, proposal:
            recorded.append((job, verdict, proposal))
        )
        try:
            review.cmd_process()
        finally:
            capture_sync.record_verdict = original_record_verdict
        held = ledger.get(action_id)
        assert held["status"] == "needs_review"
        assert held["review_verdict"] == "action-needs-human"
        assert held["proposal"]["folder"] is None
        assert held["proposal"]["actions"][0]["kind"] == "note"
        assert recorded and recorded[0][1]["verdict"] == "uncertain"

    print("PASS automatic triage policy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
