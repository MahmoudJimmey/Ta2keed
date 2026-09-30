@echo off
cd /d %~dp0
if not exist .venv python -m venv .venv
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt
echo.
echo   Ta2keed is running -^>  http://localhost:8000   (press Play demo)
echo.
python -m uvicorn ta2keed.server:app --port 8000
