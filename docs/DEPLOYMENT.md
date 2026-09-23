# Deployment (Windows, local-only)

The Second Brain runs entirely on this machine — no VPS, no cloud sync.

## Web host recovery

Web uptime is supervised separately from the optional agent schedules below.
This separation is deliberate: disabling automatic scans must never turn off
the dashboard.

Install or refresh the three per-user tasks (no administrator rights required):

```powershell
powershell -ExecutionPolicy Bypass -File .claude\scripts\setup_web_host.ps1
```

| Task | Role |
|------|------|
| `SecondBrain-WebHost` | Runs `npm run dev` without opening a browser, starts at logon, and restarts when Node exits. |
| `SecondBrain-WebWatchdog` | Checks the G2-specific `/api/health` marker every two minutes. Three consecutive failures request recovery, so a transient Next.js compile does not cause a restart loop. |
| `SecondBrain-WebRecover` | Stops and relaunches the host independently of port 3000. An orphan listener is stopped only when its command line proves it belongs to this repo. |

The existing `start-second-brain.bat` desktop launcher uses
`SecondBrain-WebRecover` when it is installed, falling back to its original
standalone dev-server launch only on machines where the tasks do not exist.

Manage it from the repo root:

```powershell
# task state plus live health
powershell -ExecutionPolicy Bypass -File .claude\scripts\setup_web_host.ps1 -Status

# clean restart; also available as recover-g2.bat
powershell -ExecutionPolicy Bypass -File .claude\scripts\setup_web_host.ps1 -Recover

# explicitly stop and unregister only the three web-host tasks
powershell -ExecutionPolicy Bypass -File .claude\scripts\setup_web_host.ps1 -Remove
```

Logs are ignored runtime data under `.claude/data/logs/`:
`web-host.log`, `web-watchdog.log`, and `web-recovery.log`. To intentionally
hold the host down during maintenance, create
`.claude/data/state/WEB_HOST_PAUSED`; remove the marker and run recovery when
maintenance is complete.

### Remote fallback over Tailscale

The watchdog normally repairs G2 without intervention. For a manual fallback,
enable Windows OpenSSH Server as an automatic service, use key authentication,
and restrict its firewall rule to the Tailscale range (`100.64.0.0/10`). From a
tailnet device, run:

```text
ssh <windows-user>@your-machine "C:\Users\<you>\Documents\SecondBrain\recover-g2.bat"
```

This recovery path depends on Windows, Tailscale, and SSH, but not on G2. It
cannot wake a powered-off or sleeping PC; that requires Wake-on-LAN or another
always-on device. Microsoft setup reference:
https://learn.microsoft.com/windows-server/administration/openssh/openssh_install_firstuse

## On-demand by default (2026-07-09)

There is **no automatic scanning**. the owner opted out of the 30-minute heartbeat
to control token spend, so nothing calls the Claude API on a schedule. You scan
when you want:

- **Dashboard:** the "Check messages & calendar" button on Today
  (`POST /api/secondbrain/heartbeat` →
  `agent_day.py --team admin --force`). This scans Gmail plus every new
  one-to-one Slack DM regardless of read state, then drafts replies.
- **Chat:** `/draft-replies` in a Claude Code session.

The scan also folds in a **lightweight daily reflection** — the first scan of
each calendar day consolidates the previous day's log into `MEMORY.md`
(throttled once/day via `reflection_date` in `heartbeat-state.json`), so
memory curation happens without a separate scheduled job. Repeat clicks the
same day skip it, so no extra tokens.

## Getting a change onto the machine that serves the dashboard (2026-09-16)

Pushing is not deploying. The dashboard is served by one machine, and a commit
made from a laptop, a work computer over Tailscale, or a cloud Claude session
only reaches it when that machine fast-forwards. Three of the four steps are not
a `git pull`:

| Step | Done by | Why it is not automatic |
|---|---|---|
| New commits in the working tree | `git merge --ff-only` | — |
| Dependencies / database schema | `npm ci`, `npm run db:push` | only when the lockfile or schema changed |
| **Scheduled tasks re-registered** | `setup_scheduler.ps1` with their flags | **Task Scheduler stores a snapshot of each trigger.** Editing `day-schedule.json` changes what the script *would* register and nothing else, so the agents keep firing at the old times until the tasks are registered again. |
| Web host on the new code | `SecondBrain-WebRecover` | `next dev` hot-reloads a page edit; only startup-time config (lockfile, next/ts config, schema) needs a restart |

`apply_update.ps1` does all four, and `SecondBrain-Update` (registered by
`setup_web_host.ps1`) runs it every 30 minutes, so a merge lands here by itself.

```powershell
update-g2.bat                 # update now
update-g2.bat -Status         # commits behind + per-task schedule drift
powershell -File .claude\scripts\setup_web_host.ps1 -NoAutoUpdate   # decline automatic pulls
```

