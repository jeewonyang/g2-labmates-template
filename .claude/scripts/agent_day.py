"""The daily run: produce every scheduled team's work, then drain the queue.

One entry point for "the Second Brain operates on a daily schedule". It does not
reimplement anything - it sequences the pieces that already exist:

    teams.scheduled_today()  ->  producers.run()  ->  dispatch.drain()

WHY THIS COSTS NOTHING PER RUN (2026-07-26)
the owner opted out of the 30-minute heartbeat on 2026-07-09 to control API spend,
and asked on 2026-07-26 that automation use their Claude and Codex *subscriptions*
rather than an API key. Both runtimes now shell out to their CLIs:
`claude -p` authenticates with their subscription login (verified working headless
on this machine - some organizations' Claude accounts block headless SDK
subscription auth, but the CLI is not affected), and `codex exec` reports "Logged in using ChatGPT". Ollama is
local. So a daily run spends no API credit at all.

What it does spend is subscription rate limit, which is why RUNTIME_CAPS exists.
An unbounded drain on a day with a large intake backlog would burn their limit on
triage and leave nothing for interactive work. Caps are per run, per runtime,
and local ollama gets the loosest one because it costs only electricity.

ORDERING
Local first, then cloud. If the daily budget runs out, it should run out on the
cheap tier, and the private jobs - which may only run locally - are the ones
that cannot be deferred to an interactive session later.

  python .claude/scripts/agent_day.py --dry-run     # plan only; enqueue nothing
  python .claude/scripts/agent_day.py               # today's teams, produce+drain
  python .claude/scripts/agent_day.py --team research
  python .claude/scripts/agent_day.py --produce-only
  python .claude/scripts/agent_day.py --drain-only
"""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Recursion guard: this spawns claude CLI sessions, whose SessionEnd hook would
# otherwise spawn a memory flush, which spawns a session, and so on.
os.environ.setdefault("CLAUDE_INVOKED_BY", "agent-day")

import dispatch  # noqa: E402
import ledger  # noqa: E402
import producers  # noqa: E402
import teams  # noqa: E402
import apply_jobs  # noqa: E402
from triage import review as triage_review_flow  # noqa: E402
from shared import append_to_daily_log, log_line, now  # noqa: E402

# Per-run ceilings. Local is nearly free; cloud runtimes draw on their
# subscription rate limit, which interactive work also needs.
RUNTIME_CAPS = {"ollama": 200, "codex": 20, "claude": 40}

# Drain order: cheapest and most-constrained-by-routing first.
DRAIN_ORDER = ("ollama", "codex", "claude")

PAUSE_FILE = Path(__file__).resolve().parents[1] / "data" / "state" / "PAUSED"

# Which machine is allowed to run the SCHEDULED automation.
#
# The ledger and all of .claude/data/ are gitignored and machine-local, so the
# desktop and a laptop each have their own queue - there is no shared lock to
# take. What they DO share is the vault, over Syncthing. Two machines producing
# from the same vault would digest the same papers twice, write two same-named
# digests, and hand Syncthing a conflict to resolve.
#
# So primacy is declared in the one place both machines can see: a file inside
# the synced vault. Interactive work (a session on the Mac, `--team`, `--force`)
# is never blocked - only the unattended scheduled run.
# Markdown, not a dotfile: the repo's gitignore is an allowlist that versions
# only *.md under VAULT/, so a dotfile would never reach the other machine -
# and Obsidian does not show dotfiles, so they would never find it either.
PRIMARY_MARKER = (Path(__file__).resolve().parents[2]
                  / "VAULT" / "Memory" / "AGENT_PRIMARY.md")


def primary_host() -> str | None:
    """The hostname inside the first fenced block of AGENT_PRIMARY.md."""
    try:
        text = PRIMARY_MARKER.read_text(encoding="utf-8")
    except OSError:
        return None
    in_fence = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            if in_fence:
                break
            in_fence = True
            continue
        if in_fence and stripped:
            return stripped
    return None


