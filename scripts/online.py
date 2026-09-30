"""Run Ta2keed on this computer AND expose it on a free public https link (Cloudflare quick tunnel).

The link is saved as PUBLIC_URL so the setup wizard shows ready-to-paste webhook URLs for Meta/Bosta.
Quick-tunnel links change on every run: fine for testing, use a cloud host (docs/deploy.md) for real customers.
"""
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
PORT = int(os.environ.get("PORT", "8000"))


def find_cloudflared() -> str | None:
    local = ROOT / "tools" / ("cloudflared.exe" if os.name == "nt" else "cloudflared")
    return str(local) if local.exists() else shutil.which("cloudflared")


def main() -> None:
    cf = find_cloudflared()
    if not cf:
        print("cloudflared not found. Windows: run  run.bat online  (downloads it). "
              "macOS: brew install cloudflared · Linux: see developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/")
        sys.exit(1)

    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "ta2keed.server:app", "--port", str(PORT),
                               "--proxy-headers", "--forwarded-allow-ips=*"], cwd=ROOT)
    tunnel = subprocess.Popen([cf, "tunnel", "--no-autoupdate", "--url", f"http://localhost:{PORT}"],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    url = None

    def pump():
        nonlocal url
        for line in tunnel.stdout:
            m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
            if m and not url:
                url = m.group(0)
    threading.Thread(target=pump, daemon=True).start()

    for _ in range(60):
        if url:
            break
        time.sleep(0.5)
    if not url:
        print("Tunnel did not start (firewall?). Ta2keed still runs on http://localhost:%d" % PORT)
    else:
        from ta2keed.config import save_wizard_values
        save_wizard_values({"PUBLIC_URL": url})
        print("\n" + "=" * 72)
        print(f"  Ta2keed is ONLINE:   {url}")
        print(f"  WhatsApp webhook:    {url}/webhook/whatsapp")
        print(f"  Setup wizard:        http://localhost:{PORT}/setup   (on this computer)")
        print("  Keep this window open. The link changes next time you run it.")
        print("=" * 72 + "\n")
        webbrowser.open(f"http://localhost:{PORT}/setup")
    try:
        server.wait()
    except KeyboardInterrupt:
        pass
    finally:
        tunnel.terminate()
        server.terminate()


if __name__ == "__main__":
    main()