It is safe by construction, which is what makes leaving it unattended
reasonable: it fast-forwards when it can and merges upstream over this machine's
own commits otherwise, aborting cleanly on a conflict (no rebase, reset, stash,
push, or force); agent writes under `VAULT/Memory/` are committed locally as
"Vault: agent writes on <machine> before update" so they travel with the repo,
while uncommitted code anywhere else stops the update untouched; an untracked
vault file that upstream now tracks (a daily log both machines wrote) is renamed
aside as `<name>.local-<stamp>`, never deleted; and it follows the checked-out
branch's own upstream, so an unmerged branch cannot deploy itself. Re-registration reproduces exactly the tasks already registered —
it never switches on automation that was left off. Log:
`.claude/data/logs/update.log`; the same facts appear on `/settings` under
**Deployment**.

Nothing about a Claude session needs restarting for any of this. A `CLAUDE.md`
change only affects the *next* session's injected context.

## Automation that lives outside this repo

`setup_scheduler.ps1` cannot retime what it did not register. The Codex app's
`rho-daily-biorxiv-scan` runs the research team at 09:00 — now inside their
deep-work block, and duplicating work the 05:00 morning run already queues.
**Retire it** in the Codex app (Automations → the task → delete); if it is kept
for any reason, set it to 05:00 to match `morning_run`. It is listed under
`automation.external` in `day-schedule.json` so it stays visible, and
`apply_update.ps1` prints it after every update.

## Optional scheduled tasks (opt-in)

`setup_scheduler.ps1` registers **nothing** by default. Opt into automation with
flags (all per-user, logon-only — need the desktop session for toasts + token
files):

| Flag | Task | Schedule | Cost |
|------|------|----------|------|
| `-EnableHeartbeat` | `SecondBrain-Heartbeat` | every 30 min, 08:00–20:00 | **spends tokens** |
| `-EnableReflection` | `SecondBrain-Reflection` | daily 05:30 | **spends tokens** |
| `-EnableWiki` | `SecondBrain-WikiDaily` | daily 22:30 | free (pure Python) |
| `-EnableDailyRun` | `SecondBrain-DailyRun` + `SecondBrain-AdminCheck` | teams at 05:00/21:30; Admin every 2h, 08:00-20:00 | subscription CLIs/local |
| `-EnableSlackMonitor` | `SecondBrain-SlackFollowup` | hourly, 08:00-20:00; all new one-to-one DMs independent of read state | no model/API calls |

Changing any of these times means editing `day-schedule.json` **and**
re-registering (`update-g2.bat`, or re-running `setup_scheduler.ps1` with the
same flags). `update-g2.bat -Status` says which tasks have drifted.

Every hour in this table is read from `.claude/agents/day-schedule.json`
(`automation` section) when the script runs; the table is a snapshot as of
2026-09-16. Their day drives the times: the morning teams finish before they wake
at 06:00 so the brief and drafts are on `/today` for their planning hour, the
intraday checks span their work blocks (08:00 to the end of light work at 20:00)
and stay quiet through the workout and wind-down, the evening teams start after
their day ends at 21:00, and the wiki runs after them. To move their day, edit that
file and re-run `setup_scheduler.ps1` with the same flags; `setup_max_cycle.ps1`
(weekdays 10:30) is separate on purpose because it follows the market, not them.

## Manage

```powershell
# on-demand steady state: remove all scheduled tasks (default, no flags)
powershell -ExecutionPolicy Bypass -File .claude\scripts\setup_scheduler.ps1

# opt into a specific automation (example: the free wiki job)
powershell -ExecutionPolicy Bypass -File .claude\scripts\setup_scheduler.ps1 -EnableWiki

# show status
powershell -ExecutionPolicy Bypass -File .claude\scripts\setup_scheduler.ps1 -Status

# remove everything
powershell -ExecutionPolicy Bypass -File .claude\scripts\setup_scheduler.ps1 -Remove
```

Trigger a run by hand: `Start-ScheduledTask -TaskName SecondBrain-Heartbeat`.

## Interpreter choice

Scheduled tasks run via `.claude\scripts\run_task.bat`, which calls the
**miniconda** interpreter (`python`). This is a
real, non-Store Python; the Microsoft Store `python.exe` is an app-execution
alias that Task Scheduler runs unreliably in its non-interactive context. All
dependencies are installed in miniconda.

## Logs

- `.claude/data/logs/scheduler.log` — raw stdout/stderr of scheduled runs
- `.claude/data/logs/heartbeat.log`, `reflection.log`, `notify.log` — structured
- Last task result: the `-Status` command above (0 = success)

## Cost estimate

- **Claude API** (background Agent SDK calls): heartbeat ≈ $0.05/run × ~20
  weekday runs ≈ $1/day; guardrail pre-flight + daily reflection + memory
  flush add a little. Roughly **$25–40/month** at current usage, less on quiet
  days (state diffing means no-delta runs skip the expensive reasoning call).
- **Everything else is local and free**: FastEmbed (CPU), SQLite, the vault.
- No VPS, no database hosting.

## If you add a second machine later (not set up)

The PRD's Phase 9 describes VPS + `git-sync` with a `concat-both` merge driver
for the append-only daily logs. Not implemented — this is a single-machine
deployment. Revisit that section if you ever want laptop↔desktop sync.
