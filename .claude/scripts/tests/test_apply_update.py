"""The base-server updater must never be able to lose their work.

`apply_update.ps1` runs unattended every 30 minutes against the checkout that
serves the dashboard, so its safety is structural rather than careful: it
fast-forwards only, it refuses a dirty tree, it follows the checked-out
branch's own upstream, and it re-registers exactly the scheduled tasks that
were already there. These tests read the script as text - PowerShell is not
available on every machine this suite runs on, and the properties worth
protecting are all visible in the source.

Run: python .claude/scripts/tests/test_apply_update.py
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
REPO = SCRIPTS.parents[1]

UPDATER = SCRIPTS / "apply_update.ps1"
WEB_HOST = SCRIPTS / "setup_web_host.ps1"
SCHEDULER = SCRIPTS / "setup_scheduler.ps1"
LAUNCHER = REPO / "update-g2.bat"
SCHEDULE = REPO / ".claude" / "agents" / "day-schedule.json"


def _src() -> str:
    return UPDATER.read_text(encoding="utf-8")


def _code() -> str:
    """The script minus its comment block and per-line comments."""
    text = re.sub(r"<#.*?#>", "", _src(), flags=re.S)
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )


def test_history_is_never_rewritten_and_work_is_never_discarded():
    code = _code()
    assert "merge --ff-only" in code.replace('", "', " ").replace('"', "") or \
        '"merge", "--ff-only"' in code, "the only way it advances is a fast-forward"
    for forbidden in (
        "reset --hard", "clean -fd", "checkout --force", "push --force",
        "stash", "rebase", "--force-with-lease", "Remove-Item", "rm -",
    ):
        assert forbidden not in code, f"{forbidden!r} has no place in an unattended updater"
    # The `git` calls it is allowed to make, by subcommand. `add`/`commit` are
    # for this machine's own vault writes; `merge --abort` is how a conflict is
    # backed out; nothing here pushes.
    subcommands = set(re.findall(r'Invoke-Git @\("([a-z\-]+)"', code))
    assert subcommands <= {"rev-parse", "fetch", "status", "merge", "diff", "log", "rev-list", "add", "commit"}, subcommands
    assert '"push"' not in code
    # A failed merge is aborted, never left half-done for an unattended machine.
    assert '"merge", "--abort"' in code


def test_native_stderr_never_terminates_the_updater():
    """Windows PowerShell 5.1 + $ErrorActionPreference = "Stop" + `2>&1` turns a
    native command's stderr into a terminating error. git's ff-only probe
    prints a hint there on every run where this machine has its own commits,
    which killed the script before the real merge (2026-09-18). Both wrappers
    must run with a function-local "Continue"."""
    code = _code()
    for fn in ("Invoke-Git", "Invoke-InRepo"):
        start = code.index(f"function {fn}")
        body = code[start:code.index("\nfunction ", start + 1)]
        assert '$ErrorActionPreference = "Continue"' in body, f"{fn} must not inherit Stop"
        assert "2>&1" in body, f"{fn} still captures stderr"
    assert '$ErrorActionPreference = "Stop"' in code, "the script-level preference stays Stop"


def test_dependencies_install_with_the_host_stopped():
    """`npm ci` against a running `next dev` fails with EPERM on Prisma's query
    engine DLL (2026-09-18). The host and its watchdog are stopped before the
    install, the watchdog restarted after it, and the host restart step still
    follows - even without the recovery task, a host this run stopped is
    started again."""
    code = _code()
    stop = code.index("function Stop-WebHostForInstall")
    ci = code.index('"ci", "--no-audit"')
    assert stop < ci, "the host is stopped before npm ci runs"
    body = code[stop:ci]
    assert 'Stop-ScheduledTask -TaskName $name' in body and '"SecondBrain-WebHost"' in body
    assert '"SecondBrain-WebWatchdog"' in body, "the watchdog is stopped too, or it recovers mid-install"
    after = code[ci:]
    assert 'Start-ScheduledTask -TaskName "SecondBrain-WebWatchdog"' in after, "the watchdog comes back"
    assert 'Start-ScheduledTask -TaskName "SecondBrain-WebHost"' in after, "a host this run stopped is restarted"
    assert "Stop-Process" not in code, "orphan handling stays in recover_web_host.ps1, which proves ownership first"


def test_uncommitted_code_stops_the_update_but_vault_writes_are_committed():
    """Agents on the base machine append to tracked files under VAULT/Memory all
    day (calendar-writes.md, daily logs, MEMORY.md). Refusing on any dirt blocked
    the second-ever run (2026-09-17). Vault dirt is committed and carried; code
    dirt - anything else - still stops everything, untouched."""
    code = _code()
    assert "--untracked-files=no" in code, (
        "ignored/untracked files are always present here (.claude/data, dev.db); "
        "counting them as local work would block every update"
    )
    assert '$_ -like "VAULT/Memory/*"' in code and '$_ -notlike "VAULT/Memory/*"' in code
    assert '"add", "-u", "--", "VAULT/Memory"' in code, "only tracked vault files, only that folder"
    assert "Vault: agent writes on" in code
    # Refusal and commit both happen before anything is merged.
    assert code.index("if ($codeDirty.Count -gt 0)") < code.index('"merge", "--ff-only"')
    assert code.index('"add", "-u", "--", "VAULT/Memory"') < code.index('"merge", "--ff-only"')


def test_untracked_vault_collision_is_renamed_aside_never_deleted():
    code = _code()
    assert "Resolve-UntrackedCollision" in code
    assert 'notlike "VAULT/*"' in code, "only vault files are moved aside; code is reported"
    assert "Move-Item" in code and ".local-" in code
    assert "Remove-Item" not in code


def test_it_follows_the_checked_out_branch_upstream():
    """An unmerged feature branch must not be able to deploy itself."""
    code = _code()
    assert "--symbolic-full-name" in code and "@{u}" in code
    assert "$SAFE_REF" in code, "an explicit -Branch becomes a git argument and is validated"
    pattern = re.search(r"\$SAFE_REF = '([^']+)'", code)
    assert pattern, "SAFE_REF must be a literal pattern"
    rx = re.compile(pattern.group(1))
    assert rx.match("main") and rx.match("claude/inspiring-archimedes-wa9ha9")
    for bad in ("--upload-pack=evil", "; rm -rf /", "-x", "..", "$(whoami)"):
        assert not rx.match(bad), bad


def test_scheduled_tasks_are_re_registered_from_what_is_registered():
    """The gap this closes: Task Scheduler stores a snapshot of the trigger
    times, so editing day-schedule.json changes nothing until the tasks are
    registered again. Re-registering must reproduce their opt-in set, never widen
    it - turning automation on that they left off would be the script making a
    decision instead of applying one."""
    code = _code()
    assert "day-schedule.json" in code and "setup_scheduler.ps1" in code
    assert "Get-RegisteredAgentFlags" in code
    flags = set(re.findall(r'"(-Enable[A-Za-z]+)"', code))
    assert flags == {
        "-EnableDailyRun", "-EnableSlackMonitor", "-EnableHeartbeat",
        "-EnableReflection", "-EnableWiki",
    }, flags
    # Every flag it can re-register must be a flag the scheduler accepts.
    scheduler = SCHEDULER.read_text(encoding="utf-8")
    for flag in flags:
        assert f"[switch]${flag[1:]}" in scheduler.replace("\n", " ") or flag[1:] in scheduler, flag
    # A flag list is only ever built from registered tasks.
    block = code[code.index("function Get-RegisteredAgentFlags"):]
    block = block[: block.index("function Get-ExpectedStarts")]
    assert "Get-ScheduledTask" in block and "SilentlyContinue" in block


def test_drift_is_reported_against_the_day_schedule():
    code = _code()
    assert "Get-ScheduleDrift" in code and "StartBoundary" in code
    expected = re.search(r"function Get-ExpectedStarts.*?^}", code, re.S | re.M)
    assert expected, "expected-times table must exist"
    body = expected.group(0)
    automation = json.loads(SCHEDULE.read_text(encoding="utf-8"))["automation"]
    for key in ("morning_run", "evening_run", "reflection", "wiki"):
        assert f"$a.{key}" in body, key
    for key in ("intraday_admin", "heartbeat", "slack_monitor"):
        assert f"$a.{key}.start" in body, key
    # Every task named in the drift table is one setup_scheduler.ps1 registers.
    named = set(re.findall(r'"(SecondBrain-[A-Za-z]+)"\s*=', body))
    scheduler = SCHEDULER.read_text(encoding="utf-8")
    for task in named:
        assert task in scheduler, task
    assert automation, "day-schedule.json must carry an automation section"


def test_the_web_host_restarts_only_for_startup_time_changes():
    """A dev server hot-reloads a page edit. Restarting on every source change
    would drop whatever they have open for no reason."""
    code = _code()
    restart = code[code.index("SecondBrain-WebRecover"):]
    assert "Start-ScheduledTask" in restart
    guard = re.search(
        r'if \(Test-Changed @\("package-lock\.json"[^)]*\)\) \{\s*\n\s*if \(Get-ScheduledTask -TaskName "SecondBrain-WebRecover"',
        code,
    )
    assert guard, "the restart must be behind a startup-config-changed test"
    assert '"src/' not in guard.group(0), "a source edit alone must not restart the host"


def test_auto_update_is_registered_as_infrastructure_and_can_be_declined():
    host = WEB_HOST.read_text(encoding="utf-8")
    assert "SecondBrain-Update" in host
    assert "apply_update.ps1" in host and "-Quiet" in host
    assert "$NoAutoUpdate" in host, "they must be able to decline automatic pulls"
    assert '$taskNames = @($hostTask, $watchTask, $recoverTask, $updateTask)' in host, (
        "-Remove must clean up the update task too"
    )
    # It belongs with web-host infrastructure, not with the removable agent
    # automation: setup_scheduler.ps1's no-flag mode unregisters everything it
    # owns, and deployment currency must survive that.
    assert "SecondBrain-Update" not in SCHEDULER.read_text(encoding="utf-8")


def test_vault_markdown_merges_by_union_so_the_updater_never_stalls_on_memory():
    """Both machines append to MEMORY.md and the logs. A line-level conflict
    there would leave the unattended updater stuck every 30 minutes; keeping
    both sides is always the better outcome for a memory file. Code is not
    covered - a conflict there must still stop the update."""
    attrs = (REPO / ".gitattributes").read_text(encoding="utf-8")
    rules = [l.split() for l in attrs.splitlines() if l.strip() and not l.startswith("#")]
    assert ["VAULT/Memory/**/*.md", "merge=union"] in rules, rules
    for pattern, *_ in rules:
        assert pattern.startswith("VAULT/Memory/"), f"union merge must stay inside the vault: {pattern}"


def test_launcher_exists_for_ssh_and_passes_arguments_through():
    bat = LAUNCHER.read_text(encoding="utf-8")
    assert "apply_update.ps1" in bat
    assert "%*" in bat, "-Status has to reach the script"
    assert "%~dp0" in bat, "must work from any working directory (SSH lands in %USERPROFILE%)"


def test_powershell_parses_when_available():
    """Real syntax check on Windows; skipped elsewhere."""
    exe = shutil.which("powershell.exe") or shutil.which("pwsh")
    if not exe:
        print("SKIP test_powershell_parses_when_available (no PowerShell on this machine)")
        return
    for script in (UPDATER, WEB_HOST):
        checker = (
            "$ErrorActionPreference='Stop';"
            "$t=[System.Management.Automation.Language.Parser]::ParseFile("
            f"'{script}', [ref]$null, [ref]$errs);"
            "if ($errs) { $errs | ForEach-Object { $_.Message }; exit 1 }"
        )
        proc = subprocess.run(
            [exe, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
             "$errs=$null;" + checker],
            capture_output=True, text=True, timeout=60,
        )
        assert proc.returncode == 0, f"{script.name}: {proc.stdout}{proc.stderr}"


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {fn.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"ERROR {fn.__name__}: {type(exc).__name__}: {exc}")
    total = len(tests)
    print(f"\n{total - failed}/{total} updater tests passed." if not failed
          else f"\n{failed} of {total} updater tests FAILED.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
