@echo off
title Second Brain
REM Launch the Second Brain dashboard. Node isn't on the system PATH on this
REM machine, so add it here; then start the Next dev server and open the wiki.
set "PATH=%LOCALAPPDATA%\Programs\nodejs;%PATH%"
cd /d "%~dp0..\.."

REM Open the browser to the wiki as soon as the server responds (runs hidden,
REM in parallel with the server below).
start "" /min powershell -NoProfile -WindowStyle Hidden -Command "for($i=0;$i -lt 120;$i++){try{Invoke-WebRequest 'http://localhost:3000' -UseBasicParsing -TimeoutSec 2 | Out-Null; Start-Process 'http://localhost:3000/wiki'; break}catch{Start-Sleep 1}}"

echo Starting the Second Brain website...
echo The browser opens automatically once it's ready (first start can take ~30s).
echo Keep this window open while you use the site. Close it to stop the server.
echo.
call npm run dev
