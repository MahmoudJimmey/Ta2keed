#!/usr/bin/env bash
# Ta2keed launcher (macOS / Linux / Git-Bash)
#   ./run.sh          -> http://localhost:8000
#   ./run.sh online   -> + free public https link via Cloudflare quick tunnel (needs `cloudflared` installed)
set -e
cd "$(dirname "$0")"
PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null && "$c" -c 'import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)' 2>/dev/null; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "Python 3.10+ is required. Install it from https://www.python.org/downloads/ (macOS: brew install python) and run again."
  exit 1
fi
if [ ! -d .venv ]; then echo "First run: preparing Ta2keed (about a minute)..."; "$PY" -m venv .venv; fi
if [ -f .venv/bin/activate ]; then . .venv/bin/activate; else . .venv/Scripts/activate; fi
pip install -q --disable-pip-version-check -r requirements.txt
if python -c "import socket,sys; s=socket.socket(); sys.exit(0 if s.connect_ex(('127.0.0.1',8000))==0 else 1)"; then
  echo "Port 8000 is already in use (Ta2keed may already be running): open http://localhost:8000"
  exit 0
fi
if [ "$1" = "online" ]; then
  exec python scripts/online.py
fi
echo ""
echo "  Ta2keed is running →  http://localhost:8000   (first time: the setup wizard opens)"
echo "  Keep this terminal open. Ctrl+C stops it."
echo ""
exec python -m uvicorn ta2keed.server:app --port 8000
