"""Owner payment confirmation: a human check that the money actually arrived.

Why: a screenshot proves nothing on its own. It can be AI-generated, edited, or a real receipt of an
OLD transfer. The automated checks in payments.py catch the obvious fakes. Every receipt that passes
them still waits for the owner, who confirms it in the bank / InstaPay app. Nothing ships before that.

Flow
  customer sends receipt → automated checks pass → payment 'pending_owner', order 'awaiting_owner_confirm'
  → owner gets the screenshot + details on Telegram (inline buttons) and/or WhatsApp (reply buttons,
    or an approved template with quick-reply buttons outside the 24 h window) and on the dashboard
  → ✅ received: deposit recorded, order shipped, customer told automatically
  → ❌ not received: receipt marked fraud, order held, customer asked to re-check (owner alerted)
  → no answer: reminders after policy.owner_confirm_reminders_min (default 30 and 180 minutes)

Only the owner's own Telegram chat / WhatsApp number / logged-in dashboard can decide.
"""
from __future__ import annotations

import json
import logging
import re
import secrets
import time
from pathlib import Path

import httpx

from . import db, outbound
from .config import data_dir, settings, store

log = logging.getLogger("ta2keed.payconfirm")
GRAPH = "https://graph.facebook.com/v21.0"

YES_WORDS = ("تم", "وصل", "وصلت", "اه", "ايوه", "yes", "ok", "approve", "نعم")
NO_WORDS = ("لا", "موصلش", "مجاش", "no", "reject", "مش واصل")


def enabled() -> bool:
    return bool(store()["policy"].get("owner_payment_confirmation", True))


def _receipts_dir() -> Path:
    d = data_dir() / "receipts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def image_path(check: dict) -> Path | None:
    if not check.get("image_file"):
        return None
    p = (_receipts_dir() / check["image_file"]).resolve()
    return p if p.parent == _receipts_dir().resolve() and p.exists() else None


def get(check_id: int) -> dict | None:
    return db.one("SELECT * FROM payment_checks WHERE id=?", (check_id,))


def pending_for_order(order_id: str) -> dict | None:
    return db.one("SELECT * FROM payment_checks WHERE order_id=? AND status='pending' ORDER BY id DESC", (order_id,))


def pending() -> list[dict]:
    rows = db.q("SELECT c.*, o.customer_name, o.customer_phone, o.total FROM payment_checks c "
                "JOIN orders o ON o.id=c.order_id WHERE c.status='pending' ORDER BY c.asked_at")
    for r in rows:
        r["info"] = json.loads(r["info"] or "{}")
        r["has_image"] = bool(image_path(r))
    return rows


# ------------------------------------------------------------------ start

def start(order: dict, conv_id: int, payment_id: int, info: dict, image: bytes | None, mime: str) -> dict:
    code = f"{secrets.randbelow(9000) + 1000}"
    fname = None
    if image:
        ext = {"image/jpeg": ".jpg", "image/webp": ".webp"}.get(mime, ".png")
        fname = f"{order['id']}-{payment_id}{ext}"
        f = _receipts_dir() / fname
        f.write_bytes(image)
        try:
            import os
            os.chmod(f, 0o600)
        except OSError:
            pass
    now = time.time()
    cid = db.x("INSERT INTO payment_checks(order_id,payment_id,conv_id,code,amount,reference,info,image_file,status,"
               "asked_at,reminders) VALUES(?,?,?,?,?,?,?,?,?,?,0)",
               (order["id"], payment_id, conv_id, code, int(float(info.get("amount") or 0)), info.get("reference"),
                json.dumps(info, ensure_ascii=False), fname, "pending", now))
    db.x("UPDATE payments SET status='pending_owner' WHERE id=?", (payment_id,))
    db.x("UPDATE orders SET status='awaiting_owner_confirm', updated_at=? WHERE id=?", (now, order["id"]))
    check = get(cid)
    via = ask_owner(check, order)
    db.log_event(conv_id, "payment_confirmation_requested", {"check_id": cid, "amount": check["amount"],
                                                             "reference": check["reference"], "via": via}, order["id"])
    return {"check_id": cid, "code": code, "via": via}