def check_primary() -> bool:
    """True if this machine may run the scheduled automation."""
    declared = primary_host()
    if not declared:
        return True             # no marker: single-machine setup, carry on
    import socket
    me = socket.gethostname()
    if me.lower() == declared.lower():
        return True
    print(f"not the primary agent host: this is {me!r}, "
          f"{PRIMARY_MARKER.name} names {declared!r}.")
    print("The vault is shared, so only one machine runs the scheduled teams.")
    print("Override for a one-off run with --force.")
    return False


def _flag(name: str) -> bool:
    return name in sys.argv


def _opt(name: str, default=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def _in_window(manifest: dict, window: str) -> bool:
    """Split teams by their declared run_at, so one task can serve both halves.

    Registering five scheduled tasks to honor five run_at values would be five
    things to keep in sync. Two triggers on one task, filtered here, gives the
    same result: admin/research run in the morning, vault/security at
    night, and changing a manifest's run_at needs no scheduler change.
    """
    if window == "all":
        return True
    run_at = manifest.get("run_at") or "09:00"
    try:
        hour = int(str(run_at).split(":")[0])
    except ValueError:
        hour = 9
    return hour < 12 if window == "morning" else hour >= 12


def selected_teams() -> list[dict]:
    one = _opt("--team")
    if one:
        m = teams.get(one)
        if not m:
            print(f"no such team: {one} (have: {', '.join(teams.ids())})")
            return []
        return [m]

    window = _opt("--window", "all")
    if window == "auto":
        # Task Scheduler has no per-trigger arguments, so one action serves both
        # daily triggers and the clock decides which half runs.
        window = "morning" if now().hour < 12 else "evening"
    if window not in ("all", "morning", "evening"):
        print(f"unknown --window {window!r} (all|morning|evening|auto)")
        return []
    return [m for m in teams.scheduled_today(now().weekday())
            if _in_window(m, window)]


def produce(selected, *, dry_run: bool) -> dict:
    """Run each team's producer. One team's failure must not stop the rest."""
    summary = {}
    for m in selected:
        tid = m["id"]
        try:
            res = producers.run(m["producer"], dry_run=dry_run)
            summary[tid] = res
            detail = res.get("by_kind") or res.get("detail") or ""
            print(f"  {tid:<10} {res.get('planned', res.get('created', '?'))} "
                  f"planned  {detail}")
        except Exception as e:
            summary[tid] = {"error": repr(e)}
            log_line("agent-day", f"producer {tid} failed: {e!r}")
            print(f"  {tid:<10} ERROR {type(e).__name__}: {e}")
    return summary


def drain(*, dry_run: bool) -> dict:
    """Drain the queue, cheapest runtime first, capped per runtime."""
    totals = {}
    worker = f"agent-day-{os.getpid()}"
    for rt in DRAIN_ORDER:
        cap = RUNTIME_CAPS.get(rt, 20)
        try:
            counts = dispatch.drain(worker=worker, runtimes_filter=[rt],
                                    max_jobs=cap, dry_run=dry_run)
        except Exception as e:
            log_line("agent-day", f"drain {rt} failed: {e!r}")
            print(f"  {rt:<8} ERROR {type(e).__name__}: {e}")
            continue
        if counts:
            totals[rt] = counts
            print(f"  {rt:<8} {counts}")
        else:
            print(f"  {rt:<8} nothing to do")

        # Local classification is tier one. Queue sanitized independent audits
        # immediately so the same daily cycle can run tier two instead
        # of leaving every classification stranded in needs_review.
        if rt == "ollama" and not dry_run:
            argv = sys.argv
            sys.argv = ["review.py", "enqueue", "--max", "1000"]
            try:
                triage_review_flow.cmd_enqueue()
            finally:
                sys.argv = argv

    if not dry_run:
        # Consume verifier verdicts, then perform every already-approved,
        # reversible effect. New project taxonomy and external calendar
        # proposals remain review-gated.
        argv = sys.argv
        sys.argv = ["review.py", "process"]
        try:
            triage_review_flow.cmd_process()
        finally:
            sys.argv = argv

        # A confirmed new-folder proposal creates only the directory and
        # enqueues one replacement classification. Finish that bounded second
        # pass in the same Agent Day run instead of waiting until the next
        # morning/evening schedule.
        reclassifications = [
            job for job in ledger.query(status="created", kind="triage.classify")
            if int((job.get("payload") or {}).get("reclassificationPass") or 0) > 0
        ][:20]
        if reclassifications:
            completed = 0
            for source in reclassifications:
                claimed = ledger.claim_job(source["job"], worker)
                if claimed and dispatch.run_one(claimed) != "failed":
                    completed += 1
            print(f"  reclass  {completed}/{len(reclassifications)} local passes")

            sys.argv = ["review.py", "enqueue", "--max", "1000"]
            try:
                triage_review_flow.cmd_enqueue()
            finally:
                sys.argv = argv
            counts = dispatch.drain(
                worker=worker,
                runtimes_filter=[triage_review_flow.triage_review.DEFAULT_RUNTIME],
                max_jobs=RUNTIME_CAPS.get(
                    triage_review_flow.triage_review.DEFAULT_RUNTIME, 20),
                dry_run=False,
            )
            if counts:
                totals["reclassification-review"] = counts
            sys.argv = ["review.py", "process"]
            try:
                triage_review_flow.cmd_process()
            finally:
                sys.argv = argv

        sys.argv = ["apply_jobs.py", "--max", "200"]
        try:
            rc = apply_jobs.main()
            totals["apply"] = {"ok": 1 if rc == 0 else 0}
        finally:
            sys.argv = argv
    return totals


def main() -> int:
    dry = _flag("--dry-run")
    started = time.monotonic()

    if PAUSE_FILE.exists() and not _flag("--force"):
        print(f"paused: {PAUSE_FILE} exists (remove it, or pass --force)")
        return 0

    # Only gates the unattended path: an explicit --team run is someone sitting
    # at the machine asking for it, which is always allowed.
    if not _flag("--force") and not _opt("--team") and not check_primary():
        return 0

    selected = selected_teams()
    if not selected:
        print("no teams scheduled today")
        return 0

    print(f"agent-day {now():%Y-%m-%d %H:%M}  "
          f"teams: {', '.join(m['id'] for m in selected)}"
          f"{'  [DRY RUN]' if dry else ''}")

    prod = {}
    if not _flag("--drain-only"):
        print("\nproduce:")
        prod = produce(selected, dry_run=dry)

    drained = {}
    if not _flag("--produce-only"):
        print("\ndrain:")
        drained = drain(dry_run=dry)

    by_status = ledger.stats().get("by_status", {})
    queued = by_status.get("created", 0)
    review = by_status.get("needs_review", 0)
    failed = by_status.get("failed", 0)
    elapsed = time.monotonic() - started
    print(f"\nqueue: {queued} queued, {review} need review, "
          f"{failed} failed   ({elapsed:.0f}s)")

    if not dry:
        lines = []
        for tid, res in prod.items():
            if "error" in res:
                lines.append(f"- {tid}: producer error - {res['error'][:160]}")
            else:
                by = res.get("by_kind") or {}
                if by:
                    lines.append(f"- {tid}: enqueued " + ", ".join(
                        f"{v} {k}" for k, v in sorted(by.items())))
        for rt, counts in drained.items():
            lines.append(f"- ran {rt}: {counts}")
        lines.append(f"- queue now: {review} awaiting review at /ops")
        if lines:
            append_to_daily_log("Agent day", "\n".join(lines))
        log_line("agent-day",
                 f"produced={sum(r.get('created') or 0 for r in prod.values())} "
                 f"drained={drained} needs_review={review}")

        if review:
            try:
                from notify import toast
                toast("Second Brain",
                      f"{review} item(s) need your review")
            except Exception:
                pass            # a missing toast must never fail the run

    return 0


if __name__ == "__main__":
    sys.exit(main())
