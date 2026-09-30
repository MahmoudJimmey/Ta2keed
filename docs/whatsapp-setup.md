# WhatsApp setup (Cloud API)

Ta2keed talks to customers on WhatsApp through Meta's official **WhatsApp Cloud API**. It also sends the shop owner alerts and the daily summary on WhatsApp.

## 1. Create the app (about 15 minutes)

1. Go to developers.facebook.com → **My Apps → Create app → Business**, then add the **WhatsApp** product.
2. Under **WhatsApp → API Setup** you get a free **test number**, a temporary **access token** and your **Phone number ID**. Add your own phone (and a second phone to play the customer) as recipients.
3. For a permanent token: Business Settings → System users → add a user → generate a token with `whatsapp_business_messaging` and `whatsapp_business_management`.
4. **App secret:** App settings → Basic. Ta2keed uses it to verify that webhooks really come from Meta.

## 2. Expose the webhook

Meta needs a public HTTPS address. For a demo, a tunnel to your laptop is enough:

```bash
cloudflared tunnel --url http://localhost:8000      # or: ngrok http 8000
```

In **WhatsApp → Configuration → Webhook**:
- Callback URL: `https://<your-tunnel>/webhook/whatsapp`
- Verify token: the value of `WHATSAPP_VERIFY_TOKEN` (default `ta2keed-verify`)
- Subscribe to the **messages** field.

## 3. Configure `.env`

```
WHATSAPP_ACCESS_TOKEN=EAAG...
WHATSAPP_PHONE_NUMBER_ID=1234567890
WHATSAPP_VERIFY_TOKEN=ta2keed-verify
WHATSAPP_APP_SECRET=abc123...
OWNER_WHATSAPP=2010XXXXXXXX        # the owner's own WhatsApp (international format, no +)
```

Restart the server. `/health` should now show `whatsapp: true`.

## What the agent does on WhatsApp

| Who | What |
|---|---|
| Customer | Orders by text, voice note or photo (receipt screenshots). Button replies from templates work too. |
| Customer | Gets **only the delivery highlights**: out for delivery (with the exact cash to prepare), delivered, and a failed attempt (asks for a new time). "Picked up" and "in transit" updates stay on the dashboard. |
| Customer | 24 h after delivery: a 1–5 rating request. 14 days after: a reorder offer with a discount code. |
| Owner | Instant alerts only for problems: refused, returned, failed attempt, fake receipt, low rating, reschedule request. |
| Owner | The **daily summary** at `notifications.digest_time` (default 21:00). |
| Owner | Send `ملخص` / `/digest`, `شحنات` / `/deliveries` or `عربون` / `/pending` to the business number to get answers on demand. |

The agent also marks incoming messages as read, ignores duplicate webhook deliveries from Meta, and logs failed sends to the dashboard.

## The 24-hour rule and templates

WhatsApp only allows **free-text** messages within 24 h of the person's last message. Outside that window Ta2keed automatically sends a pre-approved **template** instead. Delivery updates often come 2–4 days after the chat, and follow-ups come 1–14 days after delivery, so these templates matter.

Create them in **WhatsApp Manager → Message templates**, language **Arabic (ar)**, category **Utility** (reorder: **Marketing**). The names must match `store.json → whatsapp_templates`:

| Template name | Category | Body (`{{n}}` = parameters in this order) |
|---|---|---|
| `ta2keed_out_for_delivery` | Utility | أهلاً {{1}} 🚚 أوردرك {{2}} خرج مع المندوب النهارده. جهزي {{3}} ج كاش. لو مش هتكوني موجودة ردي على الرسالة دي. |
| `ta2keed_delivered` | Utility | أوردرك {{2}} وصل يا {{1}} 🎉 نتمنى يعجبك! |
| `ta2keed_delivery_failed` | Utility | يا {{1}}، المندوب حاول يوصل أوردر {{2}} ومقدرش. ردي على الرسالة دي بالميعاد المناسب ليكي. |
| `ta2keed_review_request` | Utility | أهلاً {{1}} 🌸 أوردر {{2}} عجبك؟ قيّمينا من 1 لـ 5 برد على الرسالة دي. |
| `ta2keed_reorder_offer` | Marketing | وحشتينا يا {{1}} 💕 خصم {{2}} على طلبك الجاي بكود {{3}} لمدة أسبوع. |
| `ta2keed_owner_digest` | Utility | ملخص {{1}}: اتأكد {{2}} أوردر بقيمة {{3}} ج · اتسلم {{4}} · كاش {{5}} ج · رفض {{6}}. |
| `ta2keed_owner_alert` | Utility | تنبيه Ta2keed: {{1}} |

Tip: send any message to the business number from the owner's phone once a day (for example `ملخص`). That keeps the owner's 24 h window open, so the full summary arrives as normal text instead of the short template.

## Courier status updates

Connect your courier so delivery updates arrive automatically:

- **Bosta:** Dashboard → Settings → Webhooks → `https://<your-host>/webhook/bosta`. The shipment's `businessReference` is the Ta2keed order id, and the tracking number is matched too.
- **Any other courier or your own driver:** `POST /webhook/courier` with `{"order_id" | "tracking", "status", "reason"?, "cod_collected"?}`. Status may be `picked_up`, `in_transit`, `out_for_delivery`, `delivered`, `delivery_failed`, `refused` or `returned`.
- Protect both webhooks with `COURIER_WEBHOOK_SECRET` (the value the caller sends in the `Authorization` header).

Without a courier connection, the **next step ▸ / failed / refused** buttons on the dashboard act as the courier for demos.
