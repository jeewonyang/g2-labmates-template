"""Regression test for append-only failed-job retries."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ledger  # noqa: E402
import retry_failures  # noqa: E402


def check(condition, label):
    if not condition:
        raise AssertionError(label)
    print(f"PASS {label}")


with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    ledger.LEDGER_DIR = root / "ledger"
    ledger.EVENTS = ledger.LEDGER_DIR / "events.jsonl"
    ledger.SNAPSHOT = ledger.LEDGER_DIR / "snapshot.json"
    retry_failures.STATE_FILE = root / "retry-state.json"

    old = ledger.create(
        "echo.check",
        {"text": "retry me"},
        runtime="ollama",
        sensitivity="internal",
    )
    ledger.fail(old, "temporary error")

    original_run_one = retry_failures.dispatch.run_one

    def complete_locally(job):
        ledger.complete(job["job"], {"echoed": "retry me", "word_count": 2})
        return "completed"

    try:
        retry_failures.dispatch.run_one = complete_locally
        result = retry_failures.retry([old])
    finally:
        retry_failures.dispatch.run_one = original_run_one

    replacement = result[0]["replacement"]
    old_state = ledger.get(old)
    replacement_state = ledger.get(replacement)

check(old_state["status"] == "resolved",
      "original failure is resolved after replacement succeeds")
check(old_state["replacement_job"] == replacement,
      "original failure points to its replacement")
check(replacement_state["status"] == "completed",
      "replacement preserves its successful terminal state")
check(replacement_state["parent"] == old,
      "replacement records the original failure as its parent")

print("\nAll failed-job retry tests passed.")
