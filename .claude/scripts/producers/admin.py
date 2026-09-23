"""Administrative producer - delegates to the Gmail and Slack cursor owners.

Deliberately thin. heartbeat_produce.py owns the Gmail snapshot cursor, while
slack_followup.py owns the read-state-independent DM high-water mark. Reproducing
either scan here would create competing cursors and silently lose messages.

So the team manifest points at this module, and this module calls that script.
The dashboard's Admin scan and the scheduled Admin team hit the same path.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TEAM = "admin"


def produce(*, dry_run: bool = False) -> dict:
    import heartbeat_produce
    import slack_followup

    argv = sys.argv
    # heartbeat_produce.main() reads flags from sys.argv. --force is right here:
    # the active-hours gate belongs to the daily schedule, which already decided
    # this should run, not to the producer.
    sys.argv = ["heartbeat_produce", "--force"] + (["--dry-run"] if dry_run else [])
    try:
        gmail_rc = heartbeat_produce.main()
        sys.argv = ["slack_followup"] + (["--dry-run"] if dry_run else [])
        slack_rc = slack_followup.main()
    finally:
        sys.argv = argv

    return {
        "created": None,
        "rc": gmail_rc or slack_rc,
        "detail": (
            "delegated to heartbeat_produce.py (Gmail cursor) and "
            "slack_followup.py (read-independent DM cursor)"
        ),
    }
