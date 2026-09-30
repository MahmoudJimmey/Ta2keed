"""Delivery tracking, highlight-only customer messages, after-delivery care, daily digest, WhatsApp plumbing."""
import datetime as dt
import hashlib
import hmac
import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from ta2keed import aftercare, agent, db, delivery, impact, notify, outbound, scheduler
from ta2keed.scenarios import SCENARIOS

RECEIPTS = Path(__file__).resolve().parent.parent / "data" / "receipts"


def shipped_order(user="mona", scenario="happy_path"):
    for step in SCENARIOS[scenario]["steps"]:
        if "image" in step:
            agent.handle("test", user, image=(RECEIPTS / step["image"]).read_bytes())
        else:
            agent.handle("test", user, step["text"])
    return db.one("SELECT * FROM orders ORDER BY created_at DESC")


def proactive(conv_id):
    return [m for m in db.q("SELECT * FROM messages WHERE conv_id=? AND role='agent'", (conv_id,))
            if json.loads(m["meta"]).get("proactive")]


def test_status_normalization():
    assert delivery.normalize_status(45) == "delivered"
    assert delivery.normalize_status("41") == "out_for_delivery"
    assert delivery.normalize_status("Out-For-Delivery") == "out_for_delivery"
    assert delivery.normalize_status("customer_refused") == "refused"
    assert delivery.normalize_status("banana") is None


def test_only_highlights_reach_the_customer():
    o = shipped_order()
    assert o["delivery_status"] == "created"
    before = len(proactive(o["conv_id"]))
    for _ in range(4):  # created -> picked_up -> in_transit -> out_for_delivery -> delivered
        delivery.advance(db.one("SELECT * FROM orders WHERE id=?", (o["id"],)))
    msgs = proactive(o["conv_id"])[before:]
    kinds = [json.loads(m["meta"])["kind"] for m in msgs]
    assert kinds == ["out_for_delivery", "delivered"]            # picked_up / in_transit stayed internal
    assert "1,070" in msgs[0]["text"]                             # tells her the exact cash to prepare
    o = db.one("SELECT * FROM orders WHERE id=?", (o["id"],))
    assert o["status"] == "delivered" and o["cod_collected"] == 1070
    ups = db.q("SELECT * FROM events WHERE type='delivery_update' AND order_id=?", (o["id"],))
    assert len(ups) == 4 and sum(json.loads(e["data"])["customer_notified"] for e in ups) == 2


def test_delivered_updates_customer_history_and_schedules_followups():
    o = shipped_order()
    before = db.customer("01011112222")["delivered"]
    delivery.apply_update(o, "delivered")
    assert db.customer("01011112222")["delivered"] == before + 1
    kinds = {j["kind"] for j in db.q("SELECT * FROM scheduled WHERE order_id=?", (o["id"],))}
    assert kinds == {"review", "reorder"}


def test_refusal_is_remembered_and_owner_alerted_but_customer_not_messaged():
    o = shipped_order(user="sara", scenario="questions")
    before = len(proactive(o["conv_id"]))
    delivery.apply_update(o, "refused", reason="العميل غير رأيه")
    assert db.customer("01055556666")["refused"] == 2              # seeded 1 + this one
    assert len(proactive(o["conv_id"])) == before                   # no message to the customer
    alert = db.one("SELECT * FROM events WHERE type='owner_alert' ORDER BY id DESC")
    assert json.loads(alert["data"])["kind"] == "refused"
    # next time she orders, the risk engine sees the refusals
    from ta2keed import risk
    score, reasons = risk.score({"phone": "01055556666", "address": "اسكندرية سموحة شارع فوزي معاذ برج النور الدور 7",
                                 "zone": "alex"}, 225)
    assert any("refused 2" in r for r in reasons)


def test_failed_attempt_asks_customer_and_captures_reschedule():
    o = shipped_order()
    delivery.apply_update(o, "out_for_delivery")
    delivery.apply_update(db.one("SELECT * FROM orders WHERE id=?", (o["id"],)), "delivery_failed", reason="الموبايل مقفول")
    last = proactive(o["conv_id"])[-1]
    assert json.loads(last["meta"])["kind"] == "delivery_failed"
    r = agent.handle("test", "mona", "بكرة بعد الساعة 5")
    assert "الميعاد الجديد" in r[0]
    kinds = [json.loads(e["data"]).get("kind") for e in db.q("SELECT data FROM events WHERE type='owner_alert'")]
    assert "delivery_failed" in kinds and "reschedule_requested" in kinds
    # courier re-attempts and delivers
    delivery.advance(db.one("SELECT * FROM orders WHERE id=?", (o["id"],)))
    delivery.advance(db.one("SELECT * FROM orders WHERE id=?", (o["id"],)))
    assert db.one("SELECT status FROM orders WHERE id=?", (o["id"],))["status"] == "delivered"


