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

async def wa_send(to: str, text: str) -> None:
    if not settings.wa_access_token:
        return
    async with httpx.AsyncClient(timeout=20) as c:
        await c.post(f"{GRAPH}/{settings.wa_phone_number_id}/messages",
                     headers={"Authorization": f"Bearer {settings.wa_access_token}"},
                     json={"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text}})


async def wa_media(media_id: str) -> tuple[bytes, str]:
    async with httpx.AsyncClient(timeout=30) as c:
        h = {"Authorization": f"Bearer {settings.wa_access_token}"}
        meta = (await c.get(f"{GRAPH}/{media_id}", headers=h)).json()
        data = (await c.get(meta["url"], headers=h)).content
        return data, meta.get("mime_type", "application/octet-stream")


async def wa_handle(payload: dict) -> None:
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for msg in change.get("value", {}).get("messages", []):
                sender = msg["from"]
                kind = msg.get("type")
                try:
                    if kind == "text":
                        replies = await asyncio.to_thread(agent.handle, "whatsapp", sender, msg["text"]["body"])
                    elif kind == "image":
                        data, mime = await wa_media(msg["image"]["id"])
                        replies = await asyncio.to_thread(agent.handle, "whatsapp", sender,
                                                          msg["image"].get("caption", ""), image=data, image_mime=mime)
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
                    m = upd.get("message")
                    if not m:
                        continue
                    chat = str(m["chat"]["id"])
                    if chat == settings.owner_telegram_chat_id and (m.get("text") or "").startswith("/"):
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
