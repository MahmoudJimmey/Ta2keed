"""Delivery tracking: courier status updates -> order state, customer history, and notifications.

Policy (store.json -> notifications):
  * EVERY courier update is recorded and shown on the owner dashboard.
  * The CUSTOMER is only messaged on highlights (default: out for delivery, delivered, failed attempt).
    "Picked up", "at hub", "in transit"... stay internal — no spam.
  * The OWNER gets an instant alert only for problems (refused, failed attempt, returned) and sees
    the rest in the daily digest.
"""
from __future__ import annotations

import json
import time

from . import db, outbound
from .config import store

# canonical statuses (happy chain first)
CHAIN = ["created", "picked_up", "in_transit", "out_for_delivery", "delivered"]
FINAL = {"delivered", "refused", "returned", "cancelled", "lost"}
ALL = set(CHAIN) | FINAL | {"delivery_failed"}

LABEL_AR = {
    "created": "اتسجل عند شركة الشحن", "picked_up": "المندوب استلمه من المحل", "in_transit": "في الطريق",
    "out_for_delivery": "خرج مع المندوب للتوصيل", "delivered": "اتسلم", "delivery_failed": "محاولة توصيل فشلت",
    "refused": "العميل رفض الاستلام", "returned": "رجع للمحل", "cancelled": "اتلغى", "lost": "مفقود",
}

# Bosta webhook `state` codes -> canonical. Based on Bosta's published delivery states;
# verify against your Bosta dashboard (Settings -> Webhooks) before going live.
BOSTA_STATES = {
    10: "created", 11: "created", 20: "created",
    21: "picked_up", 24: "in_transit", 30: "in_transit",
    41: "out_for_delivery", 45: "delivered", 46: "returned", 47: "delivery_failed",
    48: "cancelled", 49: "cancelled", 60: "returned", 100: "lost", 101: "lost",
}
ALIASES = {
    "pickup_requested": "created", "picked": "picked_up", "pickedup": "picked_up", "received_at_warehouse": "in_transit",
    "at_hub": "in_transit", "transit": "in_transit", "on_the_way": "out_for_delivery", "ofd": "out_for_delivery",
    "out for delivery": "out_for_delivery", "exception": "delivery_failed", "failed": "delivery_failed",
    "failed_attempt": "delivery_failed", "rejected": "refused", "customer_refused": "refused",
    "returned_to_business": "returned", "rto": "returned", "canceled": "cancelled", "terminated": "cancelled",
}


def normalize_status(raw) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)) or (isinstance(raw, str) and raw.strip().isdigit()):
        return BOSTA_STATES.get(int(raw))
    s = str(raw).strip().lower().replace("-", "_")
    s = ALIASES.get(s, ALIASES.get(s.replace("_", " "), s))
    return s if s in ALL else None


def find_order(order_id: str | None = None, tracking: str | None = None) -> dict | None:
    if order_id:
        o = db.one("SELECT * FROM orders WHERE id=?", (order_id,))
        if o:
            return o
    if tracking:
        return db.one("SELECT * FROM orders WHERE tracking=?", (str(tracking),))
    return None


def _cod(order: dict) -> int:
    return int(order["total"] - (order.get("deposit_paid") or 0))


def customer_text(kind: str, order: dict) -> str:
    name = (order.get("customer_name") or "").split()[0] if order.get("customer_name") else ""
    if kind == "out_for_delivery":
        return (f"🚚 أوردرك {order['id']} خرج مع المندوب النهارده!\nجهزي {_cod(order):,} ج كاش 💵 "
                "ولو مش هتكوني موجودة ردي هنا ونغيرلك الميعاد.")
    if kind == "delivered":
        return f"🎉 أوردرك {order['id']} وصل يا {name}! نتمنى يعجبك 💕 لو في أي حاجة إحنا هنا."
    if kind == "delivery_failed":
        return ("المندوب حاول يوصلك النهارده ومقدرش 🙏\nتحبي نبعته إمتى؟ "
                "(مثلاً: بكرة الصبح / السبت بعد 5) أو ابعتي رقم تاني للتواصل.")
    return ""


def template_params(kind: str, order: dict) -> list[str]:
    name = (order.get("customer_name") or "").split()[0] if order.get("customer_name") else "عميلتنا"
    if kind == "out_for_delivery":
        return [name, order["id"], f"{_cod(order):,}"]
    if kind in ("delivered", "delivery_failed"):
        return [name, order["id"]]
    return [name]


