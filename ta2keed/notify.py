"""Owner notifications + daily digest (Telegram to the shop owner, optional)."""
from __future__ import annotations

import json

import httpx

from . import db, impact
from .config import settings

_last_event_id = {"v": 0}


def digest_text() -> str:
    m = impact.measured()
    pending = db.q("SELECT id, customer_name, total FROM orders WHERE status='awaiting_deposit'")
    lines = ["📊 ملخص اليوم — Ta2keed",
             f"أوردرات مؤكدة: {m['orders_confirmed']} ({m['revenue_confirmed_egp']:,} ج)",
             f"اتشحنت أوتوماتيك: {m['orders_auto_shipped']}",
             f"أوردرات خطرة اتوقفت قبل الشحن: {m['risky_orders_stopped_before_shipping']} "
             f"(وفرنا {m['shipping_loss_avoided_egp']:,} ج شحن ومرتجع)",
             f"عرابين: {m['deposits_collected']} ({m['deposit_cash_egp']:,} ج) — إيصالات مزورة اتمسكت: {m['fraud_receipts_blocked']}",
             f"Upsell: {m['upsells_accepted']}/{m['upsells_offered']} (+{m['upsell_revenue_egp']:,} ج)",
             f"أوردرات بعد مواعيد العمل: {m['after_hours_orders']}"]
    if pending:
        lines.append("⏳ مستني عربون: " + "، ".join(f"{p['id']} {p['customer_name']} ({p['total']} ج)" for p in pending))
    return "\n".join(lines)


def owner_command(text: str) -> str:
    cmd = text.split()[0].lower()
    if cmd in ("/digest", "/today"):
        return digest_text()
    if cmd == "/pending":
        rows = db.q("SELECT id, customer_name, total, risk_score FROM orders WHERE status='awaiting_deposit'")
        return "\n".join(f"{r['id']} — {r['customer_name']} — {r['total']} ج — risk {r['risk_score']}" for r in rows) or "مفيش"
    return "/digest — ملخص اليوم\n/pending — أوردرات مستنية عربون"


async def send_owner(text: str) -> None:
    if not (settings.telegram_bot_token and settings.owner_telegram_chat_id):
        return
    async with httpx.AsyncClient(timeout=20) as c:
        await c.post(f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                     json={"chat_id": settings.owner_telegram_chat_id, "text": text})


async def maybe_notify_owner(channel: str, user_id: str) -> None:
    """Push only the events an owner cares about: fraud and shipped high-value orders."""
    rows = db.q("SELECT * FROM events WHERE id>? ORDER BY id", (_last_event_id["v"],))
    for e in rows:
        _last_event_id["v"] = e["id"]
        data = json.loads(e["data"] or "{}")
        if e["type"] == "deposit_checked" and data.get("fraud"):
            await send_owner(f"⚠️ إيصال مشبوه على أوردر {e['order_id']} ({data.get('reason')}) — الأوردر متوقف.")
        elif e["type"] == "shipment_created":
            await send_owner(f"🚚 {e['order_id']} اتشحن — {data.get('tracking')}")
