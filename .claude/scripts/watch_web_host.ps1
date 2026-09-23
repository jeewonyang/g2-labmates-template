<#
Short health watchdog for the independently scheduled G2 web host.

The watchdog requires a G2-specific response marker, not merely an open port.
It tolerates transient Next.js compilation stalls and requests recovery only
after consecutive failures.
#>
[CmdletBinding()]
param(
    [string]$HealthUrl = "http://127.0.0.1:3000/api/health",
    [ValidateRange(1, 20)][int]$FailureThreshold = 3,
    [string]$RecoverTaskName = "SecondBrain-WebRecover",
    [string]$StatePath,
    [string]$LogPath,
    [switch]$ProbeOnly,
    [switch]$NoRecover
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$stateDir = Join-Path $repo ".claude\data\state"
$logDir = Join-Path $repo ".claude\data\logs"
$pausePath = Join-Path $stateDir "WEB_HOST_PAUSED"
if (-not $StatePath) { $StatePath = Join-Path $stateDir "web-watchdog.json" }
if (-not $LogPath) { $LogPath = Join-Path $logDir "web-watchdog.log" }

New-Item -ItemType Directory -Force -Path $stateDir, $logDir | Out-Null

function Write-WatchdogLog {
    param([Parameter(Mandatory = $true)][string]$Message)
    $timestamp = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ssK")
    Add-Content -LiteralPath $LogPath -Encoding UTF8 -Value "[$timestamp] $Message"
}

function New-WatchdogState {
    return [pscustomobject]@{
        consecutiveFailures = 0
        lastSuccessAt = $null
        lastFailureAt = $null
        lastRecoveryAt = $null
        lastError = $null
    }
}

function Read-WatchdogState {
    if (-not (Test-Path -LiteralPath $StatePath)) { return (New-WatchdogState) }
    try {
        $saved = Get-Content -Raw -LiteralPath $StatePath | ConvertFrom-Json
        foreach ($name in @("consecutiveFailures", "lastSuccessAt", "lastFailureAt",
                            "lastRecoveryAt", "lastError")) {
            if ($saved.PSObject.Properties.Name -notcontains $name) {
                Add-Member -InputObject $saved -NotePropertyName $name -NotePropertyValue $null
            }
        }
        return $saved
    } catch {
        Write-WatchdogLog "Ignored unreadable watchdog state: $($_.Exception.Message)"
        return (New-WatchdogState)
    }
}

function Save-WatchdogState {
    param([Parameter(Mandatory = $true)]$State)
    $State | ConvertTo-Json | Set-Content -LiteralPath $StatePath -Encoding UTF8
}

function Test-G2Health {
    try {
        $response = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 5
        if ($response.StatusCode -ne 200) {
            return [pscustomobject]@{ Healthy = $false; Error = "HTTP $($response.StatusCode)" }
        }
        if ($response.Headers["X-G2-Service"] -ne "second-brain") {
            return [pscustomobject]@{ Healthy = $false; Error = "G2 service marker missing" }
        }
        $body = $response.Content | ConvertFrom-Json
        if ($body.ok -ne $true -or $body.service -ne "second-brain") {
            return [pscustomobject]@{ Healthy = $false; Error = "G2 health body invalid" }
        }
        return [pscustomobject]@{ Healthy = $true; Error = $null }
    } catch {
        return [pscustomobject]@{ Healthy = $false; Error = $_.Exception.Message }
    }
}

$probe = Test-G2Health
if ($ProbeOnly) {
    if ($probe.Healthy) {
        Write-Output "healthy"
        exit 0
    }
    Write-Output "unhealthy: $($probe.Error)"
    exit 1
}

$state = Read-WatchdogState
if (Test-Path -LiteralPath $pausePath) {
    if ([int]$state.consecutiveFailures -ne 0) {
        $state.consecutiveFailures = 0
        $state.lastError = $null
        Save-WatchdogState $state
    }
    exit 0
}

if ($probe.Healthy) {
    if ([int]$state.consecutiveFailures -gt 0) {
        Write-WatchdogLog "G2 recovered after $($state.consecutiveFailures) failed probe(s)."
    }
    $state.consecutiveFailures = 0
    $state.lastSuccessAt = (Get-Date).ToString("o")
    $state.lastError = $null
    Save-WatchdogState $state
    exit 0
}

$state.consecutiveFailures = [int]$state.consecutiveFailures + 1
$state.lastFailureAt = (Get-Date).ToString("o")
$state.lastError = $probe.Error
if ([int]$state.consecutiveFailures -eq 1) {
    Write-WatchdogLog "Health probe failed: $($probe.Error)"
}

if ([int]$state.consecutiveFailures -ge $FailureThreshold) {
    if ($NoRecover) {
        Write-WatchdogLog "Recovery suppressed after $($state.consecutiveFailures) failed probes."
    } else {
        try {
            Start-ScheduledTask -TaskName $RecoverTaskName
            $state.lastRecoveryAt = (Get-Date).ToString("o")
            Write-WatchdogLog "Requested $RecoverTaskName after $($state.consecutiveFailures) failed probes."
        } catch {
            Write-WatchdogLog "Could not start $RecoverTaskName`: $($_.Exception.Message)"
        }
    }
    $state.consecutiveFailures = 0
}

Save-WatchdogState $state
exit 0