def test_duplicate_and_late_webhooks_are_ignored():
    o = shipped_order()
    delivery.apply_update(o, "delivered")
    o = db.one("SELECT * FROM orders WHERE id=?", (o["id"],))
    assert delivery.apply_update(o, "delivered")["duplicate"]
    assert delivery.apply_update(o, "in_transit")["ignored"]
    assert db.customer("01011112222")["delivered"] == 7             # counted once


def test_review_high_rating_thanks_low_rating_alerts_owner():
    o = shipped_order()
    delivery.apply_update(o, "delivered")
    sent = aftercare.fast_forward(o["id"])
    assert [s["kind"] for s in sent] == ["review", "reorder"]
    # reorder prompt is the latest; send review again flow: rating must still be parsed
    conv = db.get_conversation("test", "mona")
    conv["draft"]["post"] = {"kind": "rating", "order_id": o["id"]}
    db.save_conversation(conv)
    r = agent.handle("test", "mona", "2")
    assert "آسفين" in r[0]
    assert db.one("SELECT rating FROM orders WHERE id=?", (o["id"],))["rating"] == 2
    alert = db.one("SELECT * FROM events WHERE type='owner_alert' ORDER BY id DESC")
    assert json.loads(alert["data"])["kind"] == "low_rating"


def test_high_rating():
    o = shipped_order()
    delivery.apply_update(o, "delivered")
    db.x("UPDATE scheduled SET due_at=0 WHERE kind='review'")
    aftercare.run_due()
    r = agent.handle("test", "mona", "⭐⭐⭐⭐⭐")
    assert "شكراً" in r[0] and db.one("SELECT rating FROM orders")["rating"] == 5


def test_reorder_offer_leads_to_tagged_repeat_order():
    o = shipped_order()
    delivery.apply_update(o, "delivered")
    db.x("UPDATE scheduled SET due_at=0 WHERE kind='reorder'")
    sent = aftercare.run_due()
    assert sent and sent[0]["kind"] == "reorder"
    msg = proactive(o["conv_id"])[-1]["text"]
    assert "خصم 10%" in msg and "NOUR" in msg
    for t in ["عايزة طقم بيتي M زيتي", "لا", "تمام"]:
        agent.handle("test", "mona", t)
    new = db.one("SELECT * FROM orders ORDER BY created_at DESC")
    assert new["id"] != o["id"] and new["source"] == "reorder" and new["status"] == "shipped"
    assert impact.measured()["repeat_orders"] == 1


def test_followups_skip_if_not_delivered():
    o = shipped_order()
    aftercare.schedule(o, "review", 0)
    assert aftercare.run_due() == []
    assert db.one("SELECT status FROM scheduled")["status"] == "skipped"


def test_daily_digest_content_and_schedule():
    o = shipped_order()
    for _ in range(4):
        delivery.advance(db.one("SELECT * FROM orders WHERE id=?", (o["id"],)))
    shipped_order(user="heba", scenario="known_refuser")
    text = notify.digest_text()
    assert "اتسلم: 1" in text and "1,070" in text and "ملخص اليوم" in text
    # scheduler sends once per day after digest_time
    late = dt.datetime.now().replace(hour=23, minute=0)
    early = dt.datetime.now().replace(hour=8, minute=0)
    assert not scheduler.digest_due(early)
    assert scheduler.tick(late)["digest"] is not None
    assert scheduler.tick(late)["digest"] is None
    assert db.one("SELECT COUNT(*) n FROM events WHERE type='digest_sent'")["n"] == 1


def test_measured_refusal_rate():
    a = shipped_order()
    b = shipped_order(user="sara", scenario="questions")
    delivery.apply_update(a, "delivered")
    delivery.apply_update(b, "refused")
    m = impact.measured()
    assert m["orders_delivered"] == 1 and m["orders_refused_or_returned"] == 1 and m["measured_refusal_rate"] == 0.5


