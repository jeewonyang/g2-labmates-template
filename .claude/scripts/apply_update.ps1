<#
Bring this machine's G2 checkout up to date, and apply the side effects a pull
alone does not.

Why this exists (2026-09-16). the owner edits G2 from several places - the
desktop, a laptop, a work computer over Tailscale, a Claude session in the
cloud - but only one machine serves the dashboard and runs the scheduled
agents. A change is not "done" when it is pushed; it is done when that machine
is running it. Four things have to happen there, and three of them a `git pull`
does not do:

  1. the new commits land in the working tree                (git)
  2. dependencies and the database schema match the code     (npm / prisma)
  3. Windows Task Scheduler re-reads the day schedule        (setup_scheduler)
  4. the running Next.js host is actually on the new code    (web-host recovery)

(3) is the one that surprises. Task Scheduler stores a *snapshot* of each
trigger when the task is registered - editing day-schedule.json changes what
setup_scheduler.ps1 *would* register, and nothing else. Until the tasks are
re-registered, the agents keep firing at the old times. This script re-registers
them whenever the schedule or the scheduler script changed, preserving exactly
the set of tasks they had opted into (derived from what is registered, never
guessed), so the day schedule becomes the single source of truth in practice and
not just on paper.

Safety, in the order that matters:

  - **Fast-forward when it can; a real merge when this machine has commits of
    its own; never rebase, reset, stash, or force.** A merge that conflicts is
    aborted, which puts the tree back exactly as it was, and reported.
  - **Agent writes under VAULT/Memory are committed here, not skipped over.**
    The admin, vault, and reflection agents append to tracked files all day
    (calendar-writes.md, daily logs, MEMORY.md, drafts) - that is what the
    repo versions that folder for. Refusing to update while any of them is
    dirty (the first design, 2026-09-16) blocked the very next run. They are
    committed as "Vault: agent writes on <machine> before update" so the record
    travels with the repo, and the merge carries them.
  - **Uncommitted CODE stops the update** with a report, not a stash and not a
    discard. Anything outside VAULT/Memory is work they are doing, and nothing
    here overwrites a file they wrote.
  - **An untracked vault file that upstream now tracks is renamed aside**
    (`<name>.local-<stamp><ext>`), never deleted, and the merge is retried once.
    That is the "daily log written on both machines" case, hit on 2026-09-17.
  - **Upstream only.** It updates the checked-out branch from its own upstream,
    so unmerged work in a feature branch cannot deploy itself. Merging is still
    their decision; this only carries out the decision they already made.
  - **No arguments reach a shell.** The branch name, when given, is validated
    against a strict pattern before it is used.

Usage (normal user, from the repo root):
  powershell -ExecutionPolicy Bypass -File .claude\scripts\apply_update.ps1
  powershell -ExecutionPolicy Bypass -File .claude\scripts\apply_update.ps1 -Status
  powershell -ExecutionPolicy Bypass -File .claude\scripts\apply_update.ps1 -Branch main
  update-g2.bat                     # same thing, double-clickable / over SSH

`SecondBrain-Update` (registered by setup_web_host.ps1) runs it every 30 minutes
with -Quiet, which prints nothing on a no-op run. Log: .claude/data/logs/update.log
#>
[CmdletBinding()]
param(
    [switch]$Status,
    [string]$Branch,
    [switch]$Quiet
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$scheduleFile = Join-Path $repo ".claude\agents\day-schedule.json"
$schedulerScript = Join-Path $PSScriptRoot "setup_scheduler.ps1"
$webHostScript = Join-Path $PSScriptRoot "setup_web_host.ps1"
$maxCycleScript = Join-Path $PSScriptRoot "setup_max_cycle.ps1"
$logDir = Join-Path $repo ".claude\data\logs"
$logPath = Join-Path $logDir "update.log"

# A git ref this script will accept. Deliberately narrow: this value becomes a
# git argument, and "whatever the caller typed" is how a tool like this grows a
# command-injection hole.
$SAFE_REF = '^[A-Za-z0-9][A-Za-z0-9._\-\/]{0,100}$'

function Write-Log {
    param([string]$Message, [switch]$Always)
    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    if (-not (Test-Path -LiteralPath $logDir)) {
        New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    }
    Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
    if ($Always -or -not $Quiet) { Write-Host $Message }
}

function Invoke-Git {
    <#  Runs git in the repo and returns @{ Ok; Out }. Never throws on a
        non-zero exit: a failed fetch is a normal outcome on a laptop that is
        off the network, and this runs unattended every 30 minutes. #>
    param([Parameter(Mandatory = $true)][string[]]$GitArgs)
    # Local to this function: under the script's "Stop" preference, Windows
    # PowerShell 5.1 turns ANY stderr line a native command writes into a
    # terminating error the moment it is redirected with 2>&1. git writes
    # hints there on ordinary paths - "Diverging branches can't be
    # fast-forwarded" is what the ff-only probe says whenever this machine
    # has vault commits of its own, which is every run after the first - and
    # that killed the script one line before the real merge (2026-09-18).
    $ErrorActionPreference = "Continue"
    $out = & git -C $repo @GitArgs 2>&1 | ForEach-Object {
        if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.ToString() } else { $_ }
    }
    return @{ Ok = ($LASTEXITCODE -eq 0); Out = ($out | Out-String).Trim() }
}

