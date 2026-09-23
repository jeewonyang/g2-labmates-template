<#
Restart the scheduled G2 host without depending on the G2 HTTP process.

If Task Scheduler leaves an orphan listener, it is terminated only after its
command line is proven to belong to this repo's Node/Next process. A process on
port 3000 that cannot be attributed to G2 is never touched.
#>
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "Medium")]
param(
    [string]$HostTaskName = "SecondBrain-WebHost",
    [ValidateRange(1, 65535)][int]$Port = 3000,
    [ValidateRange(5, 300)][int]$ReadyTimeoutSeconds = 120,
    [string]$HealthUrl = "http://127.0.0.1:3000/api/health",
    [string]$LogPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$logDir = Join-Path $repo ".claude\data\logs"
if (-not $LogPath) { $LogPath = Join-Path $logDir "web-recovery.log" }
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Write-RecoveryLog {
    param([Parameter(Mandatory = $true)][string]$Message)
    $timestamp = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ssK")
    Add-Content -LiteralPath $LogPath -Encoding UTF8 -Value "[$timestamp] $Message"
}

function Get-PortListeners {
    return @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique)
}

function Test-G2Health {
    try {
        $response = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 3
        return ($response.StatusCode -eq 200 -and
                $response.Headers["X-G2-Service"] -eq "second-brain")
    } catch {
        return $false
    }
}

trap {
    Write-RecoveryLog "Recovery failed: $($_.Exception.Message)"
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}

$task = Get-ScheduledTask -TaskName $HostTaskName -ErrorAction SilentlyContinue
if (-not $task) {
    throw "Scheduled task $HostTaskName is not registered. Run setup_web_host.ps1 first."
}

if (-not $PSCmdlet.ShouldProcess($HostTaskName, "restart the G2 web host")) {
    return
}

Write-RecoveryLog "Recovery requested."
if ($task.State -eq "Running") {
    Stop-ScheduledTask -TaskName $HostTaskName
    Write-RecoveryLog "Stopped $HostTaskName."
}

$deadline = (Get-Date).AddSeconds(10)
do {
    $listeners = @(Get-PortListeners)
    if ($listeners.Count -eq 0) { break }
    Start-Sleep -Milliseconds 500
} while ((Get-Date) -lt $deadline)

$listeners = @(Get-PortListeners)
if ($listeners.Count -gt 0) {
    $owned = @()
    foreach ($ownerPid in $listeners) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId = $ownerPid" -ErrorAction SilentlyContinue
        $commandLine = if ($process) { [string]$process.CommandLine } else { "" }
        $isNode = $process -and ([string]$process.Name -ieq "node.exe")
        $isThisRepo = $commandLine.IndexOf($repo, [StringComparison]::OrdinalIgnoreCase) -ge 0
        if (-not ($isNode -and $isThisRepo)) {
            Write-RecoveryLog "Refused to stop unowned PID $ownerPid on port $Port."
            throw "Port $Port is held by a process that cannot be proven to belong to G2 (PID $ownerPid)."
        }
        $owned += [int]$ownerPid
    }
    foreach ($ownerPid in $owned) {
        Stop-Process -Id $ownerPid -Force
        Write-RecoveryLog "Stopped orphaned G2 listener PID $ownerPid."
    }
}

$deadline = (Get-Date).AddSeconds(10)
while (@(Get-PortListeners).Count -gt 0 -and (Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 500
}
if (@(Get-PortListeners).Count -gt 0) {
    throw "Port $Port did not become free; the host was not restarted."
}

Start-ScheduledTask -TaskName $HostTaskName
Write-RecoveryLog "Started $HostTaskName."

$deadline = (Get-Date).AddSeconds($ReadyTimeoutSeconds)
do {
    if (Test-G2Health) {
        Write-RecoveryLog "G2 health check passed."
        Write-Output "G2 web host is healthy."
        exit 0
    }
    Start-Sleep -Seconds 1
} while ((Get-Date) -lt $deadline)

Write-RecoveryLog "G2 did not become healthy within $ReadyTimeoutSeconds seconds."
throw "G2 was restarted but did not become healthy within $ReadyTimeoutSeconds seconds."