def apply_update(order: dict, raw_status, *, reason: str | None = None, source: str = "courier",
                 cod_collected: int | None = None) -> dict:
    status = normalize_status(raw_status)
    if not status:
        return {"ok": False, "error": f"unknown status {raw_status!r}"}
    prev = order.get("delivery_status")
    if prev == status:
        return {"ok": True, "duplicate": True, "status": status}
    if prev in FINAL and status not in ("returned",):  # ignore late/out-of-order webhooks after a final state
        return {"ok": True, "ignored": True, "status": status, "reason": f"already {prev}"}

    now = time.time()
    fields = {"delivery_status": status, "delivery_updated_at": now}
    if status == "delivered":
        fields.update(status="delivered", delivered_at=now, cod_collected=cod_collected if cod_collected is not None else _cod(order))
    elif status in ("refused", "returned", "cancelled", "lost"):
        fields["status"] = status
    sets = ", ".join(f"{k}=?" for k in fields)
    db.x(f"UPDATE orders SET {sets}, updated_at=? WHERE id=?", (*fields.values(), now, order["id"]))

    # customer history feeds the risk score next time
    phone = order.get("customer_phone")
    if phone and status == "delivered":
        db.x("UPDATE customers SET delivered=delivered+1 WHERE phone=?", (phone,))
    elif phone and (status == "refused" or (status == "returned" and prev != "refused")):
        db.x("UPDATE customers SET refused=refused+1 WHERE phone=?", (phone,))

    cfg = store().get("notifications", {})
    highlight = status in cfg.get("customer_highlights", ["out_for_delivery", "delivered", "delivery_failed"])
    db.log_event(order["conv_id"], "delivery_update",
                 {"status": status, "prev": prev, "reason": reason, "source": source, "customer_notified": highlight},
                 order["id"])

    order = db.one("SELECT * FROM orders WHERE id=?", (order["id"],))
    result = {"ok": True, "status": status, "customer_notified": False, "owner_alerted": False}

    if highlight and order.get("conv_id"):
        outbound.send_customer(order["conv_id"], customer_text(status, order), status, order_id=order["id"],
                               template_params=template_params(status, order))
        result["customer_notified"] = True
        if status == "delivery_failed":
            _expect_reply(order["conv_id"], {"kind": "reschedule", "order_id": order["id"]})

    if status in cfg.get("owner_instant_alerts", ["refused", "delivery_failed", "returned"]):
        msg = {"refused": f"⛔ {order['id']} ({order['customer_name']}) رفض الاستلام. السبب: {reason or 'غير محدد'} — "
                          f"اتسجل في تاريخ العميل وهيتطلب منه عربون المرة الجاية.",
               "returned": f"↩️ {order['id']} راجع للمحل — تابعي استلام البضاعة من شركة الشحن.",
               "delivery_failed": f"⚠️ {order['id']} ({order['customer_name']} {order['customer_phone']}) محاولة توصيل فشلت"
                                  f"{' — ' + reason if reason else ''}. سألنا العميل عن ميعاد جديد."}.get(status)
        if msg:
            outbound.send_owner(msg, status, order_id=order["id"])
            result["owner_alerted"] = True

    if status == "delivered":
        from . import aftercare
        aftercare.schedule_after_delivery(order)
    return result


def advance(order: dict) -> dict:
    """Mock courier: move the order one step along the happy chain (for demos without a real courier)."""
    cur = order.get("delivery_status") or "created"
    if cur in FINAL:
        return {"ok": False, "error": f"order already {cur}"}
    if cur == "delivery_failed":
        nxt = "out_for_delivery"
    else:
        nxt = CHAIN[min(CHAIN.index(cur) + 1, len(CHAIN) - 1)] if cur in CHAIN else "picked_up"
    return apply_update(order, nxt, source="mock-courier")


def _expect_reply(conv_id: int, post: dict) -> None:
    """Mark the conversation so the customer's next message is routed to aftercare (rating/reschedule/reorder)."""
    conv = db.conversation_by_id(conv_id)
    if not conv or conv["state"] not in ("CONFIRMED",):
        return
    draft = json.loads(conv["draft"] or "{}")
    draft["post"] = post
    db.x("UPDATE conversations SET draft=?, updated_at=? WHERE id=?", (json.dumps(draft, ensure_ascii=False), time.time(), conv_id))


def parse_bosta(payload: dict) -> dict:
    """Bosta webhook body -> {tracking, order_id, status, reason, cod}."""
    d = payload.get("data", payload)
    return {
        "tracking": d.get("trackingNumber") or d.get("tracking_number"),
        "order_id": d.get("businessReference") or d.get("business_reference"),
        "status": d.get("state") if d.get("state") is not None else d.get("status"),
        "reason": d.get("exceptionReason") or d.get("exception_reason") or d.get("reason"),
        "cod": d.get("cod") or d.get("collectedAmount"),
    }
