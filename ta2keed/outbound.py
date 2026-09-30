"""Proactive (agent-initiated) messages to customers and to the shop owner.

Customer channel = the channel the order came from (web / telegram / whatsapp).
WhatsApp rule: free-form text is only allowed within 24h of the customer's last message;
outside that window we send a pre-approved template (names in store.json -> whatsapp_templates).

Every send is logged (messages + events) so the dashboard and impact report can prove
exactly what the customer was told — and what was deliberately kept internal.
"""
from __future__ import annotations

import logging
import time

import httpx

from . import db
from .config import settings, store

log = logging.getLogger("ta2keed.outbound")
GRAPH = "https://graph.facebook.com/v21.0"
WA_WINDOW_S = 24 * 3600


# ------------------------------------------------------------------ WhatsApp primitives (sync; used from threads)

def wa_text_payload(to: str, text: str) -> dict:
    return {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text}}


def wa_template_payload(to: str, template: str, params: list[str]) -> dict:
    tpl = {"name": template, "language": {"code": store().get("whatsapp_templates", {}).get("language", "ar")}}
    if params:
        tpl["components"] = [{"type": "body", "parameters": [{"type": "text", "text": str(p)} for p in params]}]
    return {"messaging_product": "whatsapp", "to": to, "type": "template", "template": tpl}


def wa_post(payload: dict) -> bool:
    if not (settings.wa_access_token and settings.wa_phone_number_id):
        return False
    try:
        r = httpx.post(f"{GRAPH}/{settings.wa_phone_number_id}/messages",
                       headers={"Authorization": f"Bearer {settings.wa_access_token}"}, json=payload, timeout=20)
        if r.status_code >= 400:
            log.warning("whatsapp send failed %s %s", r.status_code, r.text[:300])
        return r.status_code < 400
    except httpx.HTTPError:
        log.exception("whatsapp send error")
        return False


def wa_plan(last_inbound: float | None, kind: str, now: float | None = None) -> str:
    """'text' inside the 24h window, 'template' outside it (if one is configured), else 'skip'."""
    now = now or time.time()
    if last_inbound and now - last_inbound < WA_WINDOW_S:
        return "text"
    return "template" if store().get("whatsapp_templates", {}).get(kind) else "skip"


def tg_post(chat_id: str, text: str) -> bool:
    if not settings.telegram_bot_token:
        return False
    try:
        r = httpx.post(f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                       json={"chat_id": chat_id, "text": text}, timeout=20)
        return r.status_code < 400
    except httpx.HTTPError:
        log.exception("telegram send error")
        return False


# ------------------------------------------------------------------ customer

def send_customer(conv_id: int, text: str, kind: str, *, order_id: str | None = None,
                  template_params: list[str] | None = None) -> dict:
    conv = db.conversation_by_id(conv_id)
    if not conv:
        return {"sent": False, "via": "none"}
    channel, user = conv["channel"], conv["user_id"]
    via, ok = "stored", True  # web/sim: message is stored and the web chat polls it

    if channel == "telegram":
        ok, via = tg_post(user, text), "telegram"
    elif channel == "whatsapp":
        plan = wa_plan(db.last_inbound_ts(conv_id), kind)
        if plan == "text":
            ok, via = wa_post(wa_text_payload(user, text)), "whatsapp-text"
        elif plan == "template":
            tpl = store()["whatsapp_templates"][kind]
            ok, via = wa_post(wa_template_payload(user, tpl, template_params or [])), f"whatsapp-template:{tpl}"
        else:
            ok, via = False, "whatsapp-skipped(24h window, no template)"

    db.add_message(conv_id, "agent", text, {"proactive": True, "kind": kind, "via": via})
    db.log_event(conv_id, "customer_notified", {"kind": kind, "channel": channel, "via": via, "ok": ok}, order_id)
    return {"sent": ok, "via": via}


# ------------------------------------------------------------------ owner

def send_owner(text: str, kind: str, *, order_id: str | None = None, template_params: list[str] | None = None) -> dict:
    """Owner gets alerts/digests on Telegram and/or WhatsApp. Always logged to the dashboard 'Owner inbox'."""
    vias = []
    if settings.owner_telegram_chat_id and tg_post(settings.owner_telegram_chat_id, text):
        vias.append("telegram")
    if settings.owner_whatsapp:
        last = float(db.kv_get("owner_last_inbound", "0") or 0)
        tpl_kind = "owner_digest" if kind == "digest" else "owner_alert"
        plan = wa_plan(last or None, tpl_kind)
        if plan == "text" and wa_post(wa_text_payload(settings.owner_whatsapp, text)):
            vias.append("whatsapp-text")
        elif plan == "template":
            params = template_params or [text[:900].replace("\n", " · ")]
            if wa_post(wa_template_payload(settings.owner_whatsapp, store()["whatsapp_templates"][tpl_kind], params)):
                vias.append("whatsapp-template")
    db.log_event(None, "owner_alert", {"kind": kind, "text": text, "via": vias or ["dashboard"]}, order_id)
    return {"via": vias or ["dashboard"]}
