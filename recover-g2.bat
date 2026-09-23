@echo off
REM Independent recovery entry point. This asks Task Scheduler to restart G2;
REM it does not call the G2 server, so it still works when port 3000 is dead.

schtasks /Run /TN "SecondBrain-WebRecover"
if errorlevel 1 (
  echo G2 recovery task is not available. Run .claude\scripts\setup_web_host.ps1 first.
  exit /b 1
)
echo G2 recovery requested. It can take up to two minutes to become healthy.
exit /b 0
