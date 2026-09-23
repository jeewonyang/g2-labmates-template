<#
Install and manage G2's independent Windows web-host recovery tasks.

This is deliberately separate from setup_scheduler.ps1. Agent automation is
on-demand and removable; web uptime is infrastructure and must not disappear
when the owner changes heartbeat or team schedules.

It also owns SecondBrain-Update (added 2026-09-16), which keeps the *deployment*
current for the same reason: they edit G2 from a laptop, a work computer over
Tailscale, and cloud Claude sessions, but one machine serves the dashboard and
runs the agents. Every 30 minutes it fast-forwards this checkout from its own
upstream and applies what a pull does not - dependencies, the database schema,
and re-registering the scheduled tasks, which store a snapshot of
day-schedule.json rather than reading it. It never touches a dirty tree and
never pulls a branch they have not merged, so it carries out their decisions rather
than making any. -NoAutoUpdate leaves it out.

Usage (normal user, from the repo root):
  powershell -ExecutionPolicy Bypass -File .claude\scripts\setup_web_host.ps1
  powershell -ExecutionPolicy Bypass -File .claude\scripts\setup_web_host.ps1 -Status
  powershell -ExecutionPolicy Bypass -File .claude\scripts\setup_web_host.ps1 -Recover
  powershell -ExecutionPolicy Bypass -File .claude\scripts\setup_web_host.ps1 -Remove
#>
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "Medium")]
param(
    [switch]$Status,
    [switch]$Recover,
    [switch]$Remove,
    [switch]$NoAutoUpdate
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$powershell = Join-Path $PSHOME "powershell.exe"
$hostScript = Join-Path $PSScriptRoot "run_web_host.ps1"
$watchScript = Join-Path $PSScriptRoot "watch_web_host.ps1"
$recoverScript = Join-Path $PSScriptRoot "recover_web_host.ps1"
$updateScript = Join-Path $PSScriptRoot "apply_update.ps1"
$hostTask = "SecondBrain-WebHost"
$watchTask = "SecondBrain-WebWatchdog"
$recoverTask = "SecondBrain-WebRecover"
$updateTask = "SecondBrain-Update"
$taskNames = @($hostTask, $watchTask, $recoverTask, $updateTask)

function Get-TaskOrNull {
    param([Parameter(Mandatory = $true)][string]$Name)
    return Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
}

function Test-InstalledHealth {
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:3000/api/health" `
            -UseBasicParsing -TimeoutSec 3
        return ($response.StatusCode -eq 200 -and
                $response.Headers["X-G2-Service"] -eq "second-brain")
    } catch {
        return $false
    }
}

if ($Status) {
    $rows = @()
    foreach ($name in $taskNames) {
        $task = Get-TaskOrNull $name
        if (-not $task) {
            $rows += [pscustomobject]@{
                TaskName = $name; State = "not registered"; LastRun = $null
                NextRun = $null; LastResult = $null
            }
            continue
        }
        $info = Get-ScheduledTaskInfo -TaskName $name
        $rows += [pscustomobject]@{
            TaskName = $name; State = $task.State; LastRun = $info.LastRunTime
            NextRun = $info.NextRunTime; LastResult = $info.LastTaskResult
        }
    }
    $rows | Format-Table -AutoSize
    if (Test-InstalledHealth) {
        Write-Host "G2 health: healthy" -ForegroundColor Green
    } else {
        Write-Host "G2 health: unreachable or unhealthy" -ForegroundColor Yellow
    }
    return
}

if ($Recover) {
    if (-not (Get-TaskOrNull $recoverTask)) {
        throw "$recoverTask is not registered. Run this script without flags first."
    }
    Start-ScheduledTask -TaskName $recoverTask
    Write-Host "Recovery requested. Check status in a few seconds with -Status."
    return
}

if ($Remove) {
    foreach ($name in $taskNames) {
        $task = Get-TaskOrNull $name
        if (-not $task) { continue }
        if ($PSCmdlet.ShouldProcess($name, "stop and unregister scheduled task")) {
            if ($task.State -eq "Running") {
                Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
            }
            Unregister-ScheduledTask -TaskName $name -Confirm:$false
            Write-Host "Removed $name"
        }
    }
    return
}

