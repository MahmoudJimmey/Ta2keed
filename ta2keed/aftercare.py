"""After-delivery care: rating request -> handle rating (thank / recover), reorder offer, reschedule replies.

Timeline after `delivered` (store.json -> notifications):
  +review_after_hours   ask for a 1-5 rating
  +reorder_after_days   personalised reorder offer with a one-time discount code
Low ratings (<=3) alert the owner immediately and the customer gets an apology + fix offer.
"""
from __future__ import annotations

import json
import random
import re
import string
import time

from . import db, nlu, outbound
from .config import product, store

AR_NUM = {"واحد": 1, "اتنين": 2, "تلاته": 3, "اربعه": 4, "خمسه": 5}


def _cfg() -> dict:
    return store().get("notifications", {})


def schedule(order: dict, kind: str, due_at: float, payload: dict | None = None) -> None:
    if db.one("SELECT id FROM scheduled WHERE order_id=? AND kind=? AND status='pending'", (order["id"], kind)):
        return
    conv = db.conversation_by_id(order["conv_id"]) if order.get("conv_id") else None
    db.x("INSERT INTO scheduled(order_id,conv_id,channel,user_id,kind,payload,due_at,status) VALUES(?,?,?,?,?,?,?,?)",
         (order["id"], order.get("conv_id"), conv["channel"] if conv else None, conv["user_id"] if conv else None,
          kind, json.dumps(payload or {}, ensure_ascii=False), due_at, "pending"))


def schedule_after_delivery(order: dict) -> None:
    now = time.time()
    schedule(order, "review", now + _cfg().get("review_after_hours", 24) * 3600)
    schedule(order, "reorder", now + _cfg().get("reorder_after_days", 14) * 86400)


def _first_name(order: dict) -> str:
    return (order.get("customer_name") or "").split()[0] if order.get("customer_name") else ""


def _code(order: dict) -> str:
    rng = random.Random(order["id"])
    return "NOUR" + "".join(rng.choices(string.ascii_uppercase + string.digits, k=5))


def _reorder_suggestion(order: dict) -> dict | None:
    items = json.loads(order["items"]) if isinstance(order["items"], str) else order["items"]
    have = {i["sku"] for i in items}
    for it in items:
        up = (product(it["sku"]) or {}).get("upsell")
        if up and up["sku"] not in have:
            return product(up["sku"])
    for p in store()["products"]:
        if p["sku"] not in have:
            return p
    return None


def message_for(kind: str, order: dict) -> tuple[str, list[str]]:
    name = _first_name(order)
    if kind == "review":
        return (f"أهلاً يا {name} 🌸 الأوردر {order['id']} عجبك؟\nقيّمينا من 1 لـ 5 ⭐ (رد برقم بس) — رأيك بيفرق معانا جداً.",
                [name, order["id"]])
    if kind == "reorder":
        p = _reorder_suggestion(order)
        disc = int(_cfg().get("reorder_discount", 0.10) * 100)
        pick = f" — عندنا {p['name_ar']} هيليق جداً مع اللي اشتريتيه" if p else ""
        return (f"وحشتينا يا {name} 💕{pick}.\nخصم {disc}% على طلبك الجاي بكود {_code(order)} لمدة أسبوع. "
                "ابعتيلي اسم المنتج وأنا أسجلهولك 🛍️", [name, f"{disc}%", _code(order)])
    return "", []