def owner_text(check: dict, order: dict, reminder: bool = False) -> str:
    info = json.loads(check["info"] or "{}") if isinstance(check.get("info"), str) else (check.get("info") or {})
    method = {"instapay": "InstaPay", "vodafone_cash": "فودافون كاش", "bank": "تحويل بنكي"}.get(info.get("method"), info.get("method") or "")
    lines = [("⏰ تذكير — " if reminder else "") + f"💳 تأكيد تحويل — أوردر {order['id']}",
             f"العميل: {order.get('customer_name', '')} ({order.get('customer_phone', '')})",
             f"المبلغ في الإيصال: {check['amount']:,} ج{(' · ' + method) if method else ''}",
             f"رقم العملية: {check.get('reference') or '—'}"]
    if info.get("datetime"):
        lines.append(f"وقت الإيصال: {info['datetime']}")
    if info.get("recipient"):
        lines.append(f"محول لـ: {info['recipient']}")
    lines += [f"إجمالي الأوردر: {order.get('total', 0):,} ج", "",
              "⚠️ افتحي تطبيق البنك / InstaPay واتأكدي إن المبلغ وصل فعلاً بنفس رقم العملية قبل ما توافقي.",
              "الأوردر مش هيتشحن غير بعد تأكيدك.", "",
              f"اضغطي الزرار، أو ردي: «تم {check['code']}» لو وصل — «لا {check['code']}» لو موصلش."]
    return "\n".join(lines)


def _tg_buttons(check_id: int) -> dict:
    return {"inline_keyboard": [[{"text": "✅ وصل", "callback_data": f"pay:{check_id}:yes"},
                                 {"text": "❌ موصلش", "callback_data": f"pay:{check_id}:no"}]]}


def _tg_send(check: dict, text: str) -> bool:
    chat = settings.owner_telegram_chat_id
    if not (settings.telegram_bot_token and chat):
        return False
    base = f"https://api.telegram.org/bot{settings.telegram_bot_token}"
    markup = json.dumps(_tg_buttons(check["id"]))
    try:
        img = image_path(check)
        if img and len(text) <= 1000:
            r = httpx.post(f"{base}/sendPhoto", data={"chat_id": chat, "caption": text, "reply_markup": markup},
                           files={"photo": (img.name, img.read_bytes())}, timeout=30)
        else:
            if img:
                httpx.post(f"{base}/sendPhoto", data={"chat_id": chat}, files={"photo": (img.name, img.read_bytes())}, timeout=30)
            r = httpx.post(f"{base}/sendMessage", data={"chat_id": chat, "text": text, "reply_markup": markup}, timeout=20)
        return r.status_code < 400
    except httpx.HTTPError:
        log.exception("telegram payment check failed")
        return False


def _wa_upload(img: Path) -> str | None:
    try:
        mime = "image/jpeg" if img.suffix == ".jpg" else "image/png"
        r = httpx.post(f"{GRAPH}/{settings.wa_phone_number_id}/media",
                       headers={"Authorization": f"Bearer {settings.wa_access_token}"},
                       data={"messaging_product": "whatsapp", "type": mime},
                       files={"file": (img.name, img.read_bytes(), mime)}, timeout=30)
        return r.json().get("id") if r.status_code < 400 else None
    except httpx.HTTPError:
        return None


