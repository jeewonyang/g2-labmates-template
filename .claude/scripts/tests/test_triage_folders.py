"""Regression tests for reviewed Vault folder creation and reclassification."""

import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import ledger  # noqa: E402
from jobs import triage_classify  # noqa: E402
from triage import review as review_flow  # noqa: E402

PASS = []
FAIL = []


def check(name, condition, detail=""):
    if condition:
        PASS.append(name)
        print(f"PASS {name}")
    else:
        FAIL.append(name)
        print(f"FAIL {name}" + (f": {detail}" if detail else ""))


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        ledger_dir = root / "ledger"
        ledger.LEDGER_DIR = ledger_dir
        ledger.EVENTS = ledger_dir / "events.jsonl"
        ledger.SNAPSHOT = ledger_dir / "snapshot.json"
        triage_classify.REPO_ROOT = root

        inbox = root / "VAULT" / "Research-Private" / "00_Inbox"
        bucket = root / "VAULT" / "Research-Private" / "30_Resources"
        inbox.mkdir(parents=True)
        bucket.mkdir(parents=True)
        source = inbox / "protein-design-note.md"
        source.write_text("Reusable protein design reference", encoding="utf-8")

        jid = ledger.create(
            "triage.classify",
            {"path": source.relative_to(root).as_posix()},
            runtime="ollama",
            sensitivity="private",
        )
        ledger.claim_job(jid, "test")
        proposal = {
            "vault": "Research-Private",
            "bucket": "30_Resources",
            "project": None,
            "folder": "Protein Design/Methods",
            "folder_mode": "create",
            "folder_rationale": "Durable reusable method category",
        }
        ledger.needs_review(jid, proposal)
        outcome = triage_classify.prepare_folder_reclassification(
            ledger.get(jid), proposal, actor="test-review")

        created = bucket / "Protein Design" / "Methods"
        replacement = ledger.get(outcome["reclassificationJobId"])
        check("reviewed folder is created", created.is_dir())
        check("source classification is superseded",
              ledger.get(jid)["status"] == "superseded")
        check("replacement runs a second classification pass",
              replacement["payload"]["reclassificationPass"] == 1)
        check("replacement records the expanded folder",
              replacement["payload"]["createdFolder"]
              == "Research-Private/30_Resources/Protein Design/Methods")

        prompt = triage_classify.build_prompt(replacement["payload"])
        check("second prompt identifies reclassification",
              "RECLASSIFICATION PASS 1" in prompt)
        check("new folder appears as an existing option",
              "Protein Design/Methods" in prompt)
        check("second pass forbids another new folder",
              "Do NOT propose another new folder" in prompt)

        final = {
            **proposal,
            "folder_mode": "existing",
        }
        triage_classify.apply(replacement, final)
        copied = created / source.name
        check("second-pass classification files into the new folder",
              copied.is_file())
        check("copy semantics preserve the inbox source", source.is_file())

        unsafe = [
            "../escape",
            "Finance",
            "_private",
            "CON",
            "one/two/three",
            "C:/absolute",
        ]
        blocked = 0
        for value in unsafe:
            try:
                triage_classify.safe_folder_parts(value)
            except ValueError:
                blocked += 1
        check("unsafe folder paths fail closed", blocked == len(unsafe),
              f"blocked {blocked}/{len(unsafe)}")

        try:
            triage_classify.prepare_folder_reclassification(
                {"job": "fake", "payload": {}},
                {
                    "vault": "Research-Private",
                    "bucket": "10_Projects",
                    "project": "DifferentProject",
                    "folder": "NewProject",
                    "folder_mode": "create",
                },
                actor="test",
            )
            project_guarded = False
        except ValueError:
            project_guarded = True
        check("new project must match its folder", project_guarded)

        second_source = inbox / "microscopy-reference.md"
        second_source.write_text("Reusable microscopy reference", encoding="utf-8")
        second_job = ledger.create(
            "triage.classify",
            {"path": second_source.relative_to(root).as_posix()},
            runtime="ollama",
            sensitivity="private",
        )
        ledger.claim_job(second_job, "test")
        second_proposal = {
            "vault": "Research-Private",
            "bucket": "30_Resources",
            "project": None,
            "folder": "Microscopy",
            "folder_mode": "create",
            "folder_rationale": "Reusable imaging reference category",
            "confidence": 0.95,
            "title": "Microscopy reference",
            "reason": "No existing folder fits",
            "actions": [],
        }
        ledger.needs_review(second_job, second_proposal)
        review_job = ledger.create(
            "triage.review",
            {"items": [{"job": second_job}]},
            runtime="claude",
            sensitivity="internal",
        )
        ledger.claim_job(review_job, "reviewer")
        ledger.complete(review_job, {
            "verdicts": [{
                "job": second_job,
                "verdict": "confirm",
                "vault": "Research-Private",
                "bucket": "30_Resources",
                "project": None,
                "folder": "Microscopy",
                "folder_mode": "create",
                "note": "Durable category; no existing folder is equivalent",
                "actions_verdict": "not_applicable",
            }],
        })
        original_argv = sys.argv
        sys.argv = ["review.py", "process"]
        try:
            review_flow.cmd_process()
        finally:
            sys.argv = original_argv
        check("confirmed folder proposal automatically queues reclassification",
              ledger.get(second_job)["status"] == "superseded")
        check("processed verifier output cannot replay",
              ledger.get(review_job).get("_consumed") is True)
        check("automatic folder proposal creates the reviewed folder",
              (bucket / "Microscopy").is_dir())

        project_source = inbox / "new-project-plan.md"
        project_source.write_text("Defined project plan", encoding="utf-8")
        project_job = ledger.create(
            "triage.classify",
            {"path": project_source.relative_to(root).as_posix()},
            runtime="ollama",
            sensitivity="private",
        )
        ledger.claim_job(project_job, "test")
        project_proposal = {
            "vault": "Research-Private",
            "bucket": "10_Projects",
            "project": "04_NewProject",
            "folder": "04_NewProject",
            "folder_mode": "create",
            "folder_rationale": "Defined outcome-driven project",
            "confidence": 0.95,
            "title": "New project",
            "reason": "New active effort",
            "actions": [],
        }
        ledger.needs_review(project_job, project_proposal)
        project_review = ledger.create(
            "triage.review",
            {"items": [{"job": project_job}]},
            runtime="claude",
            sensitivity="internal",
        )
        ledger.claim_job(project_review, "reviewer")
        ledger.complete(project_review, {
            "verdicts": [{
                "job": project_job,
                "verdict": "confirm",
                "vault": "Research-Private",
                "bucket": "10_Projects",
                "project": "04_NewProject",
                "folder": "04_NewProject",
                "folder_mode": "create",
                "note": "Appears to be a genuine project",
                "actions_verdict": "not_applicable",
            }],
        })
        original_argv = sys.argv
        sys.argv = ["review.py", "process"]
        try:
            review_flow.cmd_process()
        finally:
            sys.argv = original_argv
        check("new project folder waits for explicit human approval",
              ledger.get(project_job)["status"] == "needs_review")
        check("verifier alone cannot create a new project folder",
              not (root / "VAULT" / "Research-Private"
                   / "10_Projects" / "04_NewProject").exists())

    print()
    if FAIL:
        print(f"{len(FAIL)} FAILED: {', '.join(FAIL)}")
        return 1
    print(f"All {len(PASS)} triage folder tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
