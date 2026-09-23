"""Unified CLI for all integrations. The heartbeat and chat use these too.

Examples:
  python .claude/scripts/query.py status
  python .claude/scripts/query.py gmail unread
  python .claude/scripts/query.py gmail admin
  python .claude/scripts/query.py gmail search "from:pi@lab.edu newer_than:7d"
  python .claude/scripts/query.py gmail body <message_id>
  python .claude/scripts/query.py gmail draft <to> <subject> <body_file>
  python .claude/scripts/query.py calendar upcoming [hours]
  python .claude/scripts/query.py drive list ["q= query"]

Output is plain text (LLM-ready) by default; add --json for structured data.
Advisor mode: `gmail draft` creates a Gmail DRAFT only - nothing is ever sent.
"""

import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    sys.stdout.reconfigure(errors="replace")  # cp949 console safety
except Exception:
    pass


def _emit(objs, formatter, as_json: bool):
    if as_json:
        print(json.dumps([asdict(o) for o in objs], ensure_ascii=False, indent=2))
    else:
        print(formatter(objs))


def cmd_gmail(args, as_json):
    from integrations import gmail_integration as gm
    sub = args[0] if args else "unread"
    if sub == "unread":
        _emit(gm.list_messages("is:unread newer_than:2d"), gm.format_context, as_json)
    elif sub == "admin":
        _emit(gm.list_admin_messages(), gm.format_context, as_json)
    elif sub == "search":
        _emit(gm.list_messages(args[1]), gm.format_context, as_json)
    elif sub == "body":
        print(gm.get_message_body(args[1]))
    elif sub == "draft":
        to, subject, body_file = args[1], args[2], args[3]
        body = Path(body_file).read_text(encoding="utf-8")
        draft_id = gm.create_draft(to, subject, body)
        print(f"Draft created (id={draft_id}). Review and send it yourself in Gmail.")
    else:
        print(f"unknown gmail subcommand: {sub}")
        return 2
    return 0


def cmd_calendar(args, as_json):
    from integrations import calendar_integration as cal
    hours = int(args[1]) if len(args) > 1 and args[0] == "upcoming" else 24
    _emit(cal.upcoming_events(hours_ahead=hours), cal.format_context, as_json)
    return 0


def cmd_drive(args, as_json):
    from integrations import drive_integration as dr
    if args and args[0] == "read":
        # read <file_id> <mime_type>
        print(dr.read_file_text(args[1], args[2]))
        return 0
    query = args[1] if len(args) > 1 and args[0] == "list" else "trashed = false"
    _emit(dr.list_files(query), dr.format_context, as_json)
    return 0


def cmd_papers(args, as_json):
    from integrations import papers_integration as pp
    sub = args[0] if args else "new"
    if sub == "search":
        _emit(pp.search_arxiv(args[1]), pp.format_context, as_json)
    else:  # "new"
        _emit(pp.new_papers(), pp.format_context, as_json)
    return 0


def cmd_slack(args, as_json):
    from integrations import slack_integration as sl
    sub = args[0] if args else "needs-response"
    if sub == "recent":
        hours = float(args[1]) if len(args) > 1 else 8.0
        _emit(sl.recent_messages(hours_back=hours), sl.format_context, as_json)
    elif sub == "unread":
        days = float(args[1]) if len(args) > 1 else 45.0
        _emit(sl.unread_messages(max_age_days=days), sl.format_context, as_json)
    elif sub == "since":
        # Incremental scan: messages newer than the last checkpoint. Read-only
        # re: the committed checkpoint - it stashes the scan-start time but does
        # NOT advance the checkpoint (call `mark-scanned` after drafting so an
        # interrupted run never loses messages).
        #   Positional arg = fallback window in days when there's no checkpoint
        #     yet (default 2).
        #   --all = also scan member channels (broadcasts, channel @-mentions).
        #     Complete but slow (Slack rate-limits history); default is DMs +
        #     group DMs only, which stays fast and covers everything that needs
        #     a reply.
        import time as _time
        include_channels = "--all" in args
        pos = [a for a in args[1:] if not a.startswith("--")]
        fallback = float(pos[0]) if pos else 2.0
        scan_start = _time.time()
        checkpoint = sl.get_checkpoint(fallback_days=fallback)
        msgs = sl.messages_since(checkpoint, include_channels=include_channels)
        sl.stash_scan_start(scan_start)
        if as_json:
            _emit(msgs, sl.format_context, True)
        else:
            from datetime import datetime
            since_iso = datetime.fromtimestamp(checkpoint).strftime("%Y-%m-%d %H:%M")
            scope = "DMs + channels" if include_channels else "DMs + group DMs"
            print(f"(new since {since_iso}, scanned {scope}, "
                  f"scan time {datetime.fromtimestamp(scan_start):%Y-%m-%d %H:%M})")
            print(sl.format_context(msgs))
    elif sub == "mark-scanned":
        # Advance the checkpoint. No arg => promote the scan-start stashed by the
        # last `since` (gap-safe). Pass an explicit Slack ts to pin it manually.
        ts = float(args[1]) if len(args) > 1 else None
        committed = sl.set_checkpoint(ts)
        print(f"checkpoint set to {committed:.6f}")
    elif sub == "needs-response":
        hours = float(args[1]) if len(args) > 1 else 24.0
        _emit(sl.needs_response(hours_back=hours), sl.format_context, as_json)
    elif sub == "whoami":
        uid, name = sl.whoami()
        print(f"{name} ({uid})")
    else:
        print(f"unknown slack subcommand: {sub}")
        return 2
    return 0


def cmd_github(args, as_json):
    from integrations import github_integration as gh
    sub = args[0] if args else "notifications"
    if sub == "notifications":
        _emit(gh.notifications(), gh.format_notifications, as_json)
    elif sub == "assigned":
        _emit(gh.assigned_items(), gh.format_work_items, as_json)
    elif sub == "reviews":
        _emit(gh.review_requests(), gh.format_work_items, as_json)
    else:
        print(f"unknown github subcommand: {sub}")
        return 2
    return 0


HANDLERS = {"gmail": cmd_gmail, "calendar": cmd_calendar, "drive": cmd_drive,
            "papers": cmd_papers, "slack": cmd_slack, "github": cmd_github}


def main() -> int:
    argv = [a for a in sys.argv[1:] if a != "--json"]
    as_json = "--json" in sys.argv
    if not argv or argv[0] == "status":
        from integrations import registry
        print(registry.status())
        return 0
    platform, rest = argv[0], argv[1:]
    handler = HANDLERS.get(platform)
    if not handler:
        print(f"unknown platform: {platform}. Configured: run `query.py status`")
        return 2
    try:
        return handler(rest, as_json)
    except FileNotFoundError:
        from integrations import registry
        integ = registry.REGISTRY.get(platform)
        hint = f" Setup: {integ.setup_hint}" if integ else ""
        print(f"{platform} is not configured yet.{hint}")
        print("Details: docs/INTEGRATIONS_SETUP.md")
        return 1
    except Exception as e:
        print(f"error ({platform}): {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
