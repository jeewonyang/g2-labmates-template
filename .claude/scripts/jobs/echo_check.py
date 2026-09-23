"""A trivial job kind used to smoke-test the dispatcher end to end.

Runs locally, requires no review, and touches nothing. Keep it: it is the
cheapest way to confirm the ledger -> dispatcher -> runtime path still works
after a change, without spending cloud tokens or writing to the vault.

  python .claude/scripts/ledger.py create echo.check '{"text":"hello"}' \
      --runtime ollama --sensitivity internal
  python .claude/scripts/dispatch.py --once --kinds echo.check
"""

KIND = "echo.check"
DEFAULT_RUNTIME = "ollama"
SENSITIVITY = "internal"
REVIEW_REQUIRED = False          # effect is confined to the ledger itself
TIMEOUT = 180

SCHEMA = {
    "type": "object",
    "required": ["echoed", "word_count"],
    "properties": {
        "echoed": {"type": "string"},
        "word_count": {"type": "integer"},
    },
}


def build_prompt(payload) -> str:
    text = (payload or {}).get("text", "")
    return (
        "Echo the text below back verbatim in the `echoed` field and put its "
        "word count in `word_count`. Return only the JSON object.\n\n"
        f"TEXT: {text}"
    )


def apply(job, result) -> None:
    """No side effect - REVIEW_REQUIRED is False, so this is never called."""
    return None
