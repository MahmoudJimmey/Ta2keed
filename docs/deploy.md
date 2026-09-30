# Where Ta2keed runs, and how to put it online

Ta2keed is a small web server (Python/FastAPI plus one SQLite file). It runs wherever you start it:

| Option | Good for | Reachable by WhatsApp? | Always on? | Cost |
|---|---|---|---|---|
| **Your computer**: `run.bat` | Trying it, the demo video, judges | ❌ | only while the PC is on | free |
| **Your computer + tunnel**: `run.bat online` | Testing real WhatsApp messages today | ✅ (link changes each run) | only while the PC is on | free |
| **Cloud host** (Render, Railway, Fly.io, VPS) | Real customers | ✅ fixed address | ✅ 24/7 | ~$5–7/month |

After starting, open **/setup**. The wizard walks through the shop, products, WhatsApp, AI, courier and alerts, and shows the exact webhook links to paste into Meta and Bosta.

---

## Option A: this computer

```bash
run.bat            # Windows
./run.sh           # macOS / Linux
```
The browser opens at http://localhost:8000. On first launch it goes to the setup wizard. On this computer no password is needed.

## Option B: this computer + free public link (test WhatsApp today)

```bash
run.bat online     # downloads Cloudflare's free tunnel tool the first time
```
It prints something like `https://brave-lion-1234.trycloudflare.com`. That address is saved automatically, so **/setup → WhatsApp** shows the ready-to-paste webhook URL. Keep the window open. Next time you run it you get a new link, and you have to update the webhook in Meta again.

## Option C: cloud host, 24/7 (for a real shop)

### Render (one click)
1. Click **https://render.com/deploy?repo=https://github.com/MahmoudJimmey/Ta2keed** (sign in with GitHub).
2. Render reads `render.yaml`: Docker, Frankfurt region, a 1 GB disk for orders and settings, and a generated `ADMIN_PASSWORD`.
3. When it's live, open **Environment** in Render, copy `ADMIN_PASSWORD`, go to `https://<your-app>.onrender.com/setup` and log in. `TA2KEED_SECRET_KEY` (the key that encrypts your API tokens) is generated there too. Keep a copy somewhere safe.
4. Finish the wizard. The webhook URLs it shows are already correct.

> The Starter plan (~$7/month) is needed for the persistent disk. On the free plan the app sleeps after 15 minutes (WhatsApp messages wake it, but the first reply is slow) and **loses its data on every restart**.

### Railway / Fly.io / any Docker host
The `Dockerfile` works everywhere. The important parts:
- Mount a **persistent volume at `/data`** (orders, settings, shop profile).
- Set `ADMIN_PASSWORD` (or use the one-time setup link below).
- The app listens on `$PORT` (default 8000).

```bash
docker build -t ta2keed .
docker run -d -p 8000:8000 -v ta2keed-data:/data -e ADMIN_PASSWORD='change-me-please' ta2keed
```

### A VPS (e.g. a $5 droplet)
Same Docker command, plus a free HTTPS proxy such as Caddy (`caddy reverse-proxy --from yourdomain.com --to :8000`). Meta requires https.

---

## Security when online
Full details: [security.md](security.md).
- The dashboard and wizard require the **owner password** once the server is reachable from outside.
- Started online **without** a password? The server log prints a one-time link `…/setup?token=…`. Only someone with access to the logs can claim the server, and the first wizard step sets the password.
- `/webhook/whatsapp` checks Meta's signature (set the App secret in the wizard). Courier webhooks check `COURIER_WEBHOOK_SECRET`.
- Secrets typed in the wizard are stored in `<data dir>/settings.json` (never in git). Values set as host environment variables always win and show as 🔒 in the wizard.

## Where the data lives
| File (in `instance/` locally, `/data` on a host) | What |
|---|---|
| `ta2keed.db` | orders, conversations, payments, events |
| `settings.json` | everything entered in the wizard (tokens, owner number, …) |
| `store.json` | your shop profile: products, fees, policies, business numbers |

Back up that folder and you've backed up the whole shop.
