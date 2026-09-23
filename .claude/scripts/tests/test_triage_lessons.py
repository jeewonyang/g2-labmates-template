"""Tests for the triage correction-learning log.

The load-bearing property is the sanitization split: the LOCAL classifier
prompt may carry capture titles, but the CLOUD verifier prompt and the
git-versioned memory file must carry aggregate counts only.

Plain-python, no pytest - matches test_ledger.py.

  python .claude/scripts/tests/test_triage_lessons.py
"""

import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

from triage import lessons  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"{'PASS' if cond else 'FAIL'} {name}{'' if cond else '  -> ' + detail}")


def fresh(tmp: Path) -> None:
    tmp.mkdir(parents=True, exist_ok=True)
    lessons.STATE_FILE = tmp / "triage-corrections.jsonl"
    lessons.MEMORY_FILE = tmp / "TRIAGE_TENDENCIES.md"


def proposal(**kw):
    base = {
        "vault": "Research-Private",
        "bucket": "30_Resources",
        "folder": None,
        "folder_mode": "bucket-root",
        "actions": [{"kind": "note", "title": "x"}],
    }
    base.update(kw)
    return base


def test_records_a_diff(tmp):
    fresh(tmp / "diff")
    row = lessons.record(
        "ops-correction",
        title="Collect brain samples",
        old=proposal(),
        new=proposal(actions=[{"kind": "task", "title": "x"}]),
    )
    check("a changed action kind is recorded", row is not None)
    check("the diff names the moved field",
          row and row["diffs"] == [
              {"field": "action_kind", "from": "note", "to": "task"}],
          str(row and row["diffs"]))


def test_no_op_is_not_recorded(tmp):
    fresh(tmp / "noop")
    row = lessons.record("ops-correction", title="t",
                         old=proposal(), new=proposal())
    check("saving without changes records nothing", row is None)


def test_decline_is_recorded(tmp):
    fresh(tmp / "decline")
    row = lessons.record("ops-decline", title="t", old=proposal(), new=None,
                         note="wrong vault entirely")
    check("a decline is recorded", row is not None and row["declined"])
    counts = lessons.aggregate()
    check("a decline aggregates as a declined pattern",
          any(k[0] == "declined" for k in counts), str(dict(counts)))


def test_local_prompt_includes_titles(tmp):
    fresh(tmp / "local")
    lessons.record("ops-correction", title="Collect brain samples",
                   old=proposal(),
                   new=proposal(actions=[{"kind": "task", "title": "x"}]))
    block = lessons.prompt_block()
    check("local prompt names the corrected field",
          "action_kind" in block and "note -> task" in block, block)
    check("local prompt may include the capture title",
          "Collect brain samples" in block, block)


def test_cloud_prompt_is_aggregate_only(tmp):
    fresh(tmp / "cloud")
    for _ in range(2):
        lessons.record("ops-correction", title="Collect brain samples",
                       old=proposal(),
                       new=proposal(actions=[{"kind": "task", "title": "x"}]))
    block = lessons.review_block()
    check("cloud prompt shows the repeated pattern",
          "note -> task" in block and "2x" in block, block)
    check("cloud prompt leaks no capture title",
          "Collect brain samples" not in block, block)


def test_single_occurrence_stays_local(tmp):
    fresh(tmp / "threshold")
    lessons.record("ops-correction", title="one off", old=proposal(),
                   new=proposal(vault="G2OS-Staging"))
    check("a one-time correction does not reach the cloud prompt",
          lessons.review_block() == "", lessons.review_block())
    check("but it does reach the local prompt",
          "G2OS-Staging" in lessons.prompt_block())


def test_memory_file_is_aggregate_only(tmp):
    fresh(tmp / "memory")
    lessons.record("ops-correction", title="Collect brain samples",
                   old=proposal(),
                   new=proposal(actions=[{"kind": "task", "title": "x"}]))
    text = lessons.MEMORY_FILE.read_text(encoding="utf-8")
    check("the versioned memory file is written", bool(text))
    check("the versioned memory file leaks no title",
          "Collect brain samples" not in text, text[:300])
    check("the versioned memory file carries the pattern",
          "note -> task" in text, text[:300])


def test_snapshot_accepts_reduced_input(tmp):
    fresh(tmp / "reduced")
    row = lessons.record("applied-capture-correction", title="t",
                         old={"action_kind": "note"},
                         new={"action_kind": "task"})
    check("a bare action_kind pair records one diff",
          row is not None and len(row["diffs"]) == 1, str(row and row["diffs"]))


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        test_records_a_diff(tmp)
        test_no_op_is_not_recorded(tmp)
        test_decline_is_recorded(tmp)
        test_local_prompt_includes_titles(tmp)
        test_cloud_prompt_is_aggregate_only(tmp)
        test_single_occurrence_stays_local(tmp)
        test_memory_file_is_aggregate_only(tmp)
        test_snapshot_accepts_reduced_input(tmp)

    print()
    if FAIL:
        print(f"{len(FAIL)} FAILED: {', '.join(FAIL)}")
        return 1
    print(f"All {len(PASS)} triage-lesson tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
