@echo off
REM Bring this machine's G2 up to date with git and apply what a pull does not:
REM dependencies, the database schema, the Windows scheduled tasks (they store a
REM snapshot of day-schedule.json, so they must be re-registered), and a web-host
REM restart when startup config changed. Safe by construction: fast-forward only,
REM and it refuses to touch a checkout with uncommitted work.
REM
REM   update-g2.bat            update now
REM   update-g2.bat -Status    report only: behind by how much, schedule drift
powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0.claude\scripts\apply_update.ps1" %*
exit /b %errorlevel%
