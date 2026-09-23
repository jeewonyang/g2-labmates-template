@echo off
REM Wrapper invoked by Windows Task Scheduler for background agent jobs.
REM Usage: run_task.bat <script-name.py> [args...]
REM Uses `python` from PATH. That must be a real (non-Windows-Store) Python:
REM Task Scheduler runs the Store alias unreliably headless. Set
REM SECONDBRAIN_PYTHON to the full path of an interpreter to override.
REM Runs from the repo root so relative paths (VAULT/, .claude/) resolve.
REM stdout/stderr go to a per-task log; the scripts also write structured logs
REM under .claude/data/logs.

set "REPO=%~dp0..\.."
set "PY=python"
if defined SECONDBRAIN_PYTHON set "PY=%SECONDBRAIN_PYTHON%"
set "SCRIPT=%~1"
cd /d "%REPO%"
"%PY%" ".claude\scripts\%SCRIPT%" %2 %3 %4 %5 >> ".claude\data\logs\scheduler.log" 2>&1
