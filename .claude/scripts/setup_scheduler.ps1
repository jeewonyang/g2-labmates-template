<#
Second Brain scheduling. DEFAULT IS ON-DEMAND: no automatic scans, so API
tokens are only spent when the owner clicks "Run scan now" on the dashboard (or
runs /draft-replies in chat).

Every time below comes from .claude/agents/day-schedule.json ("automation"
section), which is derived from the owner's day (wake 06:00, at lab 08:00, light
work until 20:00, workout 20:00-21:00, bed prep 22:00; set 2026-09-16). Change
the day there, re-run this script,
and every task moves together - do not hard-code an hour in this file.
Defaults as of 2026-09-16:

Automation is opt-in via flags:
  -EnableHeartbeat   every 30 min across the work blocks, 08:00-20:00 (SPENDS TOKENS each run)
  -EnableReflection  daily 05:30, promotes daily log to MEMORY.md (SPENDS TOKENS)
  -EnableWiki        daily 22:30, wiki scan/lint/reindex (pure Python, NO tokens)
  -EnableSlackMonitor hourly 08:00-20:00, read-only all-DM drafting plus
                     actionable-task notifications (NO model/API tokens)
  -EnableDailyRun    agent_day.py twice daily (05:00 morning teams, so the
                     brief and drafts are ready when they wake at 06:00;
                     21:30 evening teams, after their day ends at 21:00). This
                     is the agent-team automation.
                     Also checks Admin every 2 hours, 08:00-20:00, so new
                     correspondence does not wait until the next morning.
                     NO API SPEND: claude and codex run through their CLIs on
                     the owner's subscriptions, ollama is local. It does consume
                     subscription rate limit, which RUNTIME_CAPS in agent_day.py
                     bounds per run. Supersedes -EnableHeartbeat/-EnableReflection:
                     the daily run produces and drains everything they did, so
                     do not enable those alongside it.

Running with no flags UNREGISTERS all SecondBrain tasks and reports on-demand
mode (this is the intended steady state).

Usage (from repo root, normal user - no admin needed):
  powershell -ExecutionPolicy Bypass -File .claude\scripts\setup_scheduler.ps1                 # on-demand (no tasks)
  powershell -ExecutionPolicy Bypass -File .claude\scripts\setup_scheduler.ps1 -EnableWiki      # opt into the free wiki job
  powershell -ExecutionPolicy Bypass -File .claude\scripts\setup_scheduler.ps1 -Status
  powershell -ExecutionPolicy Bypass -File .claude\scripts\setup_scheduler.ps1 -Remove
#>
param(
    [switch]$Remove, [switch]$Status,
    [switch]$EnableHeartbeat, [switch]$EnableReflection, [switch]$EnableWiki,
    [switch]$EnableDailyRun, [switch]$EnableSlackMonitor
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path "$PSScriptRoot\..\..").Path
$runner = Join-Path $repo ".claude\scripts\run_task.bat"
$hb = "SecondBrain-Heartbeat"
$rf = "SecondBrain-Reflection"
$wk = "SecondBrain-WikiDaily"
$dr = "SecondBrain-DailyRun"
$ac = "SecondBrain-AdminCheck"
$sm = "SecondBrain-SlackFollowup"

# One source of truth for every hour in this file. The /today schedule board
# and heartbeat.py read the same document, so their day changes in one place.
$scheduleFile = Join-Path $repo ".claude\agents\day-schedule.json"
if (-not (Test-Path $scheduleFile)) { throw "Day schedule not found: $scheduleFile" }
$automation = (Get-Content -Raw -LiteralPath $scheduleFile | ConvertFrom-Json).automation
if (-not $automation) { throw "$scheduleFile has no 'automation' section" }

# Hours between two "HH:mm" clock times on the same day, for RepetitionDuration.
function Get-WindowHours([string]$start, [string]$until) {
    $span = [datetime]::ParseExact($until, "HH:mm", $null) - [datetime]::ParseExact($start, "HH:mm", $null)
    if ($span.TotalHours -le 0) { throw "window $start-$until is not positive" }
    return $span.TotalHours
}