function Get-CurrentBranch {
    $r = Invoke-Git @("rev-parse", "--abbrev-ref", "HEAD")
    if (-not $r.Ok -or $r.Out -eq "HEAD") { return $null }
    return $r.Out
}

function Get-TargetRef {
    <#  The branch to update from, most specific first: an explicit -Branch, the
        checked-out branch's own upstream, else origin/<branch>. Returns
        @{ Remote; Ref } or $null when the checkout is detached. #>
    if ($Branch) {
        if ($Branch -notmatch $SAFE_REF) { throw "Refusing suspicious branch name: $Branch" }
        return @{ Remote = "origin"; Ref = "origin/$Branch"; Branch = $Branch }
    }
    $current = Get-CurrentBranch
    if (-not $current) { return $null }
    $upstream = Invoke-Git @("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if ($upstream.Ok -and $upstream.Out) {
        $parts = $upstream.Out.Split("/", 2)
        return @{ Remote = $parts[0]; Ref = $upstream.Out; Branch = $parts[1] }
    }
    return @{ Remote = "origin"; Ref = "origin/$current"; Branch = $current }
}

function Test-CleanTree {
    # Ignored files (.claude/data, prisma/dev.db, node_modules) are not tracked
    # and must not count as local work: they are always "dirty" by design.
    $r = Invoke-Git @("status", "--porcelain", "--untracked-files=no")
    return ($r.Ok -and -not $r.Out)
}

function Get-RegisteredAgentFlags {
    <#  The scheduler flags this machine currently has, read from the tasks that
        exist rather than remembered in a file. Re-registering has to reproduce
        their opt-in set exactly - turning automation ON that they had left off
        would be this script overriding a decision instead of carrying one out. #>
    $map = [ordered]@{
        "SecondBrain-DailyRun"      = "-EnableDailyRun"
        "SecondBrain-SlackFollowup" = "-EnableSlackMonitor"
        "SecondBrain-Heartbeat"     = "-EnableHeartbeat"
        "SecondBrain-Reflection"    = "-EnableReflection"
        "SecondBrain-WikiDaily"     = "-EnableWiki"
    }
    $flags = @()
    foreach ($name in $map.Keys) {
        if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
            $flags += $map[$name]
        }
    }
    # AdminCheck rides on -EnableDailyRun and has no flag of its own.
    # Returned bare, and wrapped in @() by callers. Wrapping an EMPTY array in
    # the usual unary-comma idiom yields an array holding an empty array: Count
    # reads 1, so a machine with no agent tasks would look like it had one, and
    # piping it hands the next stage an object with no properties. Found by
    # running this against a scratch checkout, not by reading it.
    return $flags
}

function Get-ExpectedStarts {
    <#  What each task's triggers SHOULD start at, per day-schedule.json. Used
        only to report drift - re-registering is what fixes it. #>
    if (-not (Test-Path -LiteralPath $scheduleFile)) { return @{} }
    $a = (Get-Content -Raw -LiteralPath $scheduleFile | ConvertFrom-Json).automation
    return @{
        "SecondBrain-DailyRun"      = @($a.morning_run, $a.evening_run)
        "SecondBrain-AdminCheck"    = @($a.intraday_admin.start)
        "SecondBrain-Heartbeat"     = @($a.heartbeat.start)
        "SecondBrain-SlackFollowup" = @($a.slack_monitor.start)
        "SecondBrain-Reflection"    = @($a.reflection)
        "SecondBrain-WikiDaily"     = @($a.wiki)
    }
}

