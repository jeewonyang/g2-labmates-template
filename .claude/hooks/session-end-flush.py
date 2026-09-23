"""SessionEnd hook: on session end, flush conversation memory.

Extracts recent conversation text and spawns memory_flush.py in the
background. Skips when CLAUDE_INVOKED_BY is set (recursion prevention).
Never blocks or fails session shutdown.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _flush_common import run_flush_hook  # noqa: E402

if __name__ == "__main__":
    try:
        sys.exit(run_flush_hook("SessionEnd"))
    except Exception as e:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        from shared import log_line
        log_line("hooks", f"SessionEnd ERROR: {e!r}")
        sys.exit(0)
