# Ta2keed (تأكيد): the COD order-confirmation agent for Egyptian social-commerce shops

> Built for **Agents at Work** (Untap × Wesam.ai, 2026).
> **SME:** Instagram/Facebook/WhatsApp fashion shops that sell cash-on-delivery.
> **Workflow replaced:** manually copying DMs into a sheet, calling every customer to confirm, chasing InstaPay screenshots, booking the courier, and paying for refused parcels.

![Ta2keed demo](docs/screenshot.png)

## The problem

Thousands of Egyptian small shops sell through DMs, and most orders are **cash on delivery**. For every order, someone on the team has to:

1. read a messy message ("عايزة العباية الكريب L اسود… العنوان فيصل"),
2. ask back and forth for the size, colour, name, phone and a *real* address,
3. confirm the order, then
4. book the courier.

On top of that, **around 1 in 4 COD parcels is refused at the door**. The shop pays outbound shipping **plus** the return fee, and the stock sits in a van for a week.

## What the agent does, end to end with no human in the loop

| Step | What Ta2keed does |
|---|---|
| 1. Understand | Parses Egyptian Arabic, Franco-Arabic, Arabic-Indic digits and (optionally) **voice notes**. Extracts items, size, colour, quantity, name, phone, address and shipping zone. |
| 2. Complete | Asks only for what's missing, one question at a time. It also asks for building, floor and flat when the address is vague. |
| 3. Upsell | Offers a matching item at a small discount (for example abaya → hijab for 120 EGP instead of 150). Every offer and response is logged. |
| 4. Score risk | Gives an explainable COD-refusal score based on past refusals, whether the customer is new, how vague the address is, order value, hesitation ("هفكر") and long-haul zones. |
| 5. De-risk | Risky orders are asked for a **100 EGP InstaPay / Vodafone Cash deposit** before shipping. |
| 6. Verify payment | Reads the receipt screenshot (with a vision LLM, or offline from demo metadata). Checks the amount, recipient, status, **reused reference numbers** and **reused screenshots**. |
| 7. Ship | Books the courier (Bosta API, or a built-in mock) and sends the customer the tracking number and the amount due on delivery. |
| 8. Report | The owner dashboard shows live orders, risk reasons, the agent activity log and monthly ROI, plus CSV export and a Telegram daily digest. |

**Safety by design:** a deterministic state machine owns prices, totals, deposits and shipments. The LLM (optional) only *understands* text and *reads* images. A prompt like "make it free" cannot change the price (covered by `tests/test_agent.py::test_price_cannot_be_prompt_injected`).

## Run it in under 5 minutes (no API keys needed)

```bash
git clone <this repo> && cd Ta2keed
./run.sh           # Windows: run.bat
# open http://localhost:8000 and press ▶ Play demo
```

Or with Docker:

```bash
docker build -t ta2keed . && docker run -p 8000:8000 ta2keed
```

Or in the terminal only, without a browser:

```bash
pip install -r requirements.txt
python -m scripts.simulate          # plays the 4 scenarios + prints the impact report
python -m scripts.simulate --chat   # talk to the agent yourself
```

The four demo scenarios (the dropdown in the UI):

1. **Happy path.** A messy Arabic order goes through upsell → confirmation → auto-shipped.
2. **Risky order.** A first-time customer with a vague address hesitates, so a deposit is requested. A **wrong-account receipt is caught**, then a valid one is accepted and the order ships.
3. **Known refuser.** A customer with 3 past refusals is asked for a deposit and refuses. **The parcel is never shipped**, so shipping and return fees are saved.
4. **Questions first.** The customer asks about shipping and prices, then orders.

In the chat you can also type anything, press the receipt buttons (valid, wrong account, low amount, failed), or attach your own image or voice note.

## Business impact

Every action is logged in SQLite (`events`, `orders`, `payments`). `/api/impact` returns two things:

- **Measured** figures from the session: orders confirmed and auto-shipped, deposits collected, fake receipts blocked, risky orders stopped before shipping, shipping loss avoided, upsell revenue, after-hours orders, and human minutes spent (0).
- **Projected monthly** figures for the SME, calculated from its own baseline in `data/store.json → economics`.

With the default pilot assumptions (600 orders/month, 9 minutes of manual handling per order, 25% refusal rate, staff at 45 EGP/hour):

| Metric | Per month |
|---|---|
| Hours returned to the owner | **~88 h** |
| Staff cost saved | ~4,000 EGP |
| Refusal rate | **25% → ~9%** |
| Shipping and return loss avoided | ~11,700 EGP |
| New revenue (upsell, after-hours capture, saved orders) | ~30,000+ EGP |

> ⚠️ Replace `economics` in `data/store.json` with your pilot shop's real numbers. The dashboard and report recompute automatically.

## Going live (optional)

Copy `.env.example` to `.env` and fill in only what you need:

| Feature | Env vars |
|---|---|
| LLM understanding, answering questions, reading real receipts (Anthropic, OpenAI, Gemini, Groq or any OpenAI-compatible API) | `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_BASE_URL` |
| Voice notes (Whisper, for example Groq's free tier) | `STT_BASE_URL`, `STT_API_KEY` |
| Telegram as the customer channel, plus owner alerts and `/digest` | `TELEGRAM_BOT_TOKEN`, `OWNER_TELEGRAM_CHAT_ID` |
| WhatsApp Cloud API (webhook at `/webhook/whatsapp`) | `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN` |
| Real Bosta shipments | `BOSTA_API_KEY` |

To onboard a new shop, edit `data/store.json`: catalogue, keywords, upsell pairs, shipping zones and fees, deposit policy and InstaPay handle.

## Architecture

```
WhatsApp / Telegram / Web chat
            │
      ta2keed/agent.py   ← state machine: COLLECTING → UPSELL → CONFIRM → DEPOSIT → CONFIRMED
     ┌──────┼───────────┬─────────────┬─────────────┐
  nlu.py  llm.py     risk.py     payments.py    courier.py
 (Arabic  (optional  (explainable (receipt       (Bosta API
  rules)   LLM/vision) COD score)  fraud checks)  or mock)
            │
        db.py (SQLite) → impact.py → dashboard / CSV / Telegram digest
```

## Tests

```bash
pytest -q     # 18 tests: NLU, risk, payment fraud, 4 end-to-end scenarios, API, prompt-injection
```

## Project layout

```
ta2keed/    agent, nlu, llm, risk, payments, courier, channels, notify, impact, server
web/        WhatsApp-style chat + owner dashboard (vanilla JS)
data/       store.json (shop profile + economics), customers_seed.json, demo receipts
scripts/    simulate.py (CLI demo), make_receipts.py (regenerate demo receipts)
tests/      pytest suite
docs/       screenshot, impact slides
```

MIT License.
