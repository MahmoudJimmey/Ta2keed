"""Start Ta2keed inside GitHub Codespaces (no Python on your computer; everything runs in the browser).

Runs automatically when the codespace opens. It prints ONE link: click it to open the setup wizard.
    python scripts/codespace.py          # start (private link, only you, signed in to GitHub)
    python scripts/codespace.py public   # also make the link public so WhatsApp / Bosta webhooks can reach it
"""
import functools
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

print = functools.partial(print, flush=True)  # show the link immediately, even when output is piped
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
PORT = os.environ.get("PORT", "8000")
name, dom = os.environ.get("CODESPACE_NAME"), os.environ.get("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN")
BASE = f"https://{name}-{PORT}.{dom}" if name and dom else f"http://localhost:{PORT}"


def up() -> bool:
    try:
        return urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=2).status == 200
    except Exception:
        return False


def make_public() -> None:
    r = subprocess.run(["gh", "codespace", "ports", "visibility", f"{PORT}:public", "-c", name or ""],
                       capture_output=True, text=True)
    print("  Link is now PUBLIC (needed for WhatsApp/Bosta webhooks). The dashboard stays password-protected."
          if r.returncode == 0 else
          "  Couldn't switch automatically. Open the PORTS tab → right-click port 8000 → Port Visibility → Public.")


def banner() -> None:
    from ta2keed import auth
    from ta2keed.config import settings
    link = f"{BASE}/" if settings.admin_password else f"{BASE}/setup?token={auth.setup_token()}"
    line = "=" * 78
    print(f"\n{line}\n")
    print("   ✅ Ta2keed is running in your Codespace.\n")
    print("   👉  Ctrl+Click (Cmd+Click on Mac) this link to open it:\n")
    print(f"       {link}\n")
    if not settings.admin_password:
        print("   Step 1 of the wizard sets your owner password. Keep this link private until then.")
    else:
        print("   Log in with your owner password.")
    print("   Keep this browser tab open. Codespaces pause after ~30 min without activity,")
    print("   and it's for trying Ta2keed. For real customers 24/7, use Render (docs/SETUP-GUIDE.md, Part 6).")
    print(f"\n{line}\n")


def main() -> None:
    if up():
        print("Ta2keed is already running.")
        banner()
        return
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "ta2keed.server:app", "--host", "0.0.0.0",
                               "--port", PORT, "--proxy-headers", "--forwarded-allow-ips=*"], cwd=ROOT)
    for _ in range(120):
        if up():
            break
        if server.poll() is not None:
            print("Ta2keed failed to start. See the error above.")
            sys.exit(1)
        time.sleep(0.5)
    if "public" in sys.argv[1:]:
        make_public()
    banner()
    try:
        server.wait()
    except KeyboardInterrupt:
        server.terminate()


if __name__ == "__main__":
    main()
