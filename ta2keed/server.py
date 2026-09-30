"""FastAPI app: web chat demo, owner dashboard, REST API, WhatsApp webhook, Telegram poller."""
from __future__ import annotations

import asyncio
import base64
import contextlib
import csv
import io
import json
import logging

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import aftercare, agent, channels, db, delivery, impact, notify, scheduler
from .config import ROOT, settings, store
from .scenarios import SCENARIOS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
WEB = ROOT / "web"


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    db.conn()
    if not db.one("SELECT phone FROM customers LIMIT 1"):
        db.seed_customers()
    tasks = []
    if settings.telegram_bot_token:
        tasks.append(asyncio.create_task(channels.telegram_loop()))
    if settings.scheduler_enabled:
        tasks.append(asyncio.create_task(scheduler.loop()))
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="Ta2keed — COD order-confirmation agent", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=WEB), name="static")


class ChatIn(BaseModel):
    user: str = "web-user"
    text: str = ""
    image_b64: str | None = None
    image_mime: str = "image/png"
    audio_b64: str | None = None


@app.get("/", response_class=HTMLResponse)
def home():
    return (WEB / "index.html").read_text(encoding="utf-8")


@app.get("/health")
def health():
    return {"ok": True, "llm": settings.llm_provider if settings.llm_enabled else "offline",
            "whatsapp": bool(settings.wa_access_token), "telegram": bool(settings.telegram_bot_token),
            "courier": "bosta" if settings.bosta_api_key else "mock", "scheduler": settings.scheduler_enabled,
            "owner_channels": [c for c, on in (("telegram", settings.owner_telegram_chat_id),
                                               ("whatsapp", settings.owner_whatsapp)) if on] or ["dashboard"]}


@app.post("/api/chat")
def chat(body: ChatIn):
    image = base64.b64decode(body.image_b64) if body.image_b64 else None
    audio = base64.b64decode(body.audio_b64) if body.audio_b64 else None
    replies = agent.handle("web", body.user, body.text, image=image, image_mime=body.image_mime, audio=audio)
    conv = db.get_conversation("web", body.user)
    return {"replies": replies, "state": conv["state"], "draft": conv["draft"], "order_id": conv.get("order_id")}


@app.post("/api/reset")
def reset():
    db.reset(seed=True)
    return {"ok": True}


@app.get("/api/scenarios")
def scenarios():
    return {k: {"title": v["title"], "steps": v["steps"]} for k, v in SCENARIOS.items()}


@app.get("/api/receipts/{name}")
def receipt(name: str):
    path = (ROOT / "data" / "receipts" / name).resolve()
    if path.parent != (ROOT / "data" / "receipts").resolve() or not path.exists():
        raise HTTPException(404)
    return FileResponse(path)


@app.get("/api/orders")
def orders():
    rows = db.q("SELECT * FROM orders ORDER BY created_at DESC")
    for r in rows:
        r["items"] = json.loads(r["items"])
        r["risk_reasons"] = json.loads(r["risk_reasons"] or "[]")
    return rows