function Get-ScheduleDrift {
    <#  Registered trigger times vs the day schedule, for the tasks that exist.
        Reports; never changes anything. #>
    $expected = Get-ExpectedStarts
    $rows = @()
    foreach ($name in $expected.Keys) {
        $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        if (-not $task) { continue }
        $actual = @($task.Triggers |
            ForEach-Object { $_.StartBoundary } |
            Where-Object { $_ } |
            ForEach-Object { ([datetime]$_).ToString("HH:mm") } |
            Sort-Object)
        $want = @($expected[$name] | Sort-Object)
        $rows += [pscustomobject]@{
            TaskName   = $name
            Registered = ($actual -join ", ")
            Expected   = ($want -join ", ")
            InSync     = (($actual -join ",") -eq ($want -join ","))
        }
    }
    return $rows
}

function Show-ExternalAutomation {
    # Automation this script cannot touch, named so it is not forgotten.
    if (-not (Test-Path -LiteralPath $scheduleFile)) { return }
    $automation = (Get-Content -Raw -LiteralPath $scheduleFile | ConvertFrom-Json).automation
    if (-not ($automation.PSObject.Properties.Name -contains "external")) { return }
    foreach ($item in $automation.external) {
        $verb = if ($item.action -eq "retire") { "retire it" } else { "retime it to $($item.at)" }
        Write-Host "  external: $($item.id) in $($item.where) - $verb (by hand; not registerable from here)"
    }
}

function Invoke-InRepo {
    <#  One step of the update. A step that fails is reported and the rest still
        run: the scheduler re-registration is the most important thing this
        script does, and letting a missing npm abort the run would leave the
        agents firing at yesterday's times with nobody watching. #>
    param([Parameter(Mandatory = $true)][string]$Exe,
          [Parameter(Mandatory = $true)][string[]]$Arguments,
          [Parameter(Mandatory = $true)][string]$What)
    Write-Log "  $What"
    # Same stderr rule as Invoke-Git: npm and prisma print warnings there on
    # successful runs, and under "Stop" the first one would land in the catch
    # below as "could not run" with the step half done.
    $ErrorActionPreference = "Continue"
    try {
        & $Exe @Arguments 2>&1 | ForEach-Object { Write-Log "    $_" }
    } catch {
        Write-Log "  ! $What could not run: $($_.Exception.Message)" -Always
        return $false
    }
    if ($LASTEXITCODE -ne 0) { Write-Log "  ! $What failed (exit $LASTEXITCODE)" -Always }
    return ($LASTEXITCODE -eq 0)
}

# ---------------------------------------------------------------- status ----

