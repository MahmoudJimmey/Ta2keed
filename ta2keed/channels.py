"""Messaging channels: WhatsApp Cloud API (webhook) and Telegram (long polling).

Both are optional. With no tokens the web chat at / is the channel.
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from . import agent, db, notify
from .config import settings

log = logging.getLogger("ta2keed.channels")
GRAPH = "https://graph.facebook.com/v21.0"


# ------------------------------------------------------------------ WhatsApp

_seen_ids: dict[str, float] = {}  # Meta retries webhooks; dedupe by message id


def wa_signature_ok(body: bytes, header: str | None) -> bool:
    """Verify X-Hub-Signature-256 when WHATSAPP_APP_SECRET is set (recommended in production)."""
    if not settings.wa_app_secret:
        return True
    import hashlib
    import hmac
    if not header or not header.startswith("sha256="):
        return False
    digest = hmac.new(settings.wa_app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, header[7:])


def _owner_wa(sender: str) -> bool:
    return bool(settings.owner_whatsapp) and sender.lstrip("+") == settings.owner_whatsapp.lstrip("+")


async def wa_send(to: str, text: str) -> None:
    if not settings.wa_access_token:
        return
    async with httpx.AsyncClient(timeout=20) as c:
        await c.post(f"{GRAPH}/{settings.wa_phone_number_id}/messages",
                     headers={"Authorization": f"Bearer {settings.wa_access_token}"},
                     json={"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text}})


async def wa_mark_read(message_id: str) -> None:
    if not settings.wa_access_token:
        return
    async with httpx.AsyncClient(timeout=10) as c:
        await c.post(f"{GRAPH}/{settings.wa_phone_number_id}/messages",
                     headers={"Authorization": f"Bearer {settings.wa_access_token}"},
                     json={"messaging_product": "whatsapp", "status": "read", "message_id": message_id})


async def wa_media(media_id: str) -> tuple[bytes, str]:
    async with httpx.AsyncClient(timeout=30) as c:
        h = {"Authorization": f"Bearer {settings.wa_access_token}"}
        meta = (await c.get(f"{GRAPH}/{media_id}", headers=h)).json()
        data = (await c.get(meta["url"], headers=h)).content
        return data, meta.get("mime_type", "application/octet-stream")


def _wa_text(msg: dict) -> str:
    kind = msg.get("type")
    if kind == "text":
        return msg["text"]["body"]
    if kind == "button":  # quick-reply button on a template
        return msg["button"].get("text", "")
    if kind == "interactive":
        i = msg["interactive"]
        return (i.get("button_reply") or i.get("list_reply") or {}).get("title", "")
    return ""


async def wa_handle(payload: dict) -> None:
    import time as _t
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for st in value.get("statuses", []):  # delivery receipts for OUR messages (sent/delivered/read/failed)
                if st.get("status") == "failed":
                    db.log_event(None, "whatsapp_send_failed", {"to": st.get("recipient_id"), "errors": st.get("errors")})
            for msg in value.get("messages", []):
                mid = msg.get("id", "")
                if mid in _seen_ids:
                    continue
                _seen_ids[mid] = _t.time()
                if len(_seen_ids) > 5000:
                    for k in sorted(_seen_ids, key=_seen_ids.get)[:2500]:
                        _seen_ids.pop(k, None)
                sender = msg["from"]
                kind = msg.get("type")
                asyncio.create_task(wa_mark_read(mid))

                if _owner_wa(sender):  # the shop owner talks to the agent: commands + opens the 24h window
                    db.kv_set("owner_last_inbound", str(_t.time()))
                    from . import payconfirm
                    cb = ""
                    if kind == "button":
                        cb = msg["button"].get("payload", "")
                    elif kind == "interactive":
                        cb = (msg["interactive"].get("button_reply") or {}).get("id", "")
                    res = await asyncio.to_thread(payconfirm.handle_owner_reply, _wa_text(msg), cb, "owner-whatsapp")
                    await wa_send(sender, res["message"] if res else notify.owner_command(_wa_text(msg)))
                    continue
                try:
                    if kind in ("text", "button", "interactive"):
                        replies = await asyncio.to_thread(agent.handle, "whatsapp", sender, _wa_text(msg))
                    elif kind == "image":
                        data, mime = await wa_media(msg["image"]["id"])
                        replies = await asyncio.to_thread(agent.handle, "whatsapp", sender,
                                                          msg["image"].get("caption", ""), image=data, image_mime=mime)
                    elif kind == "document" and str(msg["document"].get("mime_type", "")).startswith("image/"):
                        data, mime = await wa_media(msg["document"]["id"])
                        replies = await asyncio.to_thread(agent.handle, "whatsapp", sender, image=data, image_mime=mime)
                    elif kind == "audio":
                        data, mime = await wa_media(msg["audio"]["id"])
                        replies = await asyncio.to_thread(agent.handle, "whatsapp", sender, audio=data,
                                                          audio_name="voice.ogg")
                    else:
                        replies = ["ممكن تبعتيلي الطلب كتابة أو فويس؟ 🙏"]
                except Exception:
                    log.exception("wa handling failed")
                    replies = ["حصلت مشكلة بسيطة، ثواني وهرد عليكي 🙏"]
                for r in replies:
                    await wa_send(sender, r)
                await notify.maybe_notify_owner("whatsapp", sender)


# ------------------------------------------------------------------ Telegram

async def tg_call(c: httpx.AsyncClient, method: str, **kw):
    r = await c.post(f"https://api.telegram.org/bot{settings.telegram_bot_token}/{method}", json=kw, timeout=70)
    return r.json()


async def tg_file(c: httpx.AsyncClient, file_id: str) -> bytes:
    info = await tg_call(c, "getFile", file_id=file_id)
    path = info["result"]["file_path"]
    return (await c.get(f"https://api.telegram.org/file/bot{settings.telegram_bot_token}/{path}")).content


async def handle_tg_callback(c, cq: dict) -> dict | None:
    from . import payconfirm
    owner = settings.owner_telegram_chat_id
    is_owner = bool(owner) and str(cq.get("from", {}).get("id")) == owner
    out = await asyncio.to_thread(payconfirm.handle_owner_reply, "", cq.get("data", ""), "owner-telegram") if is_owner else None
    await tg_call(c, "answerCallbackQuery", callback_query_id=cq["id"],
                  text=(out or {}).get("message", "مش مسموح — الزرار ده لصاحب المحل بس")[:190])
    if out and cq.get("message"):
        chat_id = cq["message"]["chat"]["id"]
        await tg_call(c, "editMessageReplyMarkup", chat_id=chat_id, message_id=cq["message"]["message_id"],
                      reply_markup={"inline_keyboard": []})
        await tg_call(c, "sendMessage", chat_id=chat_id, text=out["message"])
    return out


async def telegram_loop() -> None:
    if not settings.telegram_bot_token:
        return
    log.info("Telegram polling started")
    offset = 0
    async with httpx.AsyncClient(timeout=70) as c:
        while True:
            try:
                res = await tg_call(c, "getUpdates", offset=offset, timeout=50)
                for upd in res.get("result", []):
                    offset = upd["update_id"] + 1
                    cq = upd.get("callback_query")
                    if cq:  # owner pressed a payment-confirmation button
                        await handle_tg_callback(c, cq)
                        continue
                    m = upd.get("message")
                    if not m:
                        continue
                    chat = str(m["chat"]["id"])
                    text0 = (m.get("text") or "").strip()
                    if text0.startswith("/owner"):  # claim owner alerts: /owner <code shown in the setup wizard>
                        from .config import save_wizard_values
                        from .setup import owner_claim_code
                        ok = text0.split()[-1] == owner_claim_code()
                        if ok:
                            save_wizard_values({"OWNER_TELEGRAM_CHAT_ID": chat})
                        await tg_call(c, "sendMessage", chat_id=chat, text="✅ تمام! هتوصلك التنبيهات والملخص اليومي هنا."
                                      if ok else "الكود غلط — خديه من صفحة الإعداد في Ta2keed.")
                        continue
                    if chat == settings.owner_telegram_chat_id and text0:
                        from . import payconfirm
                        out = await asyncio.to_thread(payconfirm.handle_owner_reply, text0, "", "owner-telegram")
                        if out:
                            await tg_call(c, "sendMessage", chat_id=chat, text=out["message"])
                            continue
                    if chat == settings.owner_telegram_chat_id and text0.startswith("/"):
                        await tg_call(c, "sendMessage", chat_id=chat, text=notify.owner_command(m["text"]))
                        continue
                    if m.get("photo"):
                        data = await tg_file(c, m["photo"][-1]["file_id"])
                        replies = await asyncio.to_thread(agent.handle, "telegram", chat, m.get("caption", ""),
                                                          image=data, image_mime="image/jpeg")
                    elif m.get("voice") or m.get("audio"):
                        f = m.get("voice") or m.get("audio")
                        data = await tg_file(c, f["file_id"])
                        replies = await asyncio.to_thread(agent.handle, "telegram", chat, audio=data,
                                                          audio_name="voice.ogg")
                    elif m.get("text"):
                        text = m["text"]
                        if text == "/start":
                            db.x("DELETE FROM conversations WHERE channel='telegram' AND user_id=?", (chat,))
                            text = "السلام عليكم"
                        replies = await asyncio.to_thread(agent.handle, "telegram", chat, text)
                    else:
                        continue
                    for r in replies:
                        await tg_call(c, "sendMessage", chat_id=chat, text=r)
                    await notify.maybe_notify_owner("telegram", chat)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("telegram loop error")
                await asyncio.sleep(3)
