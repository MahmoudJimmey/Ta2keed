#!/usr/bin/env bash
# Ta2keed launcher (macOS / Linux / Git-Bash)
#   ./run.sh          -> http://localhost:8000
#   ./run.sh online   -> + free public https link via Cloudflare quick tunnel (needs `cloudflared` installed)
set -e
cd "$(dirname "$0")"
PY=$(command -v python3 || command -v python)
if [ ! -d .venv ]; then "$PY" -m venv .venv; fi
if [ -f .venv/bin/activate ]; then . .venv/bin/activate; else . .venv/Scripts/activate; fi
pip install -q -r requirements.txt
if [ "$1" = "online" ]; then
  exec python scripts/online.py
fi
echo ""
echo "  Ta2keed is running →  http://localhost:8000   (first time: the setup wizard opens)"
echo ""
exec python -m uvicorn ta2keed.server:app --port 8000
