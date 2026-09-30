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

from . import agent, channels, db, impact, notify
from .config import ROOT, settings, store
from .scenarios import SCENARIOS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
WEB = ROOT / "web"


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    db.conn()
    if not db.one("SELECT phone FROM customers LIMIT 1"):
        db.seed_customers()
    task = asyncio.create_task(channels.telegram_loop()) if settings.telegram_bot_token else None
    yield
    if task:
        task.cancel()


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
            "courier": "bosta" if settings.bosta_api_key else "mock"}


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


# ---------------- WhatsApp Cloud API webhook
@app.get("/webhook/whatsapp")
def wa_verify(mode: str = Query(None, alias="hub.mode"), token: str = Query(None, alias="hub.verify_token"),
              challenge: str = Query(None, alias="hub.challenge")):
    if mode == "subscribe" and token == settings.wa_verify_token:
        return PlainTextResponse(challenge)
    raise HTTPException(403)


@app.post("/webhook/whatsapp")
async def wa_webhook(request: Request):
    payload = await request.json()
    asyncio.create_task(channels.wa_handle(payload))
    return {"ok": True}