if ($Status) {
    $registered = @(Get-ScheduledTask -ErrorAction SilentlyContinue |
        Where-Object { $_.TaskName -like "SecondBrain-*" })
    $registered |
        Select-Object TaskName, State,
            @{n="LastRun";e={ (Get-ScheduledTaskInfo $_.TaskName).LastRunTime }},
            @{n="NextRun";e={ (Get-ScheduledTaskInfo $_.TaskName).NextRunTime }},
            @{n="LastResult";e={ (Get-ScheduledTaskInfo $_.TaskName).LastTaskResult }} |
        Format-Table -AutoSize
    if (-not $registered) {
        Write-Host "No SecondBrain tasks registered (on-demand mode - scan via the dashboard button)."
    }
    return
}

# Always unregister first so re-running is idempotent.
foreach ($name in @($hb, $rf, $wk, $dr, $ac, $sm, "SecondBrain-ChatBot")) {
    if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $name -Confirm:$false
        Write-Host "Removed $name"
    }
}
if ($Remove) { Write-Host "Done (removed)."; return }

if (-not (Test-Path $runner)) { throw "Runner not found: $runner" }
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive

if ($EnableHeartbeat) {
    # Across the lab day (the script also gates by the same hours). SPENDS TOKENS.
    $hbCfg = $automation.heartbeat
    $hbHours = Get-WindowHours $hbCfg.start $hbCfg.until
    $hbAction = New-ScheduledTaskAction -Execute $runner -Argument "heartbeat.py" `
        -WorkingDirectory (Join-Path $repo ".claude\scripts")
    $hbTrigger = New-ScheduledTaskTrigger -Daily -At $hbCfg.start
    # Graft intraday repetition on (Daily + -RepetitionInterval are different
    # parameter sets, so build the repetition separately and attach it).
    $hbTrigger.Repetition = (New-ScheduledTaskTrigger -Once -At $hbCfg.start `
        -RepetitionInterval (New-TimeSpan -Minutes $hbCfg.every_minutes) `
        -RepetitionDuration (New-TimeSpan -Hours $hbHours)).Repetition
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
        -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
        -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $hb -Action $hbAction -Trigger $hbTrigger `
        -Settings $settings -Principal $principal `
        -Description "Second Brain heartbeat (SPENDS TOKENS every $($hbCfg.every_minutes) min, $($hbCfg.start)-$($hbCfg.until) PT, 7 days)" | Out-Null
    Write-Host "Registered $hb (every $($hbCfg.every_minutes) min, $($hbCfg.start)-$($hbCfg.until)) - SPENDS TOKENS"
}

if ($EnableReflection) {
    # Before they wake, so yesterday's log is folded into MEMORY.md by the time
    # they plan the day. SPENDS TOKENS (one call).
    $rfAction = New-ScheduledTaskAction -Execute $runner -Argument "memory_reflect.py" `
        -WorkingDirectory (Join-Path $repo ".claude\scripts")
    $rfTrigger = New-ScheduledTaskTrigger -Daily -At $automation.reflection
    $rfSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $rf -Action $rfAction -Trigger $rfTrigger `
        -Settings $rfSettings -Principal $principal `
        -Description "Second Brain daily reflection (SPENDS TOKENS; promotes daily log to MEMORY.md)" | Out-Null
    Write-Host "Registered $rf (daily $($automation.reflection)) - SPENDS TOKENS"
}

