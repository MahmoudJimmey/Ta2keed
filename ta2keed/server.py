"""FastAPI app: web chat demo, owner dashboard, REST API, WhatsApp webhook, Telegram poller."""
from __future__ import annotations

import asyncio
import base64
import contextlib
import csv
import io
import json
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import aftercare, agent, auth, channels, db, delivery, impact, notify, payconfirm, scheduler, security, setup
from .config import ROOT, settings, store
from .scenarios import SCENARIOS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("ta2keed")
WEB = ROOT / "web"


def _banner() -> None:
    base = settings.public_url.rstrip("/") if settings.public_url else "http://localhost:8000"
    if settings.admin_password:
        log.info("Ta2keed ready → %s  (dashboard login required)", base)
    else:
        log.info("=" * 70)
        log.info(" Ta2keed is running. First-time setup:")
        log.info("   on this computer:  http://localhost:8000/setup")
        log.info("   from anywhere:     %s/setup?token=%s", base, auth.setup_token())
        log.info("=" * 70)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    db.conn()
    if settings.demo and not db.one("SELECT phone FROM customers LIMIT 1"):
        db.seed_customers()
    _banner()
    tasks = [asyncio.create_task(channels.telegram_supervisor())]  # starts/stops as the token is added in /setup
    if settings.scheduler_enabled:
        tasks.append(asyncio.create_task(scheduler.loop()))
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="Ta2keed — COD order-confirmation agent", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=WEB), name="static")
app.middleware("http")(auth.middleware)
app.middleware("http")(security.middleware)  # registered last = runs first


def _demo_only():
    if not settings.demo:
        raise HTTPException(403, "Demo tools are off (DEMO_MODE=off). Turn them on in /setup → Go live.")


class ChatIn(BaseModel):
    user: str = "web-user"
    text: str = ""
    image_b64: str | None = None
    image_mime: str = "image/png"
    audio_b64: str | None = None


@app.get("/", response_class=HTMLResponse)
def home():
    if not setup.wizard_values().get("_setup_complete") and not setup.wizard_values().get("_setup_skipped"):
        return RedirectResponse("/setup", status_code=303)
    return (WEB / "index.html").read_text(encoding="utf-8")


# ---------------- login + setup wizard
@app.get("/login", response_class=HTMLResponse)
def login_page():
    return (WEB / "login.html").read_text(encoding="utf-8")


class LoginIn(BaseModel):
    password: str


@app.post("/login")
def login(body: LoginIn, request: Request):
    ip = security.client_ip(request)
    if security.login_blocked(ip):
        raise HTTPException(429, "Too many attempts. Try again in 15 minutes.")
    if not auth.check_password(body.password):
        security.login_failed(ip)
        db.log_event(None, "login_failed", {"ip": ip})
        raise HTTPException(401, "Wrong password")
    security.login_ok(ip)
    db.log_event(None, "login", {"ip": ip})
    from fastapi.responses import JSONResponse
    resp = JSONResponse({"ok": True})
    resp.set_cookie(auth.COOKIE, auth.make_session(), max_age=auth.MAX_AGE, httponly=True, samesite="strict",
                    secure=auth.secure_cookie(request))
    return resp


@app.post("/logout")
def logout():
    from fastapi.responses import JSONResponse
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(auth.COOKIE)
    return resp


@app.get("/setup", response_class=HTMLResponse)
def setup_page():
    return (WEB / "setup.html").read_text(encoding="utf-8")


@app.get("/api/setup/state")
def setup_state(request: Request):
    return setup.state(str(request.base_url))


@app.post("/api/setup/save")
async def setup_save(request: Request):
    try:
        res = setup.save(await request.json())
    except ValueError as e:
        raise HTTPException(400, str(e))
    from fastapi.responses import JSONResponse
    resp = JSONResponse(res)
    if "ADMIN_PASSWORD" in res["saved"]:  # log the owner straight in after creating the password
        resp.set_cookie(auth.COOKIE, auth.make_session(), max_age=auth.MAX_AGE, httponly=True, samesite="strict",
                        secure=auth.secure_cookie(request))
    return resp