if ($Status) {
    $branchNow = Get-CurrentBranch
    $head = (Invoke-Git @("rev-parse", "--short", "HEAD")).Out
    $subject = (Invoke-Git @("log", "-1", "--pretty=%s")).Out
    Write-Host "repo     $repo"
    Write-Host "branch   $(if ($branchNow) { $branchNow } else { '(detached)' })  @ $head  $subject"
    Write-Host "tree     $(if (Test-CleanTree) { 'clean' } else { 'HAS UNCOMMITTED CHANGES - updates will be skipped' })"

    $target = Get-TargetRef
    if ($target) {
        Invoke-Git @("fetch", "--quiet", $target.Remote, $target.Branch) | Out-Null
        $counts = Invoke-Git @("rev-list", "--left-right", "--count", "HEAD...$($target.Ref)")
        if ($counts.Ok -and $counts.Out) {
            $pair = $counts.Out -split "\s+"
            Write-Host "vs $($target.Ref): $($pair[0]) ahead, $($pair[1]) behind"
        }
    }

    $drift = @(Get-ScheduleDrift)
    if ($drift.Count -eq 0) {
        Write-Host "agent tasks: none registered (on-demand mode)"
    } else {
        # Explicit lines rather than Format-Table: this is read over SSH and
        # tailed from a log, where a formatter's deferred rendering is a good
        # way to print nothing at all.
        foreach ($row in $drift) {
            Write-Host ("  {0,-27} fires {1,-12} should be {2,-12} {3}" -f `
                $row.TaskName, $row.Registered, $row.Expected,
                $(if ($row.InSync) { "ok" } else { "DRIFTED" }))
        }
        if ($drift | Where-Object { -not $_.InSync }) {
            Write-Host "Scheduled tasks are OUT OF DATE with day-schedule.json." -ForegroundColor Yellow
            Write-Host "Run this script without -Status, or re-run setup_scheduler.ps1 with your flags."
        }
    }
    Show-ExternalAutomation
    return
}

# ---------------------------------------------------------------- update ----

$target = Get-TargetRef
if (-not $target) {
    Write-Log "detached HEAD - refusing to update automatically." -Always
    exit 1
}

$fetch = Invoke-Git @("fetch", "--quiet", $target.Remote, $target.Branch)
if (-not $fetch.Ok) {
    # Offline is the common case for a laptop, and not worth a red line.
    Write-Log "fetch failed (offline?): $($fetch.Out)"
    exit 0
}

$before = (Invoke-Git @("rev-parse", "HEAD")).Out
$after = (Invoke-Git @("rev-parse", $target.Ref)).Out
if (-not $after) {
    Write-Log "no such ref: $($target.Ref)" -Always
    exit 1
}

# "Behind" rather than "different": this machine may carry commits of its own
# (its vault writes), which make HEAD differ without there being anything new.
$behindOut = (Invoke-Git @("rev-list", "--count", "HEAD..$($target.Ref)")).Out
$behind = 0
[void][int]::TryParse($behindOut, [ref]$behind)
if ($behind -eq 0) {
    Write-Log "already up to date with $($target.Ref)"
    # Even with no new commits, the registered tasks can be stale - they may have
    # edited day-schedule.json here and never re-registered.
    $drift = @(Get-ScheduleDrift) | Where-Object { -not $_.InSync }
    if ($drift) {
        Write-Log "scheduled tasks drifted from day-schedule.json; re-registering" -Always
        $flags = @(Get-RegisteredAgentFlags)
        if ($flags.Count -gt 0) {
            Invoke-InRepo "powershell.exe" (@(
                "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                "-File", $schedulerScript) + $flags) "re-registering agent schedules ($($flags -join ' '))" | Out-Null
        }
    }
    exit 0
}

# ---- local changes -------------------------------------------------------
# porcelain lines are "XY path" (or "XY old -> new" for a rename).
$statusOut = (Invoke-Git @("status", "--porcelain", "--untracked-files=no")).Out
$dirtyLines = @($statusOut -split "`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ })
$dirtyPaths = @($dirtyLines | ForEach-Object {
    $p = $_ -replace '^[ MADRCU?!]{1,2}\s+', ''
    if ($p -match ' -> ') { $p = ($p -split ' -> ')[-1] }
    $p.Trim('"')
})
$vaultDirty = @($dirtyPaths | Where-Object { $_ -like "VAULT/Memory/*" })
$codeDirty  = @($dirtyPaths | Where-Object { $_ -notlike "VAULT/Memory/*" })

if ($codeDirty.Count -gt 0) {
    Write-Log "uncommitted changes outside VAULT/Memory - NOT updating. Nothing was touched:" -Always
    foreach ($line in $dirtyLines) { Write-Log "    $line" -Always }
    exit 0
}
if ($vaultDirty.Count -gt 0) {
    # Agent output. Versioned on purpose; commit it so the update can proceed
    # and the record of this machine's day travels with the repo.
    Invoke-Git @("add", "-u", "--", "VAULT/Memory") | Out-Null
    $host_ = [System.Environment]::MachineName
    $commit = Invoke-Git @("commit", "--quiet", "-m", "Vault: agent writes on $host_ before update")
    if (-not $commit.Ok) {
        Write-Log "could not commit vault writes - NOT updating: $($commit.Out)" -Always
        exit 1
    }
    Write-Log "  committed $($vaultDirty.Count) vault file(s) written here: $($vaultDirty -join ', ')" -Always
}

# ---- bring upstream in -----------------------------------------------------
function Resolve-UntrackedCollision {
    <#  git refuses to overwrite an untracked file that upstream now tracks.
        For a file under VAULT/ (a log both machines wrote) the local copy is
        renamed aside - kept, never deleted - and the caller retries. Anything
        else is left alone and reported. Returns $true if something was moved. #>
    param([string]$GitOutput)
    if ($GitOutput -notmatch 'untracked working tree files would be overwritten') { return $false }
    $moved = $false
    $inList = $false
    foreach ($line in ($GitOutput -split "`n")) {
        if ($line -match 'would be overwritten by') { $inList = $true; continue }
        if ($line -match '^(Please|Aborting|error|fatal)') { $inList = $false; continue }
        if (-not $inList) { continue }
        $rel = $line.Trim()
        if (-not $rel -or $rel -notlike "VAULT/*") { continue }
        $full = Join-Path $repo ($rel -replace '/', '\')
        if (-not (Test-Path -LiteralPath $full)) { continue }
        $stamp = Get-Date -Format "yyyyMMdd-HHmm"
        $ext = [System.IO.Path]::GetExtension($full)
        $base = $full.Substring(0, $full.Length - $ext.Length)
        $aside = "$base.local-$stamp$ext"
        Move-Item -LiteralPath $full -Destination $aside
        Write-Log "  kept this machine's copy of $rel as $([System.IO.Path]::GetFileName($aside)) (upstream now tracks that file)" -Always
        $moved = $true
    }
    return $moved
}

function Invoke-Upstream {
    # Fast-forward if possible. Otherwise this machine has commits of its own
    # (the vault writes above, or work they committed here): merge upstream over
    # them. A conflict is aborted - the tree goes back to exactly what it was.
    $ff = Invoke-Git @("merge", "--ff-only", $target.Ref)
    if ($ff.Ok) { return $ff }
    if ($ff.Out -match 'untracked working tree files would be overwritten') { return $ff }
    $m = Invoke-Git @("merge", "--no-edit", "-m", "Merge $($target.Ref) into this machine's $($target.Branch) (apply_update)", $target.Ref)
    if (-not $m.Ok -and $m.Out -notmatch 'untracked working tree files would be overwritten') {
        Invoke-Git @("merge", "--abort") | Out-Null
    }
    return $m
}

$result = Invoke-Upstream
if (-not $result.Ok -and (Resolve-UntrackedCollision $result.Out)) {
    $result = Invoke-Upstream
}
if (-not $result.Ok) {
    Write-Log "could not bring in $($target.Ref) - left exactly as it was:" -Always
    foreach ($line in ($result.Out -split "`n")) { if ($line.Trim()) { Write-Log "    $($line.Trim())" -Always } }
    exit 1
}
$head = (Invoke-Git @("rev-parse", "HEAD")).Out
$aheadOut = (Invoke-Git @("rev-list", "--count", "$($target.Ref)..HEAD")).Out
Write-Log "updated $($before.Substring(0,7)) -> $($head.Substring(0,7)) from $($target.Ref)$(if ($aheadOut -and $aheadOut -ne '0') { " (this machine is $aheadOut commit(s) ahead - its own vault writes; not pushed)" })" -Always

# @() matters: a commit that touches ONE file makes -split return a bare string,
# and under StrictMode a string has no .Count. Caught by running a real update.
$changed = @((Invoke-Git @("diff", "--name-only", $before, "HEAD")).Out -split "`n" |
    ForEach-Object { $_.Trim() } | Where-Object { $_ })
Write-Log "  $($changed.Count) file(s) changed"

function Test-Changed {
    param([Parameter(Mandatory = $true)][string[]]$Patterns)
    foreach ($p in $Patterns) {
        if ($changed | Where-Object { $_ -like $p }) { return $true }
    }
    return $false
}

# Node lives outside PATH for scheduled tasks on this machine (see CLAUDE.md).
# LOCALAPPDATA is absent under some service accounts, so it is checked, not
# assumed - Join-Path throws on a null root and would abort the whole update.
$npm = "npm.cmd"
if ($env:LOCALAPPDATA) {
    $bundled = Join-Path (Join-Path $env:LOCALAPPDATA "Programs\nodejs") "npm.cmd"
    if (Test-Path -LiteralPath $bundled) { $npm = $bundled }
}

function Stop-WebHostForInstall {
    <#  npm cannot replace a file the running host has open: Prisma's query
        engine DLL is loaded by `next dev`, and Windows answers the rename with
        EPERM, so `npm ci` against a live host fails its postinstall (seen
        2026-09-18). Stop the host - and the watchdog, so it does not request a
        recovery halfway through the install - and wait for the port to clear.
        The restart step below brings the host back once the files are in
        place. Returns the task names it stopped. #>
    $stopped = @()
    foreach ($name in @("SecondBrain-WebWatchdog", "SecondBrain-WebHost")) {
        $t = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        if ($t -and $t.State -eq "Running") {
            Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
            $stopped += $name
        }
    }
    if ($stopped.Count -gt 0) {
        Write-Log "  stopped $($stopped -join ', ') so npm can replace files the host holds open"
        $deadline = (Get-Date).AddSeconds(15)
        while ((Get-Date) -lt $deadline -and
               @(Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue).Count -gt 0) {
            Start-Sleep -Milliseconds 500
        }
    }
    return $stopped
}

$stoppedForInstall = @()
if (Test-Changed @("package-lock.json", "package.json")) {
    $stoppedForInstall = @(Stop-WebHostForInstall)
    Invoke-InRepo $npm @("ci", "--no-audit", "--no-fund") "installing dependencies" | Out-Null
    if ($stoppedForInstall -contains "SecondBrain-WebWatchdog") {
        Start-ScheduledTask -TaskName "SecondBrain-WebWatchdog" -ErrorAction SilentlyContinue
    }
}
if (Test-Changed @("prisma/schema.prisma")) {
    Invoke-InRepo $npm @("run", "db:push") "applying the database schema" | Out-Null
}

if (Test-Changed @(".claude/agents/day-schedule.json", ".claude/scripts/setup_scheduler.ps1")) {
    $flags = @(Get-RegisteredAgentFlags)
    if ($flags.Count -eq 0) {
        Write-Log "  day schedule changed; no agent tasks registered here, so nothing to re-register"
    } else {
        Invoke-InRepo "powershell.exe" (@(
            "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-File", $schedulerScript) + $flags) "re-registering agent schedules ($($flags -join ' '))" | Out-Null
    }
    if (Get-ScheduledTask -TaskName "SecondBrain-MaxCycle" -ErrorAction SilentlyContinue) {
        # Registered, so keep it registered - its time comes from its own script.
        Invoke-InRepo "powershell.exe" @(
            "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-File", $maxCycleScript) "re-registering the Max cycle" | Out-Null
    }
}

if (Test-Changed @(".claude/scripts/setup_web_host.ps1", ".claude/scripts/run_web_host.ps1",
                  ".claude/scripts/watch_web_host.ps1", ".claude/scripts/recover_web_host.ps1")) {
    Invoke-InRepo "powershell.exe" @(
        "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
        "-File", $webHostScript) "re-registering the web host tasks" | Out-Null
}

# The dev host hot-reloads a changed page on its own, so a restart is only
# needed when something it loaded at startup changed - dependencies, the Next
# config, the TypeScript config, the environment. Restarting on every source
# edit would drop their session for no reason.
if (Test-Changed @("package-lock.json", "package.json", "next.config.ts", "tsconfig.json",
                  "postcss.config.mjs", "prisma/schema.prisma")) {
    if (Get-ScheduledTask -TaskName "SecondBrain-WebRecover" -ErrorAction SilentlyContinue) {
        Write-Log "  restarting the web host (startup-time config changed)"
        Start-ScheduledTask -TaskName "SecondBrain-WebRecover"
    } elseif ($stoppedForInstall -contains "SecondBrain-WebHost") {
        # No recovery task to do it properly, but this run stopped the host
        # itself, so it must not leave the dashboard down.
        Write-Log "  restarting the web host (stopped for the install)"
        Start-ScheduledTask -TaskName "SecondBrain-WebHost" -ErrorAction SilentlyContinue
    } else {
        Write-Log "  web host restart needed, but SecondBrain-WebRecover is not registered" -Always
    }
}

Write-Log "done." -Always
Show-ExternalAutomation
