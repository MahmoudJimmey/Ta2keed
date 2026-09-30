"""API smoke tests (FastAPI TestClient)."""
import base64
from pathlib import Path

from fastapi.testclient import TestClient

from ta2keed.server import app

RECEIPTS = Path(__file__).resolve().parent.parent / "data" / "receipts"


def test_web_chat_flow_and_dashboard():
    with TestClient(app) as c:
        assert c.get("/health").json()["ok"]
        assert "Ta2keed" in c.get("/").text
        for t in ["عايزة شنطة كروس بيج", "اسمي ياسمين حسن ورقمي 01122223333",
                  "العنوان الدقي شارع التحرير عمارة 20 الدور 3", "لا شكرا", "تمام"]:
            r = c.post("/api/chat", json={"user": "api-u", "text": t}).json()
        assert r["state"] == "CONFIRMED"
        orders = c.get("/api/orders").json()
        assert orders[0]["status"] == "shipped"
        assert c.get("/api/impact").json()["measured"]["orders_auto_shipped"] == 1
        assert "orders" in c.get("/api/orders.csv").headers["content-disposition"]


def test_image_upload_via_api():
    with TestClient(app) as c:
        for t in ["عايزة 2 فستان صيفي مقاس M بينك", "ريم عادل 01288889999 فيصل", "جنب الجامع", "لا", "تمام بس هفكر"]:
            r = c.post("/api/chat", json={"user": "api-img", "text": t}).json()
        assert r["state"] == "DEPOSIT"
        b64 = base64.b64encode((RECEIPTS / "receipt_ok.png").read_bytes()).decode()
        r = c.post("/api/chat", json={"user": "api-img", "image_b64": b64}).json()
        assert r["state"] == "OWNER_CHECK"                       # screenshot alone never ships
        chk = c.get("/api/payment-checks").json()[0]
        c.post(f"/api/payment-checks/{chk['id']}/decide", json={"approve": True})
        assert c.get("/api/orders").json()[0]["status"] == "shipped"


def test_whatsapp_verify():
    with TestClient(app) as c:
        r = c.get("/webhook/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "ta2keed-verify",
                                               "hub.challenge": "42"})
        assert r.text == "42"