foreach ($script in @($hostScript, $watchScript, $recoverScript, $updateScript)) {
    if (-not (Test-Path -LiteralPath $script)) { throw "Required script not found: $script" }
}

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive `
    -RunLevel Limited

function New-PowerShellAction {
    param([Parameter(Mandatory = $true)][string]$Script)
    $arguments = "-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$Script`""
    return New-ScheduledTaskAction -Execute $powershell -Argument $arguments `
        -WorkingDirectory $repo
}

$hostAction = New-PowerShellAction $hostScript
$hostTrigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$hostSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -DontStopOnIdleEnd `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -MultipleInstances IgnoreNew `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)

$recoverAction = New-PowerShellAction $recoverScript
$recoverSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 3) -MultipleInstances IgnoreNew

$watchAction = New-PowerShellAction $watchScript
$watchAtLogon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$watchDaily = New-ScheduledTaskTrigger -Daily -At 12am
$watchDaily.Repetition = (New-ScheduledTaskTrigger -Once -At 12am `
    -RepetitionInterval (New-TimeSpan -Minutes 2) `
    -RepetitionDuration (New-TimeSpan -Days 1)).Repetition
$watchSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew

if ($PSCmdlet.ShouldProcess($hostTask, "register supervised G2 web host")) {
    Register-ScheduledTask -TaskName $hostTask -Action $hostAction -Trigger $hostTrigger `
        -Settings $hostSettings -Principal $principal -Force `
        -Description "G2 Next.js host; starts at logon and restarts after process failure." | Out-Null
}
if ($PSCmdlet.ShouldProcess($recoverTask, "register on-demand G2 recovery task")) {
    Register-ScheduledTask -TaskName $recoverTask -Action $recoverAction `
        -Settings $recoverSettings -Principal $principal -Force `
        -Description "Independent on-demand restart for the G2 web host." | Out-Null
}
# Deployment currency. Every 30 minutes, all day: a fetch on an unchanged repo
# costs nothing, and the point is that a merge they make from anywhere shows up
# here without their having to remember to come and pull it. -Quiet keeps a no-op
# run silent in the log.
$updateAction = New-ScheduledTaskAction -Execute $powershell `
    -Argument ("-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$updateScript`" -Quiet") `
    -WorkingDirectory $repo
$updateAtLogon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$updateDaily = New-ScheduledTaskTrigger -Daily -At 12am
$updateDaily.Repetition = (New-ScheduledTaskTrigger -Once -At 12am `
    -RepetitionInterval (New-TimeSpan -Minutes 30) `
    -RepetitionDuration (New-TimeSpan -Days 1)).Repetition
$updateSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 20) -MultipleInstances IgnoreNew

if ($PSCmdlet.ShouldProcess($watchTask, "register G2 health watchdog")) {
    Register-ScheduledTask -TaskName $watchTask -Action $watchAction `
        -Trigger @($watchAtLogon, $watchDaily) -Settings $watchSettings `
        -Principal $principal -Force `
        -Description "Checks G2 every two minutes and requests recovery after three failures." | Out-Null
}

if ($NoAutoUpdate) {
    # Explicitly opted out: remove it rather than leaving a stale one running.
    if (Get-TaskOrNull $updateTask) {
        Unregister-ScheduledTask -TaskName $updateTask -Confirm:$false
        Write-Host "Removed $updateTask (-NoAutoUpdate)."
    }
} elseif ($PSCmdlet.ShouldProcess($updateTask, "register G2 auto-update")) {
    Register-ScheduledTask -TaskName $updateTask -Action $updateAction `
        -Trigger @($updateAtLogon, $updateDaily) -Settings $updateSettings `
        -Principal $principal -Force `
        -Description "Fast-forwards this checkout from its upstream every 30 minutes and re-applies dependencies, schema, and scheduled-task registration. Never touches uncommitted work." | Out-Null
}

if (-not $WhatIfPreference) {
    Start-ScheduledTask -TaskName $hostTask
    Start-ScheduledTask -TaskName $watchTask
    Write-Host "Registered and started $hostTask, $watchTask, and $recoverTask."
    if (-not $NoAutoUpdate) {
        Write-Host "Registered $updateTask (every 30 min; fast-forward only, skips a dirty tree)."
    }
    Write-Host "Use -Status to inspect health or -Recover to request a clean restart."
    Write-Host "Deployment status: .claude\scripts\apply_update.ps1 -Status"
}
