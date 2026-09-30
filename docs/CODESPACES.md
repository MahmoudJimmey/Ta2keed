# Run Ta2keed online, no installation (GitHub Codespaces)

Everything runs on GitHub's computers, in your browser. You don't install Python or anything else.
It's **free** for about 60 hours a month on a free GitHub account.

## Start it (3 clicks)
1. Sign in at **github.com** (free account).
2. Open **https://github.com/MahmoudJimmey/Ta2keed** (or your fork), then click the green **`<> Code`** button → **Codespaces** tab → **Create codespace on main**.
   Or click this button: [![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/MahmoudJimmey/Ta2keed?quickstart=1)
3. Wait about 2 minutes the first time. An editor opens in the browser, and a **terminal** at the bottom shows:

```
   ✅ Ta2keed is running in your Codespace.
   👉  Ctrl+Click this link to open it:
       https://<your-codespace>-8000.app.github.dev/setup?token=...
```

4. **Ctrl+Click the link** (Cmd+Click on Mac). The setup wizard opens in a new tab. Set your owner password in the first step, then follow the wizard (see [SETUP-GUIDE.md](SETUP-GUIDE.md), Part 2).

✅ You should see the Ta2keed setup wizard. Choose **▶ Just show me the demo** to try it straight away.

## Connect WhatsApp / Bosta webhooks (optional)
Meta and Bosta need to reach your link, so it must be **public**. In the codespace terminal type:
```
python scripts/codespace.py public
```
Or open the **PORTS** tab → right-click **8000** → **Port Visibility → Public**. Your dashboard stays protected by your owner password.

## Good to know
| | |
|---|---|
| **Stopping** | Codespaces pause after ~30 min with no activity, and the agent stops with them. Your orders and settings are kept. |
| **Starting again** | github.com/codespaces → click your codespace. Ta2keed restarts by itself and prints the link again. |
| **The link didn't appear** | In the terminal, type `python scripts/codespace.py` and press Enter. |
| **"This Ta2keed server has not been set up yet"** | You opened the address without `?token=…`. Use the full link from the terminal. |
| **Cost** | Free GitHub accounts get 120 core-hours/month (≈60 hours of this 2-core codespace). Delete codespaces you don't use at github.com/codespaces. |
| **Real customers, 24/7** | Codespaces are for trying and demos. For a real shop use **Render** (also no Python needed): [SETUP-GUIDE.md → Part 6](SETUP-GUIDE.md#part-6--put-it-online-247). |
