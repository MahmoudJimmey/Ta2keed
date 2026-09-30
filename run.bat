@echo off
REM Ta2keed launcher (Windows)
REM   run.bat          -> runs on this computer: http://localhost:8000
REM   run.bat online   -> same + a free public https link (Cloudflare quick tunnel) so WhatsApp can reach it
cd /d %~dp0
if not exist .venv python -m venv .venv
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt

if /I "%1"=="online" goto online

echo.
echo   Ta2keed is running on this computer:  http://localhost:8000
echo   First time? The setup wizard opens automatically.
echo.
start "" http://localhost:8000
python -m uvicorn ta2keed.server:app --port 8000
goto :eof

:online
if not exist tools\cloudflared.exe (
  echo Downloading cloudflared ^(one time, ~30 MB^)...
  mkdir tools 2>nul
  powershell -NoProfile -Command "Invoke-WebRequest https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe -OutFile tools\cloudflared.exe"
)
python scripts\online.py