@app.get("/api/orders.csv")
def orders_csv():
    rows = db.q("SELECT id,created_at,customer_name,customer_phone,address,zone,subtotal,shipping,total,"
                "upsell_value,risk_score,deposit_required,deposit_paid,status,tracking FROM orders ORDER BY created_at")
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()) if rows else ["id"])
    w.writeheader()
    w.writerows(rows)
    return StreamingResponse(iter(["\ufeff" + buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=orders.csv"})


@app.get("/api/events")
def events(limit: int = 60):
    rows = db.q("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))
    for r in rows:
        r["data"] = json.loads(r["data"] or "{}")
    return rows


@app.get("/api/impact")
def get_impact():
    return {"measured": impact.measured(), "projected": impact.projected(), "store": store()["store"]}


@app.get("/api/digest", response_class=PlainTextResponse)
def digest():
    return notify.digest_text()


@app.post("/api/digest/send")
def digest_send():
    return notify.send_digest()


@app.get("/api/messages")
def messages(user: str, since: int = 0, channel: str = "web"):
    """Web chat polls this to show proactive messages (delivery highlights, review, reorder)."""
    conv = db.one("SELECT id FROM conversations WHERE channel=? AND user_id=?", (channel, user))
    if not conv:
        return {"messages": [], "last_id": since}
    rows = db.q("SELECT id, role, text, meta FROM messages WHERE conv_id=? AND id>? ORDER BY id", (conv["id"], since))
    for r in rows:
        r["meta"] = json.loads(r["meta"] or "{}")
    last = db.one("SELECT MAX(id) AS m FROM messages WHERE conv_id=?", (conv["id"],))["m"] or since
    return {"messages": [r for r in rows if r["meta"].get("proactive")], "last_id": last}


# ---------------- delivery tracking
class DeliveryIn(BaseModel):
    order_id: str | None = None
    tracking: str | None = None
    status: str | int
    reason: str | None = None
    cod_collected: int | None = None


@app.post("/api/orders/{order_id}/advance")
def order_advance(order_id: str):
    """Mock courier: move the parcel one step (created → picked up → in transit → out for delivery → delivered)."""
    o = delivery.find_order(order_id)
    if not o:
        raise HTTPException(404)
    return delivery.advance(o)


@app.post("/api/orders/{order_id}/delivery")
def order_delivery(order_id: str, body: DeliveryIn):
    """Manual status update (e.g. the shop's own driver): delivered / refused / delivery_failed / returned..."""
    o = delivery.find_order(order_id)
    if not o:
        raise HTTPException(404)
    res = delivery.apply_update(o, body.status, reason=body.reason, source="manual", cod_collected=body.cod_collected)
    if not res["ok"]:
        raise HTTPException(400, res["error"])
    return res


@app.post("/webhook/courier")
async def courier_webhook(request: Request):
    """Generic courier webhook: {order_id|tracking, status, reason?, cod_collected?}."""
    if settings.courier_webhook_secret and request.headers.get("authorization") != settings.courier_webhook_secret:
        raise HTTPException(401)
    body = DeliveryIn(**(await request.json()))
    o = delivery.find_order(body.order_id, body.tracking)
    if not o:
        raise HTTPException(404, "order not found")
    return delivery.apply_update(o, body.status, reason=body.reason, source="courier-webhook",
                                 cod_collected=body.cod_collected)


@app.post("/webhook/bosta")
async def bosta_webhook(request: Request):
    """Bosta delivery webhook (set it in Bosta dashboard → Settings → Webhooks)."""
    if settings.courier_webhook_secret and request.headers.get("authorization") != settings.courier_webhook_secret:
        raise HTTPException(401)
    p = delivery.parse_bosta(await request.json())
    o = delivery.find_order(p["order_id"], p["tracking"])
    if not o:
        return {"ok": False, "error": "order not found"}  # 200 so Bosta doesn't retry forever
    return delivery.apply_update(o, p["status"], reason=p["reason"], source="bosta",
                                 cod_collected=int(p["cod"]) if p.get("cod") else None)


@app.get("/api/scheduled")
def scheduled():
    return db.q("SELECT * FROM scheduled ORDER BY due_at")


@app.post("/api/followups/fast-forward")
def followups_fast_forward(order_id: str | None = None, kind: str | None = None):
    """Demo: send pending review/reorder messages now instead of in 24h / 14 days."""
    return {"sent": aftercare.fast_forward(order_id, kind)}


# ---------------- WhatsApp Cloud API webhook
@app.get("/webhook/whatsapp")
def wa_verify(mode: str = Query(None, alias="hub.mode"), token: str = Query(None, alias="hub.verify_token"),
              challenge: str = Query(None, alias="hub.challenge")):
    if mode == "subscribe" and token == settings.wa_verify_token:
        return PlainTextResponse(challenge)
    raise HTTPException(403)


@app.post("/webhook/whatsapp")
async def wa_webhook(request: Request):
    raw = await request.body()
    if not channels.wa_signature_ok(raw, request.headers.get("x-hub-signature-256")):
        raise HTTPException(401, "bad signature")
    payload = json.loads(raw or b"{}")
    asyncio.create_task(channels.wa_handle(payload))
    return {"ok": True}
