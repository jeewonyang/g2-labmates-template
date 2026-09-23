<#
Long-running Task Scheduler entry point for the G2 Next.js development server.

Unlike start-second-brain.bat, this host does not open a browser or depend on a
console window staying open. Task Scheduler owns the process tree and restarts
this wrapper when npm exits unexpectedly.
#>
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$dataDir = Join-Path $repo ".claude\data"
$logDir = Join-Path $dataDir "logs"
$stateDir = Join-Path $dataDir "state"
$logPath = Join-Path $logDir "web-host.log"
$statePath = Join-Path $stateDir "web-host.json"
$pausePath = Join-Path $stateDir "WEB_HOST_PAUSED"
$nodeRoot = Join-Path $env:LOCALAPPDATA "Programs\nodejs"
$npm = Join-Path $nodeRoot "npm.cmd"

New-Item -ItemType Directory -Force -Path $logDir, $stateDir | Out-Null

function Write-WebHostLog {
    param([Parameter(Mandatory = $true)][string]$Message)
    $timestamp = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ssK")
    Add-Content -LiteralPath $logPath -Encoding UTF8 -Value "[$timestamp] $Message"
}

if (Test-Path -LiteralPath $pausePath) {
    Write-WebHostLog "Host start skipped because WEB_HOST_PAUSED exists."
    exit 0
}

if (-not (Test-Path -LiteralPath $npm)) {
    Write-WebHostLog "npm was not found at the fixed host path: $npm"
    exit 2
}

$metadata = [ordered]@{
    wrapperPid = $PID
    repo = $repo
    startedAt = (Get-Date).ToString("o")
    stoppedAt = $null
    exitCode = $null
}
$metadata | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8

$env:PATH = "$nodeRoot;$env:PATH"
$PSDefaultParameterValues["Out-File:Encoding"] = "utf8"
Write-WebHostLog "Starting G2 web host (wrapper PID $PID)."

$exitCode = 1
Push-Location $repo
try {
    & $npm run dev *>> $logPath
    if ($null -eq $LASTEXITCODE) {
        $exitCode = 1
    } else {
        $exitCode = [int]$LASTEXITCODE
    }
} catch {
    Write-WebHostLog "Host wrapper failed: $($_.Exception.Message)"
    $exitCode = 1
} finally {
    Pop-Location
    $metadata.stoppedAt = (Get-Date).ToString("o")
    $metadata.exitCode = $exitCode
    $metadata | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
    Write-WebHostLog "G2 web host exited with code $exitCode."
}

exit $exitCode