# ---------------- data ownership: backup, export, erase
@app.get("/api/admin/backup")
def admin_backup():
    """Download everything (database + shop profile + encrypted settings) as one zip."""
    import zipfile
    from .config import data_dir
    buf = io.BytesIO()
    import sqlite3
    import tempfile
    snap_dir = tempfile.mkdtemp()
    snap = Path(snap_dir) / "snapshot.db"
    dst = sqlite3.connect(snap)
    db.conn().backup(dst)
    dst.close()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(snap, "ta2keed.db")
        for name in ("store.json", "settings.json"):
            f = data_dir() / name
            if f.exists():
                z.write(f, name)
        z.writestr("README.txt", "Ta2keed backup. settings.json secrets are encrypted with your master key "
                                 "(.master.key or TA2KEED_SECRET_KEY), which is NOT included for safety.")
    import shutil
    shutil.rmtree(snap_dir, ignore_errors=True)
    import datetime as _dt
    return StreamingResponse(iter([buf.getvalue()]), media_type="application/zip", headers={
        "Content-Disposition": f"attachment; filename=ta2keed-backup-{_dt.date.today()}.zip"})


@app.get("/api/admin/customer/{phone}")
def admin_customer_export(phone: str):
    """Everything stored about one customer (data-subject access request)."""
    convs = db.q("SELECT id, channel, created_at FROM conversations WHERE user_id LIKE ? OR id IN "
                 "(SELECT conv_id FROM orders WHERE customer_phone=?)", (f"%{phone[-10:]}", phone))
    ids = [c["id"] for c in convs] or [-1]
    marks = ",".join("?" * len(ids))
    return {"customer": db.customer(phone), "orders": db.q("SELECT * FROM orders WHERE customer_phone=?", (phone,)),
            "messages": db.q(f"SELECT conv_id, role, text, ts FROM messages WHERE conv_id IN ({marks})", tuple(ids))}


@app.delete("/api/admin/customer/{phone}")
def admin_customer_erase(phone: str):
    """Right to erasure: anonymise orders (keeps totals for accounting) and delete messages/history."""
    convs = [r["conv_id"] for r in db.q("SELECT DISTINCT conv_id FROM orders WHERE customer_phone=?", (phone,))]
    convs += [r["id"] for r in db.q("SELECT id FROM conversations WHERE user_id LIKE ?", (f"%{phone[-10:]}",))]
    for cid in set(c for c in convs if c):
        db.x("DELETE FROM messages WHERE conv_id=?", (cid,))
        db.x("DELETE FROM conversations WHERE id=?", (cid,))
    n = db.one("SELECT COUNT(*) n FROM orders WHERE customer_phone=?", (phone,))["n"]
    db.x("UPDATE orders SET customer_name='[erased]', customer_phone='[erased]', address='[erased]' WHERE customer_phone=?", (phone,))
    db.x("DELETE FROM customers WHERE phone=?", (phone,))
    db.log_event(None, "customer_erased", {"orders_anonymised": n})
    return {"ok": True, "orders_anonymised": n, "conversations_deleted": len(set(convs))}


@app.post("/api/setup/products-csv")
async def setup_products_csv(request: Request):
    text = (await request.body()).decode("utf-8", "replace")
    prods = setup.parse_products_csv(text)
    if not prods:
        raise HTTPException(400, "No products found. First row must be headers: name_ar,name_en,price,sizes,colors")
    return {"products": prods}