if ($EnableDailyRun) {
    # Two triggers on ONE task: agent_day.py --window picks which teams belong
    # to each half, so changing a team's run_at in its manifest needs no
    # scheduler change. Logon-only, like the heartbeat: the CLIs authenticate
    # with their subscription login, and the run raises desktop toasts.
    # ONE action, TWO triggers. Task Scheduler cannot pass per-trigger
    # arguments, so `--window auto` reads the clock and runs the morning teams
    # at morning_run (05:00 - done before they wake at 06:00, so the brief is
    # on /today for their planning hour) and the evening teams at evening_run
    # (21:30 - after their day ends at 21:00, so the daily log is complete before
    # it is reflected on). A second action would instead run BOTH halves at
    # BOTH times, which is the obvious-looking wrong answer.
    $drAction = New-ScheduledTaskAction -Execute $runner `
        -Argument "agent_day.py --window auto" `
        -WorkingDirectory (Join-Path $repo ".claude\scripts")
    $drTriggers = @(
        (New-ScheduledTaskTrigger -Daily -At $automation.morning_run),
        (New-ScheduledTaskTrigger -Daily -At $automation.evening_run)
    )
    $drSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
        -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
        -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $dr -Action $drAction -Trigger $drTriggers `
        -Settings $drSettings -Principal $principal `
        -Description "Second Brain daily agent-team run (subscription CLIs + local ollama; no API spend)" | Out-Null

    # Admin needs a shorter feedback loop than research or security. Reuse the
    # same team entry point so the Gmail snapshot has one owner and every
    # resulting job still passes through the normal ledger and review gates.
    $acCfg = $automation.intraday_admin
    $acHours = Get-WindowHours $acCfg.start $acCfg.until
    $acAction = New-ScheduledTaskAction -Execute $runner `
        -Argument "agent_day.py --team admin" `
        -WorkingDirectory (Join-Path $repo ".claude\scripts")
    $acTrigger = New-ScheduledTaskTrigger -Daily -At $acCfg.start
    $acTrigger.Repetition = (New-ScheduledTaskTrigger -Once -At $acCfg.start `
        -RepetitionInterval (New-TimeSpan -Hours $acCfg.every_hours) `
        -RepetitionDuration (New-TimeSpan -Hours $acHours)).Repetition
    $acSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
        -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
        -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $ac -Action $acAction -Trigger $acTrigger `
        -Settings $acSettings -Principal $principal `
        -Description "Second Brain intraday Admin checks ($($acCfg.start)-$($acCfg.until) every $($acCfg.every_hours)h; advisor mode)" | Out-Null

    Write-Host "Registered $dr (daily $($automation.morning_run) + $($automation.evening_run)) - no API spend (subscription CLIs)"
    Write-Host "Registered $ac (every $($acCfg.every_hours)h, $($acCfg.start)-$($acCfg.until)) - advisor mode"
}

if ($EnableSlackMonitor) {
    # Lightweight, read-only Slack check. It does not call a model and never
    # writes to Slack. New one-to-one DMs are grouped into per-person bursts
    # and queued as one reply draft independently of read state; actionable
    # bursts also become idempotent
    # Prisma Today tasks plus desktop toasts. Agent analysis is queued for the
    # next normal Agent Day drain.
    $smCfg = $automation.slack_monitor
    $smHours = Get-WindowHours $smCfg.start $smCfg.until
    $smAction = New-ScheduledTaskAction -Execute $runner `
        -Argument "slack_followup.py" `
        -WorkingDirectory (Join-Path $repo ".claude\scripts")
    $smTrigger = New-ScheduledTaskTrigger -Daily -At $smCfg.start
    $smTrigger.Repetition = (New-ScheduledTaskTrigger -Once -At $smCfg.start `
        -RepetitionInterval (New-TimeSpan -Hours $smCfg.every_hours) `
        -RepetitionDuration (New-TimeSpan -Hours $smHours)).Repetition
    $smSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
        -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Minutes 15) `
        -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $sm -Action $smAction -Trigger $smTrigger `
        -Settings $smSettings -Principal $principal `
        -Description "Second Brain read-only Slack follow-up monitor (hourly; no model/API tokens)" | Out-Null
    Write-Host "Registered $sm (every $($smCfg.every_hours)h, $($smCfg.start)-$($smCfg.until)) - read-only, no model/API tokens"
}

if ($EnableWiki) {
    # After the evening run has ingested, while they sleep. Pure Python (no API cost).
    $wkAction = New-ScheduledTaskAction -Execute $runner -Argument "wiki_build.py daily" `
        -WorkingDirectory (Join-Path $repo ".claude\scripts")
    $wkTrigger = New-ScheduledTaskTrigger -Daily -At $automation.wiki
    $wkSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $wk -Action $wkAction -Trigger $wkTrigger `
        -Settings $wkSettings -Principal $principal `
        -Description "Second Brain wiki daily (no API cost)" | Out-Null
    Write-Host "Registered $wk (daily $($automation.wiki)) - no API cost"
}

if (-not ($EnableHeartbeat -or $EnableReflection -or $EnableWiki -or
          $EnableDailyRun -or $EnableSlackMonitor)) {
    Write-Host "On-demand mode: no scheduled tasks registered."
    Write-Host "Scan when you want via the dashboard 'Run scan now' button or /draft-replies."
    Write-Host "Re-enable automation with -EnableDailyRun / -EnableSlackMonitor / -EnableWiki."
}
