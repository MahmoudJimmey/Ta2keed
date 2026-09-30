"""Owner-facing reporting: daily summary (digest), instant alerts, and owner commands.

The digest is pushed automatically at store.json -> notifications.digest_time (Cairo local time)
to the owner's Telegram and/or WhatsApp, and is always available at /api/digest and on the dashboard.
"""
from __future__ import annotations

import datetime as dt
import json

from . import db, outbound

_last_event_id = {"v": 0}


def _day_bounds(day: dt.date | None = None) -> tuple[float, float]:
    day = day or dt.date.today()
    start = dt.datetime.combine(day, dt.time.min).timestamp()
    return start, start + 86400


def day_stats(day: dt.date | None = None) -> dict:
    a, b = _day_bounds(day)
    new = db.q("SELECT * FROM orders WHERE created_at>=? AND created_at<?", (a, b))
    ev = db.q("SELECT * FROM events WHERE ts>=? AND ts<?", (a, b))

    def evs(t, pred=lambda d: True):
        return [e for e in ev if e["type"] == t and pred(json.loads(e["data"] or "{}"))]

    def upd(s):
        return {e["order_id"] for e in evs("delivery_update", lambda d: d.get("status") == s)}

    delivered_ids, refused_ids = upd("delivered"), upd("refused") | upd("returned")
    delivered = [db.one("SELECT * FROM orders WHERE id=?", (i,)) for i in delivered_ids]
    ratings = [json.loads(e["data"])["rating"] for e in evs("rating")]
    confirmed = [o for o in new if o["status"] not in ("cancelled", "awaiting_deposit")]
    return {
        "date": (day or dt.date.today()).isoformat(),
        "new_orders": len(new),
        "confirmed": len(confirmed),
        "confirmed_value": sum(o["total"] for o in confirmed),
        "auto_shipped": len(evs("shipment_created")),
        "cancelled_before_shipping": sum(1 for o in new if o["status"] == "cancelled"),
        "awaiting_deposit": db.q("SELECT id, customer_name, total FROM orders WHERE status='awaiting_deposit'"),
        "deposits": len(evs("deposit_checked", lambda d: d.get("ok"))),
        "fraud_blocked": len(evs("deposit_checked", lambda d: d.get("fraud"))),
        "delivered": len(delivered_ids),
        "cash_collected": sum((o or {}).get("cod_collected") or 0 for o in delivered),
        "refused": len(refused_ids),
        "failed_attempts": len(upd("delivery_failed")),
        "out_for_delivery_now": db.one("SELECT COUNT(*) n FROM orders WHERE delivery_status='out_for_delivery'")["n"],
        "in_transit_now": db.one("SELECT COUNT(*) n FROM orders WHERE delivery_status IN ('created','picked_up','in_transit')")["n"],
        "upsells": len(evs("upsell_accepted")),
        "upsell_value": sum(json.loads(e["data"]).get("price", 0) for e in evs("upsell_accepted")),
        "ratings": ratings,
        "avg_rating": round(sum(ratings) / len(ratings), 1) if ratings else None,
        "reorders": sum(1 for o in new if o.get("source") == "reorder"),
        "customer_msgs_sent": len(evs("customer_notified")),
        "after_hours": sum(1 for o in new if o["after_hours"]),
    }


def digest_text(day: dt.date | None = None) -> str:
    s = day_stats(day)
    lines = [f"📊 ملخص اليوم — {s['date']}",
             "",
             f"🧾 أوردرات جديدة: {s['new_orders']} — اتأكد {s['confirmed']} بقيمة {s['confirmed_value']:,} ج",
             f"🚚 اتشحن أوتوماتيك: {s['auto_shipped']} · مع المندوب دلوقتي: {s['out_for_delivery_now']} · "
             f"في الطريق: {s['in_transit_now']}",
             f"✅ اتسلم: {s['delivered']} — كاش متحصل {s['cash_collected']:,} ج",
             f"⛔ رفض/مرتجع: {s['refused']} · محاولات فاشلة: {s['failed_attempts']}",
             f"💳 عرابين: {s['deposits']} · إيصالات مزورة اتمسكت: {s['fraud_blocked']} · "
             f"اتلغى قبل الشحن: {s['cancelled_before_shipping']}",
             f"🎁 Upsell: {s['upsells']} (+{s['upsell_value']:,} ج) · أوردرات متكررة: {s['reorders']}"]
    if s["avg_rating"] is not None:
        lines.append(f"⭐ متوسط التقييم: {s['avg_rating']} من {len(s['ratings'])} تقييم")
    if s["after_hours"]:
        lines.append(f"🌙 أوردرات بعد مواعيد العمل: {s['after_hours']}")
    if s["awaiting_deposit"]:
        lines.append("⏳ مستني عربون: " + "، ".join(f"{p['id']} {p['customer_name']} ({p['total']} ج)"
                                                 for p in s["awaiting_deposit"]))
    lines += ["", f"📨 رسائل اتبعتت للعملاء أوتوماتيك: {s['customer_msgs_sent']} (المهم بس)"]
    return "\n".join(lines)


def send_digest(day: dt.date | None = None) -> dict:
    s = day_stats(day)
    text = digest_text(day)
    params = [s["date"], str(s["confirmed"]), f"{s['confirmed_value']:,}", str(s["delivered"]),
              f"{s['cash_collected']:,}", str(s["refused"])]
    res = outbound.send_owner(text, "digest", template_params=params)
    db.log_event(None, "digest_sent", {"date": s["date"], "via": res["via"]})
    return {"text": text, **res}


def owner_command(text: str) -> str:
    cmd = text.strip().split()[0].lower() if text and text.strip() else ""
    if cmd in ("/digest", "/today", "/summary", "ملخص"):
        return digest_text()
    if cmd in ("/pending", "عربون"):
        rows = db.q("SELECT id, customer_name, total, risk_score FROM orders WHERE status='awaiting_deposit'")
        return "\n".join(f"{r['id']} — {r['customer_name']} — {r['total']} ج — risk {r['risk_score']}" for r in rows) or "مفيش"
    if cmd in ("/deliveries", "/track", "شحنات"):
        from .delivery import LABEL_AR
        rows = db.q("SELECT id, customer_name, delivery_status FROM orders WHERE delivery_status IS NOT NULL "
                    "AND delivery_status NOT IN ('delivered','returned','cancelled','refused') ORDER BY created_at")
        return "\n".join(f"{r['id']} — {r['customer_name']} — {LABEL_AR.get(r['delivery_status'], r['delivery_status'])}"
                         for r in rows) or "كل الشحنات اتقفلت ✅"
    return "/digest — ملخص اليوم\n/deliveries — الشحنات اللي لسه في الطريق\n/pending — أوردرات مستنية عربون"


async def maybe_notify_owner(channel: str, user_id: str) -> None:
    """Instant owner alert only for fraud during chats (delivery problems alert from delivery.py; rest -> digest)."""
    import asyncio
    rows = db.q("SELECT * FROM events WHERE id>? ORDER BY id", (_last_event_id["v"],))
    for e in rows:
        _last_event_id["v"] = e["id"]
        data = json.loads(e["data"] or "{}")
        if e["type"] == "deposit_checked" and data.get("fraud"):
            await asyncio.to_thread(outbound.send_owner,
                                    f"⚠️ إيصال مشبوه على أوردر {e['order_id']} ({data.get('reason')}) — الأوردر متوقف ومش هيتشحن.",
                                    "fraud", order_id=e["order_id"])
