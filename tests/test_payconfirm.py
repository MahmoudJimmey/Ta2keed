"""Owner payment confirmation: a screenshot alone never ships an order."""
import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ta2keed import agent, db, payconfirm
from ta2keed.scenarios import SCENARIOS

RECEIPTS = Path(__file__).resolve().parent.parent / "data" / "receipts"
OK = (RECEIPTS / "receipt_ok.png").read_bytes()


def to_deposit(user="reem"):
    for t in ["عايزة 2 فستان صيفي مقاس M بينك", "ريم عادل 01288889999 فيصل", "جنب الجامع", "لا", "تمام بس هفكر"]:
        agent.handle("test", user, t)
    conv = db.get_conversation("test", user)
    assert conv["state"] == "DEPOSIT"
    return conv


def proactive(conv_id):
    return [m for m in db.q("SELECT * FROM messages WHERE conv_id=? AND role='agent' ORDER BY id", (conv_id,))
            if json.loads(m["meta"]).get("proactive")]


def test_valid_screenshot_waits_for_owner_nothing_ships():
    conv = to_deposit()
    r = agent.handle("test", "reem", image=OK)
    assert "بنراجع" in r[0]
    o = db.one("SELECT * FROM orders")
    assert o["status"] == "awaiting_owner_confirm" and o["tracking"] is None and o["deposit_paid"] == 0
    chk = payconfirm.pending()[0]
    assert chk["order_id"] == o["id"] and chk["amount"] == 100 and chk["reference"] == "702915384462" and chk["has_image"]
    alert = db.one("SELECT data FROM events WHERE type='owner_alert' ORDER BY id DESC")
    d = json.loads(alert["data"])
    assert d["kind"] == "payment_check" and chk["code"] in d["text"] and "مش هيتشحن" in d["text"]
    # customer nudging meanwhile doesn't ship anything
    assert "بنراجع" in agent.handle("test", "reem", "ها وصل؟")[0]
    assert db.get_conversation("test", "reem")["state"] == "OWNER_CHECK"


def test_owner_approves_then_ships_and_customer_told():
    conv = to_deposit()
    agent.handle("test", "reem", image=OK)
    chk = payconfirm.pending()[0]
    res = payconfirm.decide(chk["id"], True, by="test")
    assert res["approved"]
    o = db.one("SELECT * FROM orders")
    assert o["status"] == "shipped" and o["deposit_paid"] == 100 and o["tracking"]
    msg = proactive(conv["id"])[-1]["text"]
    assert "وصلنا التحويل" in msg and o["tracking"] in msg
    assert db.get_conversation("test", "reem")["state"] == "CONFIRMED"
    # a second click is harmless
    assert payconfirm.decide(chk["id"], True, by="test")["already"]
    assert db.one("SELECT COUNT(*) n FROM events WHERE type='shipment_created'")["n"] == 1


def test_owner_rejects_order_held_customer_asked_again():
    conv = to_deposit()
    agent.handle("test", "reem", image=OK)
    chk = payconfirm.pending()[0]
    res = payconfirm.decide(chk["id"], False, by="test")
    assert res["ok"] and not res["approved"]
    o = db.one("SELECT * FROM orders")
    assert o["status"] == "awaiting_deposit" and o["tracking"] is None
    assert "موصلش" in proactive(conv["id"])[-1]["text"]
    assert db.get_conversation("test", "reem")["state"] == "DEPOSIT"
    assert db.one("SELECT status FROM payments WHERE id=?", (chk["payment_id"],))["status"] == "fraud"


def test_same_screenshot_cannot_be_reused_while_pending():
    to_deposit("reem")
    agent.handle("test", "reem", image=OK)
    for t in ["عايزة عباية كريب مقاس M كحلي", "نادية فؤاد 01599990000 اسيوط", "شارع الثورة", "لا", "تمام"]:
        agent.handle("test", "cheater", t)
    r = agent.handle("test", "cheater", image=OK)
    assert "اتستخدم قبل كده" in r[0]
    assert len(payconfirm.pending()) == 1


def test_owner_text_reply_with_code():
    to_deposit()
    agent.handle("test", "reem", image=OK)
    code = payconfirm.pending()[0]["code"]
    assert payconfirm.handle_owner_reply("تم") is None                 # no code -> not a decision
    assert payconfirm.handle_owner_reply("تم 0000") is None            # wrong code
    res = payconfirm.handle_owner_reply(f"تم {code}")
    assert res["approved"] and db.one("SELECT status FROM orders")["status"] == "shipped"


