# Ta2keed setup guide: step by step

This guide assumes no technical background. Follow the steps in order. Each step ends with **✅ You should see…** so you know it worked. If it didn't, check the **🆘 If it goes wrong** box or the [troubleshooting table](#troubleshooting) at the end.

| Part | What | Time | Needed? |
|---|---|---|---|
| [1](#part-1--download-and-start-it) | Download and start it | 5 min | ✅ Yes |
| [2](#part-2--the-setup-wizard) | Fill in the setup wizard (shop, products, fees) | 15 min | ✅ Yes |
| [3](#part-3--telegram-alerts-for-the-owner-recommended) | Owner alerts on Telegram (payment confirmations) | 5 min | ⭐ Recommended |
| [4](#part-4--whatsapp-for-customers) | WhatsApp for your customers | 30 min + Meta approval | For real customers |
| [5](#part-5--bosta-courier-optional) | Bosta courier | 10 min | Optional |
| [6](#part-6--put-it-online-247) | Put it online 24/7, without your computer | 15 min | For real customers |
| [7](#part-7--everyday-use) | Everyday use | — | — |

> **Just want to see the demo?** Do Part 1, choose **▶ Just show me the demo**, and press **Play**. No accounts or keys needed.

---

## Part 1 · Download and start it

### Step 1.1: Install Python (one time only)
1. Open **https://www.python.org/downloads/** and click the yellow **Download Python** button.
2. Open the downloaded file.
3. ⚠️ **Important:** at the bottom of the first window, **tick "Add python.exe to PATH"**. Then click **Install Now**.
4. When it finishes, click **Close**.

✅ You should see "Setup was successful".

### Step 1.2: Download Ta2keed
1. Open **https://github.com/MahmoudJimmey/Ta2keed**.
2. Click the green **`<> Code`** button, then **Download ZIP**.
3. Open your Downloads folder, right-click **Ta2keed-main.zip**, then **Extract All… → Extract**.
4. Move the extracted **Ta2keed-main** folder somewhere permanent, such as `Documents`. Don't run it from inside the zip.

✅ You should see a folder containing `run.bat`, `README.md`, and folders named `ta2keed`, `web` and `data`.

### Step 1.3: Start it
1. Double-click **`run.bat`**.
2. If Windows shows **"Windows protected your PC"**, click **More info → Run anyway**. This only appears the first time.
3. A black window opens. The **first time** it prepares everything for about 1 minute.

✅ You should see `Ta2keed is running: http://localhost:8000`, and your browser opens the **setup wizard** automatically.

> ⚠️ **Keep the black window open.** Closing it stops the agent. To start it again later, double-click `run.bat` again. Your data is kept.

> 🆘 **If it goes wrong**
> - *"Python 3.10 or newer is not installed"*: repeat Step 1.1 and make sure you tick **Add python.exe to PATH**.
> - *"Could not download the libraries"*: check your internet connection and run it again.
> - *The browser didn't open*: open it yourself and go to **http://localhost:8000**.
> - *"already running on port 8000"*: another Ta2keed window is still open. Use that one, or close it first.

---

## Part 2 · The setup wizard

The wizard lives at **http://localhost:8000/setup**, and you can come back to it anytime. The steps are listed on the left. Each one saves as soon as you press **Save & continue →**. Nothing needs a restart.

**Welcome.** Choose **Go live** to set up your real shop, or **▶ Just show me the demo** to try the sample shop first.

**Step 2.1: Owner login**
- Type a password and remember it. You'll need it when you open the dashboard from your phone or online.
- On this computer only? You can press **Skip (this computer only)**, but you **must** set a password before going online (Part 6).

**Step 2.2: Your shop**
- **Shop name** (English and Arabic) and the **assistant's name**, which customers see.
- **InstaPay address** and/or **Vodafone Cash number**. ⚠️ Type these exactly. The agent rejects receipts sent to any other account.
- **Deposit amount** (e.g. 100 EGP) and **when to ask for it**. The default asks only the riskiest orders.
- **Business hours.**
- ✅ Keep **"Confirm every transfer yourself"** ticked. It's the protection against fake or reused screenshots. See [Part 7](#when-a-transfer-to-confirm-arrives).

**Step 2.3: Products**
- Add each product: name, price, sizes and colours.
- **Keywords** are the words customers actually type, in Arabic, Franco and with typos (e.g. `فستان, fostan, فسطان`). More keywords mean fewer questions to the customer.
- **Upsell**: the product to suggest with it, and its discount.
- Lots of products? Download the **CSV template**, fill it in Excel, and upload it.

**Step 2.4: Shipping & fees**
- The delivery fee per zone (Cairo, Giza, Alexandria, Delta, Upper Egypt, …) and what a **returned parcel costs you**.

**Step 2.5: AI brain** *(optional, skip it at first)*
- Without AI, the agent already understands normal Egyptian Arabic orders, for free.
- With AI it also understands unusual messages and **reads real receipt screenshots**. Pick **Google Gemini** (it has a free tier), get a key at **aistudio.google.com/apikey**, paste it, and press **Test connection**.
- ✅ You should see a green "Connected".

**Step 2.6: WhatsApp.** See [Part 4](#part-4--whatsapp-for-customers). Press **Skip for now** for the moment.

**Step 2.7: Alerts & daily summary.** See [Part 3](#part-3--telegram-alerts-for-the-owner-recommended). Do it next.

**Step 2.8: Courier.** Keep **Demo** for now, or see [Part 5](#part-5--bosta-courier-optional).

**Step 2.9: Business numbers**
- Your real **orders per month**, **minutes per order today**, and **refusal rate**. Rough numbers are fine. They drive the savings shown on the dashboard.

**Step 2.10: Go live.** Read the checklist, then press **✓ Finish & open dashboard**.

✅ You should see the dashboard: **Today**, the numbers, **Orders**, and a phone preview on the right. Type an order into the phone, e.g. `عايزة فستان صيفي مقاس M`, to try it.

---

## Part 3 · Telegram alerts for the owner (recommended)

Telegram is the easiest way to get **"Did this transfer arrive? ✅ / ❌"** questions, alerts and the daily summary on your phone. It's free and needs no approval.

1. Install **Telegram** on your phone and sign in.
2. In Telegram, search for **@BotFather** (the one with the blue tick) and open it.
3. Send `/newbot`.
4. Enter a name, e.g. `Nour Boutique Ta2keed`.
5. Enter a username that ends in `bot`, e.g. `nourboutique_ta2keed_bot`.
6. BotFather replies with a **token** like `7412345678:AAH…`. Copy it.
7. In the wizard: **Alerts & daily summary**, paste the token into **Telegram bot token**, and press **Test**.
8. In Telegram, open **your new bot** (tap the `t.me/…` link BotFather sent) and press **Start**.
9. Send the bot the message shown in the wizard, e.g. `/owner 482913`. The code is different for every shop.
10. Press **Refresh** in the wizard, then **Send today's summary now**.

✅ You should see the daily summary arrive in Telegram. The wizard shows your chat as linked.

> 🆘 *The bot doesn't reply*: make sure the black window (Part 1.3) is still open, wait about 10 seconds, and send `/owner <code>` again. The code must match what the wizard shows.
>
> 🔒 Only the Telegram account that sent `/owner <code>` can approve payments. If anyone else presses the buttons, the bot refuses.

---

## Part 4 · WhatsApp for customers

> You need: a **phone number not already used on the WhatsApp app** (or Meta's free test number to start), a **Facebook account**, and your agent reachable from the internet: **Part 6**, or `run.bat online` for testing.

### Step 4.1: Create the Meta app
1. Go to **https://developers.facebook.com** → **Get started** (sign in with Facebook) → **My Apps → Create app**.
2. Choose **Other → Business** (or **"Connect with customers through WhatsApp"**), give it a name, and create it.
3. On the app page, find **WhatsApp** and click **Set up**. Create or choose a Business portfolio.

### Step 4.2: Copy the 4 values into the wizard (step "WhatsApp")
From **WhatsApp → API Setup**:
- **Temporary access token**: copy it to **Access token**. It expires in 24 h; Step 4.5 makes it permanent.
- **Phone number ID**: copy it to **Phone number ID**.
- **WhatsApp Business Account ID**: copy it to **WABA ID**.

From **App settings → Basic**:
- **App secret**: click **Show**, then copy it to **App secret**.

Then press **Test connection**, type your own number, and press **Send me a test message**.

✅ You should see a WhatsApp message arrive on your phone.

> With the test number you must first add your phone under **API Setup → "To" → Manage phone number list**.

### Step 4.3: Connect the webhook (so customer messages reach the agent)
1. The wizard shows a **Callback URL** (like `https://…/webhook/whatsapp`) and a **Verify token**. Each has a **Copy** button.
   - If the URL says `localhost`, the agent isn't online yet. Do **Part 6** first, or run **`run.bat online`**.
2. In Meta: **WhatsApp → Configuration → Webhook → Edit**, paste both, and press **Verify and save**.
3. Under **Webhook fields**, click **Manage** and **Subscribe** to **messages**.

✅ Send "السلام عليكم" to your business number from another phone. The agent replies within seconds.

### Step 4.4: Message templates
WhatsApp only allows free-form messages within **24 hours** of the customer's last message. Later messages, such as delivery updates, review requests and **payment confirmations sent to you**, need Meta-approved templates.
- In the wizard press **Create missing templates**. Meta usually approves them within minutes to a day. Press **Check status** to follow.

### Step 4.5: Permanent token (before real customers)
1. Go to **business.facebook.com → Settings → Users → System users → Add**, with the **Admin** role.
2. Click **Add assets**, choose your app, and give full control.
3. Click **Generate token**, choose your app, and tick `whatsapp_business_messaging` and `whatsapp_business_management`. Set the expiry to **Never**.
4. Paste the new token into the wizard, replacing the temporary one.

### Step 4.6: Owner alerts on WhatsApp too (optional)
In the wizard's **Alerts** step, put your **personal** WhatsApp number in international format without `+` (e.g. `201001234567`). Send the business number any message once a day (e.g. `ملخص`) so the ✅/❌ buttons can be sent without a template.

---

## Part 5 · Bosta courier (optional)
1. Log in to **business.bosta.co** → **Settings → API integration → Create API key**, and copy it.
2. In the wizard: **Courier → Bosta**, paste the key, and press **Test key**.
3. Press **Generate** next to *Webhook secret*, then copy the **Webhook URL** and the secret.
4. In Bosta: **Settings → Webhooks → Add**, paste the URL, and put the secret in the **Authorization header** field.

✅ Confirmed orders now create real Bosta shipments. Delivery updates come back automatically, and customers only get the important ones: out for delivery, delivered, failed attempt.

> No Bosta? Choose **My own delivery person** and mark parcels delivered or refused from the dashboard.

---

## Part 6 · Put it online 24/7

On your PC, the agent stops when the PC sleeps or `run.bat` is closed. For real customers, run it on a cloud server. **Render** takes about 15 minutes and costs about $7 a month.

1. Create a free **GitHub** account if you don't have one, then open **https://github.com/MahmoudJimmey/Ta2keed** and click **Fork** (top right). This gives you your own copy.
2. Go to **https://render.com** and sign up **with GitHub**.
3. Click **New → Blueprint**, choose your **Ta2keed** fork, and click **Apply**. Render reads `render.yaml` and sets up everything: the Frankfurt region, a disk for your data, a generated password and an encryption key.
4. Add a payment card. The **Starter** plan is needed so your data disk survives restarts.
5. Wait about 5 minutes until it says **Live**. Copy your address, e.g. `https://ta2keed-xxxx.onrender.com`.
6. In Render: open the service → **Environment**, and copy the value of **ADMIN_PASSWORD**.
7. Open `https://<your-address>/setup`, log in with that password, then set your own password in **Owner login**.
8. Do Parts 2 to 5 again on this online copy. The webhook URLs are now correct automatically.
9. **Keep a copy of `TA2KEED_SECRET_KEY`** (also under Environment) somewhere safe, e.g. your password manager. It unlocks your saved API keys.

✅ Open `https://<your-address>/health` and you should see `"ok":true`. Your agent now works with your computer off.

> **Backups:** once a week, open `https://<your-address>/api/admin/backup` while logged in. It downloads a zip of all your orders and settings.
>
> **Testing only, without paying:** run **`run.bat online`** on your PC. It gives you a temporary public link (it changes on every run). Fine for trying WhatsApp, but not for real customers.

---

## Part 7 · Everyday use

### When a "transfer to confirm" arrives
A customer paid a deposit, and the screenshot passed the automatic checks. **The order is on hold until you answer.**
1. Open your **bank / InstaPay / Vodafone Cash app**. Don't rely on the screenshot.
2. Look for the **same amount** and the **same reference number** shown in the message.
3. Found it: tap **✅ وصل**. The order ships and the customer gets the tracking number automatically.
   Not there: tap **❌ موصلش**. The order stays on hold and the customer is asked to check.
4. You can also reply `تم 1234` or `لا 1234` (the 4-digit code in the message), or use the **Payments to confirm** card on the dashboard.

If you don't answer, you're reminded after 30 minutes and again after 3 hours.

### What else comes to you
- 🚨 **Instant alerts:** refused or returned parcel, fake receipt, bad rating, a customer asking to reschedule.
- 📊 **Daily summary** at 21:00 (change it in *Alerts*): orders, revenue, shipments, refusals, deposits.
- On WhatsApp you can message the business number: `ملخص` (summary), `شحنات` (shipments), `عربون` (deposits).

### Changing anything later
Open **/setup** (the **Settings** tab on the dashboard). Changes apply immediately.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Double-clicking `run.bat` flashes and closes | Right-click inside the folder → **Open in Terminal**, type `.\run.bat`, press Enter, and read the message. |
| "Python is not installed" but I installed it | Reinstall Python and **tick "Add python.exe to PATH"**. Then restart the PC. |
| The page says "can't be reached" | The black window is closed. Double-click `run.bat` again. |
| Asked for a password I never set (online) | Render → your service → **Environment** → `ADMIN_PASSWORD`. |
| Too many wrong passwords | Wait 15 minutes (brute-force protection). |
| WhatsApp "Verify and save" fails | The agent must be online (Part 6 or `run.bat online`), and the Verify token must be copied exactly. |
| Customers message but the agent doesn't answer | Meta → Webhook fields → **messages** must be **Subscribed**. The token may have expired (Step 4.5). |
| Delivery updates / payment questions don't arrive on WhatsApp | Templates not approved yet. Press **Check status** (Step 4.4). Meanwhile they reach Telegram and the dashboard. |
| Telegram bot silent | The black window or server must be running. Send `/owner <code>` again. |
| Saved API keys show as "not set" after moving servers | The encryption key changed. Set the old `TA2KEED_SECRET_KEY` again, or re-enter the keys. |
| Start over with the demo data | Dashboard → **Reset** (only shown in demo mode). It deletes all orders and chats but keeps your settings. Take a backup first if you have real data. |

---

## ملخص سريع بالعربي

1. نزّل Python من python.org، ووانت بتسطّبه **علّم على "Add python.exe to PATH"**.
2. من صفحة GitHub: **Code ← Download ZIP**، وبعدها فك الضغط (Extract All).
3. دبل كليك على **run.bat** وسيب الشباك الأسود مفتوح. هيفتحلك معالج الإعداد لوحده.
4. اكتب بيانات المحل، حساب InstaPay أو فودافون كاش **بالظبط**، المنتجات، ومصاريف الشحن.
5. تيليجرام: ابعت `/newbot` لـ **@BotFather** ← انسخ التوكن في خطوة Alerts ← ابعت للبوت `/owner` والكود اللي ظاهر.
6. لما تجيلك رسالة **"تأكيد تحويل"**: افتح تطبيق البنك واتأكد إن نفس المبلغ ونفس رقم العملية وصلوا فعلاً، وبعدين اضغط **✅ وصل** أو **❌ موصلش**. الأوردر مش بيتشحن غير بعد ردك.
7. عشان يشتغل من غير الكمبيوتر: اعمل Fork على GitHub ← Render.com ← New Blueprint (حوالي 7 دولار في الشهر). التفاصيل في الجزء 6.