def run_due(now: float | None = None) -> list[dict]:
    """Send every scheduled message whose time has come. Called by the scheduler loop (and the demo fast-forward)."""
    now = now or time.time()
    sent = []
    for job in db.q("SELECT * FROM scheduled WHERE status='pending' AND due_at<=? ORDER BY due_at", (now,)):
        order = db.one("SELECT * FROM orders WHERE id=?", (job["order_id"],))
        if not order or order["status"] != "delivered" or not order.get("conv_id"):
            db.x("UPDATE scheduled SET status='skipped', sent_at=? WHERE id=?", (now, job["id"]))
            continue
        if job["kind"] == "review" and order.get("rating"):
            db.x("UPDATE scheduled SET status='skipped', sent_at=? WHERE id=?", (now, job["id"]))
            continue
        text, params = message_for(job["kind"], order)
        res = outbound.send_customer(order["conv_id"], text, job["kind"], order_id=order["id"], template_params=params)
        db.x("UPDATE scheduled SET status=?, sent_at=? WHERE id=?", ("sent" if res["sent"] else "failed", now, job["id"]))
        post = {"kind": "rating" if job["kind"] == "review" else "reorder", "order_id": order["id"]}
        from .delivery import _expect_reply
        _expect_reply(order["conv_id"], post)
        sent.append({"order_id": order["id"], "kind": job["kind"], **res})
    return sent


def fast_forward(order_id: str | None = None, kind: str | None = None) -> list[dict]:
    """Demo helper: make pending follow-ups (optionally for one order / one kind) due now and send them."""
    sql, args = "UPDATE scheduled SET due_at=0 WHERE status='pending'", []
    if order_id:
        sql += " AND order_id=?"
        args.append(order_id)
    if kind:
        sql += " AND kind=?"
        args.append(kind)
    db.x(sql, tuple(args))
    return run_due()


# ------------------------------------------------------------------ customer replies after delivery

def parse_rating(text: str) -> int | None:
    t = nlu.normalize(text)
    m = re.search(r"(?<!\d)([1-5])(?!\d)", t)
    if m:
        return int(m.group(1))
    stars = text.count("⭐") or text.count("🌟")
    if 1 <= stars <= 5:
        return stars
    for w, n in AR_NUM.items():
        if re.search(rf"(?<![\u0600-\u06FF]){w}(?![\u0600-\u06FF])", t):
            return n
    return None


def handle_reply(conv: dict, text: str) -> list[str] | None:
    """Return replies if this message answers a post-delivery prompt, else None (normal flow continues)."""
    post = conv["draft"].get("post")
    if not post or not text:
        return None
    order = db.one("SELECT * FROM orders WHERE id=?", (post["order_id"],))
    if not order:
        conv["draft"].pop("post", None)
        return None
    kind = post["kind"]

    if kind == "rating":
        r = parse_rating(text)
        if r is None:
            return None
        conv["draft"].pop("post", None)
        db.x("UPDATE orders SET rating=? WHERE id=?", (r, order["id"]))
        db.log_event(conv["id"], "rating", {"rating": r, "comment": text}, order["id"])
        if r >= 4:
            return [f"شكراً جداً يا {_first_name(order)} 😍 تقييمك {'⭐' * r} فرّحنا!\n"
                    "لو تحبي تشاركي صورة بالحاجة على إنستجرام ومنشنينا هنبعتلك هدية في الأوردر الجاي 🎁"]
        outbound.send_owner(f"😟 تقييم {r}/5 على {order['id']} من {order['customer_name']} ({order['customer_phone']}): «{text}» "
                            "— كلميها النهارده.", "low_rating", order_id=order["id"])
        return ["آسفين جداً إن التجربة ما كانتش على قد توقعك 🙏 وصلت ملاحظتك للإدارة وهيكلموكي النهارده. "
                "لو في مشكلة في المقاس أو المنتج الاستبدال علينا."]

    if kind == "reschedule":
        conv["draft"].pop("post", None)
        db.log_event(conv["id"], "reschedule_requested", {"text": text}, order["id"])
        outbound.send_owner(f"📅 {order['id']} العميل عايز ميعاد توصيل جديد: «{text}» — بلغي شركة الشحن.",
                            "reschedule_requested", order_id=order["id"])
        return ["تمام ✅ بلغنا شركة الشحن بالميعاد الجديد، والمندوب هيكلمك قبلها."]

    if kind == "reorder":
        conv["draft"].pop("post", None)  # the message itself is a new order -> normal flow handles it
        db.log_event(conv["id"], "reorder_reply", {"text": text}, order["id"])
        return None
    return None
