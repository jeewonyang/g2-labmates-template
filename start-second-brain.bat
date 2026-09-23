@echo off
REM Launch the Second Brain dashboard: start the dev server (if not already
REM running) and open it in the default browser. Double-click this, or use the
REM "Second Brain" desktop shortcut that points here.

cd /d "%~dp0"
set "PATH=%LOCALAPPDATA%\Programs\nodejs;%PATH%"
set "URL=http://localhost:3000"

REM Is the server already up? (reuse it instead of starting a second one.)
powershell -NoProfile -Command "try{ if((Invoke-WebRequest '%URL%' -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200){ exit 0 } exit 1 }catch{ exit 1 }"
if %errorlevel%==0 goto :open

REM Prefer the independent scheduled recovery path when it is installed. This
REM replaces stale listeners instead of racing them with a second dev server.
schtasks /Query /TN "SecondBrain-WebRecover" >nul 2>&1
if %errorlevel% neq 0 goto :fallback
echo Requesting supervised G2 recovery...
schtasks /Run /TN "SecondBrain-WebRecover" >nul
if %errorlevel%==0 goto :wait

:fallback
REM Portable fallback for a clone where setup_web_host.ps1 has not been run.
echo Starting Second Brain server...
start "Second Brain server" /min cmd /k "cd /d "%~dp0" && set "PATH=%LOCALAPPDATA%\Programs\nodejs;%PATH%" && npm run dev"

:wait
REM Wait for the server to answer (up to ~90s), then open the browser.
echo Waiting for the server to be ready...
powershell -NoProfile -Command "for($i=0;$i -lt 180;$i++){ try{ if((Invoke-WebRequest '%URL%' -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200){ exit 0 } }catch{} Start-Sleep -Milliseconds 500 }; exit 1"
if %errorlevel% neq 0 (
  echo Server did not become ready in time. Open %URL% manually once it finishes starting.
  pause
  exit /b 1
)

:open
echo Opening %URL% ...
start "" "%URL%"
exit /b 0