@app.get("/api/setup/products-template.csv")
def setup_products_template():
    rows = "name_ar,name_en,price,sizes,colors,keywords,upsell_sku,upsell_price\n"
    for p in store()["products"]:
        up = p.get("upsell") or {}
        rows += (f"{p['name_ar']},{p['name_en']},{p['price']},{' / '.join(p['sizes'])},{' / '.join(p['colors'])},"
                 f"{' / '.join(p['keywords'])},{up.get('sku', '')},{up.get('price', '')}\n")
    return StreamingResponse(iter(["\ufeff" + rows]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=products.csv"})


class TestIn(BaseModel):
    to: str | None = None
    url: str | None = None
    create: bool = False


@app.post("/api/setup/test/{what}")
def setup_test(what: str, body: TestIn | None = None, request: Request = None):
    body = body or TestIn()
    fn = {"llm": setup.test_llm, "whatsapp": setup.test_whatsapp, "telegram": setup.test_telegram,
          "bosta": setup.test_bosta,
          "whatsapp-send": lambda: setup.test_whatsapp_send(body.to),
          "templates": lambda: setup.whatsapp_templates(body.create),
          "public-url": lambda: setup.test_public_url(body.url or setup.public_url(str(request.base_url))),
          "digest": lambda: {"ok": True, "message": "Sent via " + ", ".join(notify.send_digest()["via"])}}.get(what)
    if not fn:
        raise HTTPException(404)
    return fn()


@app.get("/api/setup/secret")
def setup_secret():
    return {"value": setup.generate_secret()}


@app.get("/health")
def health():
    return {"ok": True, "llm": settings.llm_provider if settings.llm_enabled else "offline",
            "whatsapp": bool(settings.wa_access_token), "telegram": bool(settings.telegram_bot_token),
            "courier": "bosta" if settings.bosta_api_key else "mock", "scheduler": settings.scheduler_enabled,
            "owner_channels": [c for c, on in (("telegram", settings.owner_telegram_chat_id),
                                               ("whatsapp", settings.owner_whatsapp)) if on] or ["dashboard"],
            "demo": settings.demo, "shop": store()["store"]["name"]}


@app.post("/api/chat")
def chat(body: ChatIn):
    image = base64.b64decode(body.image_b64) if body.image_b64 else None
    audio = base64.b64decode(body.audio_b64) if body.audio_b64 else None
    replies = agent.handle("web", body.user, body.text, image=image, image_mime=body.image_mime, audio=audio)
    conv = db.get_conversation("web", body.user)
    return {"replies": replies, "state": conv["state"], "draft": conv["draft"], "order_id": conv.get("order_id")}


@app.post("/api/reset")
def reset():
    _demo_only()
    db.reset(seed=True)
    return {"ok": True}


@app.get("/api/scenarios")
def scenarios():
    if not settings.demo:
        return {}
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
    if settings.bosta_api_key and not settings.demo:
        raise HTTPException(403, "Real courier connected — updates come from Bosta.")
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


# ---------------- owner payment confirmation (second layer after the screenshot checks)
@app.get("/api/payment-checks")
def payment_checks():
    return payconfirm.pending()


@app.get("/api/payment-checks/{check_id}/image")
def payment_check_image(check_id: int):
    c = payconfirm.get(check_id)
    p = payconfirm.image_path(c) if c else None
    if not p:
        raise HTTPException(404)
    return FileResponse(p)


class DecisionIn(BaseModel):
    approve: bool
    note: str | None = None


@app.post("/api/payment-checks/{check_id}/decide")
def payment_check_decide(check_id: int, body: DecisionIn):
    res = payconfirm.decide(check_id, body.approve, by="owner-dashboard", note=body.note)
    if not res["ok"] and not res.get("already"):
        raise HTTPException(400, res["message"])
    return res


@app.get("/api/scheduled")
def scheduled():
    return db.q("SELECT * FROM scheduled ORDER BY due_at")


@app.post("/api/followups/fast-forward")
def followups_fast_forward(order_id: str | None = None, kind: str | None = None):
    """Demo: send pending review/reorder messages now instead of in 24h / 14 days."""
    _demo_only()
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
