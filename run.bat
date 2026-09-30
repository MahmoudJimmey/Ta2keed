@echo off
setlocal
REM Ta2keed launcher (Windows). Double-click this file.
REM   run.bat          -> runs on this computer: http://localhost:8000
REM   run.bat online   -> same + a free public https link (Cloudflare quick tunnel) so WhatsApp can reach it
cd /d "%~dp0"
title Ta2keed

REM ---- 1. find a real Python 3.10+ (the Microsoft Store "python" stub does not count)
set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1 && set "PY=py -3"
if not defined PY python -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1 && set "PY=python"
if not defined PY (
  echo.
  echo   [!] Python 3.10 or newer is not installed.
  echo.
  echo       1. Open https://www.python.org/downloads/ and click "Download Python".
  echo       2. Run the installer and TICK the box "Add python.exe to PATH" at the bottom.
  echo       3. Close this window and double-click run.bat again.
  echo.
  start "" https://www.python.org/downloads/
  pause
  exit /b 1
)

REM ---- 2. private environment + libraries (first run only takes ~1 minute)
if not exist .venv\Scripts\python.exe (
  echo   First run: preparing Ta2keed, this takes about a minute...
  %PY% -m venv .venv || goto :fail
)
.venv\Scripts\python.exe -m pip install -q --disable-pip-version-check -r requirements.txt || goto :fail_pip

REM ---- 3. make sure port 8000 is free
.venv\Scripts\python.exe -c "import socket,sys; s=socket.socket(); sys.exit(s.connect_ex(('127.0.0.1',8000))==0)"
if errorlevel 1 (
  echo.
  echo   [!] Ta2keed ^(or another program^) is already running on port 8000.
  echo       Opening it in your browser. Close the other black window first if you want to restart.
  start "" http://localhost:8000
  pause
  exit /b 0
)

if /I "%~1"=="online" goto :online

echo.
echo   ============================================================
echo     Ta2keed is running:  http://localhost:8000
echo     First time? The setup wizard opens automatically.
echo     KEEP THIS WINDOW OPEN. Closing it stops the agent.
echo   ============================================================
echo.
start "" http://localhost:8000
.venv\Scripts\python.exe -m uvicorn ta2keed.server:app --port 8000
goto :eof

:online
if not exist tools\cloudflared.exe (
  echo   Downloading cloudflared ^(one time, ~30 MB^)...
  mkdir tools 2>nul
  powershell -NoProfile -Command "Invoke-WebRequest https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe -OutFile tools\cloudflared.exe" || goto :fail
)
.venv\Scripts\python.exe scripts\online.py
pause
goto :eof

:fail_pip
echo.
echo   [!] Could not download the libraries. Check your internet connection and run again.
pause
exit /b 1
:fail
echo.
echo   [!] Something went wrong above. Take a screenshot of this window and send it to the developer.
pause
exit /b 1