def _wa_send(check: dict, order: dict, text: str) -> bool:
    to = settings.owner_whatsapp
    if not (to and settings.wa_access_token and settings.wa_phone_number_id):
        return False
    last = float(db.kv_get("owner_last_inbound", "0") or 0)
    plan = outbound.wa_plan(last or None, "payment_check")
    if plan == "text":
        img = image_path(check)
        media = _wa_upload(img) if img else None
        if media:
            outbound.wa_post({"messaging_product": "whatsapp", "to": to, "type": "image",
                              "image": {"id": media, "caption": f"إيصال أوردر {order['id']}"}})
        return outbound.wa_post({
            "messaging_product": "whatsapp", "to": to, "type": "interactive",
            "interactive": {"type": "button", "body": {"text": text[:1024]},
                            "action": {"buttons": [
                                {"type": "reply", "reply": {"id": f"pay:{check['id']}:yes", "title": "✅ وصل"}},
                                {"type": "reply", "reply": {"id": f"pay:{check['id']}:no", "title": "❌ موصلش"}}]}}})
    if plan == "template":
        tpl = store()["whatsapp_templates"]["payment_check"]
        p = outbound.wa_template_payload(to, tpl, [order.get("customer_name") or "-", f"{check['amount']:,}", order["id"],
                                                   check.get("reference") or "-"])
        p["template"]["components"] += [
            {"type": "button", "sub_type": "quick_reply", "index": "0", "parameters": [{"type": "payload", "payload": f"pay:{check['id']}:yes"}]},
            {"type": "button", "sub_type": "quick_reply", "index": "1", "parameters": [{"type": "payload", "payload": f"pay:{check['id']}:no"}]}]
        return outbound.wa_post(p)
    return False


def ask_owner(check: dict, order: dict, reminder: bool = False) -> list[str]:
    text = owner_text(check, order, reminder)
    via = []
    if _tg_send(check, text):
        via.append("telegram")
    if _wa_send(check, order, text):
        via.append("whatsapp")
    db.log_event(None, "owner_alert", {"kind": "payment_check", "text": text, "via": via or ["dashboard"],
                                       "check_id": check["id"]}, order["id"])
    return via or ["dashboard"]


# ------------------------------------------------------------------ decide

def decide(check_id: int, approve: bool, *, by: str, note: str | None = None) -> dict:
    check = get(check_id)
    if not check:
        return {"ok": False, "message": "طلب التأكيد ده مش موجود."}
    if check["status"] != "pending":
        word = "اتأكد" if check["status"] == "approved" else "اترفض"
        return {"ok": False, "already": True, "message": f"أوردر {check['order_id']} {word} قبل كده."}
    order = db.one("SELECT * FROM orders WHERE id=?", (check["order_id"],))
    now = time.time()
    if not order or order["status"] == "cancelled":
        db.x("UPDATE payment_checks SET status='void', decided_at=?, decided_by=? WHERE id=?", (now, by, check_id))
        return {"ok": False, "message": "الأوردر ده اتلغى."}

    from . import agent  # late import (agent imports this module)
    if approve:
        db.x("UPDATE payment_checks SET status='approved', decided_at=?, decided_by=?, note=? WHERE id=?", (now, by, note, check_id))
        db.x("UPDATE payments SET status='verified', reason='owner_confirmed' WHERE id=?", (check["payment_id"],))
        amt = check["amount"] or store()["policy"]["deposit_amount"]
        db.x("UPDATE orders SET deposit_paid=?, status='confirmed', updated_at=? WHERE id=?", (amt, now, order["id"]))
        order = db.one("SELECT * FROM orders WHERE id=?", (order["id"],))
        shipment = agent._ship(order, check["conv_id"])
        order = db.one("SELECT * FROM orders WHERE id=?", (order["id"],))
        _set_conv_state(check["conv_id"], "CONFIRMED")
        if check["conv_id"]:
            outbound.send_customer(check["conv_id"], f"وصلنا التحويل ✅ ({amt:,} ج) — شكراً!\n" + agent._shipped_msg(order, shipment),
                                   "deposit_confirmed", order_id=order["id"])
        db.log_event(check["conv_id"], "payment_owner_decision", {"check_id": check_id, "approved": True, "by": by,
                                                                  "minutes": round((now - check["asked_at"]) / 60, 1)}, order["id"])
        return {"ok": True, "approved": True, "message": f"✅ تمام — أوردر {order['id']} اتأكد واتشحن ({shipment['tracking']})."}

    db.x("UPDATE payment_checks SET status='rejected', decided_at=?, decided_by=?, note=? WHERE id=?", (now, by, note, check_id))
    db.x("UPDATE payments SET status='fraud', reason='owner_not_received' WHERE id=?", (check["payment_id"],))
    db.x("UPDATE orders SET status='awaiting_deposit', updated_at=? WHERE id=?", (now, order["id"]))
    _set_conv_state(check["conv_id"], "DEPOSIT")
    if check["conv_id"]:
        outbound.send_customer(check["conv_id"],
                               "للأسف التحويل ده لسه موصلش لحسابنا 🙏 اتأكدي من التطبيق إن العملية تمت على "
                               f"{store()['policy']['instapay_handle']} وابعتيلي إيصال العملية الصحيحة، أو قولي «إلغاء».",
                               "deposit_not_received", order_id=order["id"])
    db.log_event(check["conv_id"], "payment_owner_decision", {"check_id": check_id, "approved": False, "by": by}, order["id"])
    db.log_event(check["conv_id"], "deposit_checked", {"ok": False, "reason": "owner_not_received", "fraud": True}, order["id"])
    return {"ok": True, "approved": False, "message": f"❌ اتسجل — أوردر {order['id']} متوقف ومش هيتشحن، وبلغنا العميل."}


