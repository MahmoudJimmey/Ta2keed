#!/usr/bin/env bash
# One-command start (macOS / Linux / Git-Bash). Windows CMD/PowerShell: run.bat
set -e
cd "$(dirname "$0")"
PY=$(command -v python3 || command -v python)
if [ ! -d .venv ]; then "$PY" -m venv .venv; fi
if [ -f .venv/bin/activate ]; then . .venv/bin/activate; else . .venv/Scripts/activate; fi
pip install -q -r requirements.txt
echo ""
echo "  Ta2keed is running →  http://localhost:8000   (press ▶ Play demo)"
echo ""
python -m uvicorn ta2keed.server:app --port 8000