def test_owner_text_reject_with_code_arabic_digits():
    to_deposit()
    agent.handle("test", "reem", image=OK)
    code = payconfirm.pending()[0]["code"]
    arabic = code.translate(str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩"))
    res = payconfirm.handle_owner_reply(f"لا {arabic}")
    assert res["ok"] and not res["approved"]


def test_telegram_button_only_works_for_owner(monkeypatch):
    from ta2keed import channels
    monkeypatch.setenv("OWNER_TELEGRAM_CHAT_ID", "555")
    calls = []

    async def fake_call(c, method, **kw):
        calls.append((method, kw))
        return {"ok": True}
    monkeypatch.setattr(channels, "tg_call", fake_call)
    to_deposit()
    agent.handle("test", "reem", image=OK)
    cid = payconfirm.pending()[0]["id"]
    stranger = {"id": "q1", "from": {"id": 999}, "data": f"pay:{cid}:yes", "message": {"chat": {"id": 999}, "message_id": 1}}
    assert asyncio.run(channels.handle_tg_callback(None, stranger)) is None
    assert db.one("SELECT status FROM orders")["status"] == "awaiting_owner_confirm"
    owner = {"id": "q2", "from": {"id": 555}, "data": f"pay:{cid}:yes", "message": {"chat": {"id": 555}, "message_id": 2}}
    out = asyncio.run(channels.handle_tg_callback(None, owner))
    assert out["approved"] and db.one("SELECT status FROM orders")["status"] == "shipped"
    assert any(m == "editMessageReplyMarkup" for m, _ in calls)             # buttons removed after answering


def test_whatsapp_owner_button_reply(monkeypatch):
    from ta2keed import channels
    monkeypatch.setenv("OWNER_WHATSAPP", "201000000001")
    sent = []

    async def fake_send(to, text):
        sent.append(text)

    async def noop(*a, **k):
        return None
    monkeypatch.setattr(channels, "wa_send", fake_send)
    monkeypatch.setattr(channels, "wa_mark_read", noop)
    to_deposit()
    agent.handle("test", "reem", image=OK)
    cid = payconfirm.pending()[0]["id"]
    payload = {"entry": [{"changes": [{"value": {"messages": [{"id": "w1", "from": "201000000001", "type": "interactive",
               "interactive": {"type": "button_reply", "button_reply": {"id": f"pay:{cid}:no", "title": "❌ موصلش"}}}]}}]}]}
    asyncio.run(channels.wa_handle(payload))
    assert "متوقف" in sent[-1] and db.one("SELECT status FROM orders")["status"] == "awaiting_deposit"


def test_reminders_then_stop():
    to_deposit()
    agent.handle("test", "reem", image=OK)
    chk = payconfirm.pending()[0]
    t0 = chk["asked_at"]
    assert payconfirm.remind_due(t0 + 10 * 60) == 0
    assert payconfirm.remind_due(t0 + 31 * 60) == 1
    assert payconfirm.remind_due(t0 + 32 * 60) == 0
    assert payconfirm.remind_due(t0 + 181 * 60) == 1
    assert payconfirm.remind_due(t0 + 999 * 60) == 0
    reminders = [e for e in db.q("SELECT data FROM events WHERE type='owner_alert'") if "تذكير" in json.loads(e["data"])["text"]]
    assert len(reminders) == 2


def test_customer_cancel_voids_check():
    to_deposit()
    agent.handle("test", "reem", image=OK)
    agent.handle("test", "reem", "الغي")
    assert payconfirm.pending() == []
    assert db.one("SELECT status FROM payment_checks")["status"] == "void"


def test_can_be_turned_off_in_policy(monkeypatch):
    from ta2keed import config
    s = config.store()
    s["policy"]["owner_payment_confirmation"] = False
    to_deposit()
    agent.handle("test", "reem", image=OK)
    assert db.one("SELECT status FROM orders")["status"] == "shipped"
    s["policy"]["owner_payment_confirmation"] = True


def test_dashboard_api():
    from ta2keed.server import app
    to_deposit()
    agent.handle("test", "reem", image=OK)
    with TestClient(app) as c:
        rows = c.get("/api/payment-checks").json()
        assert len(rows) == 1 and rows[0]["customer_name"] == "ريم عادل"
        img = c.get(f"/api/payment-checks/{rows[0]['id']}/image")
        assert img.status_code == 200 and img.content[:4] == b"\x89PNG"
        r = c.post(f"/api/payment-checks/{rows[0]['id']}/decide", json={"approve": True}).json()
        assert r["approved"]
        assert c.get("/api/payment-checks").json() == []