def _set_conv_state(conv_id: int | None, state: str) -> None:
    if not conv_id:
        return
    conv = db.conversation_by_id(conv_id)
    if conv:
        draft = json.loads(conv["draft"] or "{}")
        draft.pop("awaiting_owner", None)
        db.x("UPDATE conversations SET state=?, draft=?, updated_at=? WHERE id=?",
             (state, json.dumps(draft, ensure_ascii=False), time.time(), conv_id))


# ------------------------------------------------------------------ owner replies (Telegram / WhatsApp)

def parse_callback(data: str) -> tuple[int, bool] | None:
    m = re.fullmatch(r"pay:(\d+):(yes|no)", (data or "").strip())
    return (int(m.group(1)), m.group(2) == "yes") if m else None


def parse_owner_text(text: str) -> tuple[int, bool] | None:
    """'تم 4821' / 'لا 4821' / 'yes 4821'. The 4-digit code identifies the request."""
    from .nlu import normalize
    t = normalize(text or "")
    m = re.search(r"(?<!\d)(\d{4})(?!\d)", t)
    if not m:
        return None
    chk = db.one("SELECT id FROM payment_checks WHERE code=? AND status='pending' ORDER BY id DESC", (m.group(1),))
    if not chk:
        return None
    words = t.replace(m.group(1), " ").split()
    if any(w in NO_WORDS for w in words):
        return chk["id"], False
    if any(w in YES_WORDS for w in words):
        return chk["id"], True
    return None


def handle_owner_reply(text: str = "", callback: str = "", by: str = "owner") -> dict | None:
    parsed = parse_callback(callback) if callback else parse_owner_text(text)
    if not parsed:
        return None
    return decide(parsed[0], parsed[1], by=by)


# ------------------------------------------------------------------ reminders

def remind_due(now: float | None = None) -> int:
    now = now or time.time()
    steps = store()["policy"].get("owner_confirm_reminders_min", [30, 180])
    sent = 0
    for c in db.q("SELECT * FROM payment_checks WHERE status='pending'"):
        n = c["reminders"] or 0
        if n < len(steps) and now - c["asked_at"] >= steps[n] * 60:
            order = db.one("SELECT * FROM orders WHERE id=?", (c["order_id"],))
            if order:
                ask_owner(c, order, reminder=True)
                db.x("UPDATE payment_checks SET reminders=? WHERE id=?", (n + 1, c["id"]))
                sent += 1
    return sent