# ---------------- WhatsApp plumbing
def test_whatsapp_24h_window_uses_template_outside():
    now = time.time()
    assert outbound.wa_plan(now - 3600, "delivered", now) == "text"
    assert outbound.wa_plan(now - 30 * 3600, "delivered", now) == "template"
    assert outbound.wa_plan(None, "no_such_kind", now) == "skip"
    p = outbound.wa_template_payload("201011112222", "ta2keed_delivered", ["منى", "NB-1001"])
    assert p["type"] == "template" and p["template"]["components"][0]["parameters"][1]["text"] == "NB-1001"


def test_whatsapp_webhook_signature(monkeypatch):
    from ta2keed.config import settings
    from ta2keed.server import app
    monkeypatch.setattr(settings, "wa_app_secret", "s3cret")
    body = json.dumps({"entry": []}).encode()
    sig = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    with TestClient(app) as c:
        assert c.post("/webhook/whatsapp", content=body, headers={"x-hub-signature-256": "sha256=bad"}).status_code == 401
        assert c.post("/webhook/whatsapp", content=body, headers={"x-hub-signature-256": sig}).status_code == 200


def test_whatsapp_inbound_end_to_end(monkeypatch):
    """Simulated Meta webhook -> agent -> replies captured (no network)."""
    import asyncio
    from ta2keed import channels
    sent = []

    async def fake_send(to, text):
        sent.append((to, text))

    async def noop(*a, **k):
        return None
    monkeypatch.setattr(channels, "wa_send", fake_send)
    monkeypatch.setattr(channels, "wa_mark_read", noop)

    def wa_msg(mid, text):
        return {"entry": [{"changes": [{"value": {"messages": [
            {"id": mid, "from": "201011112222", "type": "text", "text": {"body": text}}]}}]}]}

    asyncio.run(channels.wa_handle(wa_msg("m1", "عايزة شنطة كروس سودا")))
    asyncio.run(channels.wa_handle(wa_msg("m1", "عايزة شنطة كروس سودا")))   # Meta retry -> ignored
    assert len(sent) == 1 and sent[0][0] == "201011112222"
    conv = db.get_conversation("whatsapp", "201011112222")
    assert conv["draft"]["phone_hint"] == "01011112222"                   # phone read from the WhatsApp number


def test_owner_whatsapp_commands(monkeypatch):
    import asyncio
    from ta2keed import channels
    from ta2keed.config import settings
    monkeypatch.setattr(settings, "owner_whatsapp", "201000000001")
    sent = []

    async def fake_send(to, text):
        sent.append(text)

    async def noop(*a, **k):
        return None
    monkeypatch.setattr(channels, "wa_send", fake_send)
    monkeypatch.setattr(channels, "wa_mark_read", noop)
    asyncio.run(channels.wa_handle({"entry": [{"changes": [{"value": {"messages": [
        {"id": "o1", "from": "201000000001", "type": "text", "text": {"body": "ملخص"}}]}}]}]}))
    assert "ملخص اليوم" in sent[0]
    assert float(db.kv_get("owner_last_inbound")) > 0                      # owner's 24h window is open


def test_api_delivery_endpoints():
    from ta2keed.server import app
    with TestClient(app) as c:
        for t in ["عايزة شنطة كروس بيج", "اسمي ياسمين حسن ورقمي 01122223333",
                  "العنوان الدقي شارع التحرير عمارة 20 الدور 3", "لا شكرا", "تمام"]:
            c.post("/api/chat", json={"user": "api-d", "text": t})
        oid = c.get("/api/orders").json()[0]["id"]
        tracking = c.get("/api/orders").json()[0]["tracking"]
        assert c.post(f"/api/orders/{oid}/advance").json()["status"] == "picked_up"
        r = c.post("/webhook/bosta", json={"data": {"trackingNumber": tracking, "state": 41}}).json()
        assert r["status"] == "out_for_delivery" and r["customer_notified"]
        msgs = c.get("/api/messages", params={"user": "api-d"}).json()["messages"]
        assert msgs and msgs[-1]["meta"]["kind"] == "out_for_delivery"
        r = c.post("/webhook/courier", json={"order_id": oid, "status": "delivered"}).json()
        assert r["status"] == "delivered"
        assert len(c.get("/api/scheduled").json()) == 2
        assert len(c.post("/api/followups/fast-forward").json()["sent"]) == 2
        assert "ملخص اليوم" in c.get("/api/digest").text
