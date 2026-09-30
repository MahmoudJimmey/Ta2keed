"""Security: secrets encrypted at rest, headers, CSRF, login rate limit, backup, customer export/erase."""
import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from ta2keed import agent, config, db


@pytest.fixture
def client():
    from ta2keed.server import app
    with TestClient(app) as c:
        yield c


def test_secrets_encrypted_on_disk_but_readable(client):
    client.post("/api/setup/save", json={"settings": {"BOSTA_API_KEY": "super-secret-bosta-key", "OWNER_WHATSAPP": "201000000001"}})
    raw = config.settings_file().read_text(encoding="utf-8")
    assert "super-secret-bosta-key" not in raw and "enc:v1:" in raw      # encrypted at rest
    assert "201000000001" in raw                                          # non-secrets stay readable
    assert config.settings.bosta_api_key == "super-secret-bosta-key"      # decrypted transparently
    assert (config.data_dir() / ".master.key").exists()


def test_env_master_key_and_rotation_is_safe(client, monkeypatch):
    monkeypatch.setenv("TA2KEED_SECRET_KEY", "key-one")
    config.save_wizard_values({"LLM_API_KEY": "sk-abc"})
    assert config.settings.llm_api_key == "sk-abc"
    monkeypatch.setenv("TA2KEED_SECRET_KEY", "different-key")
    assert config.settings.llm_api_key == ""                              # wrong key -> unset, never garbage


def test_security_headers(client):
    h = client.get("/api/orders").headers
    assert h["x-frame-options"] == "DENY" and h["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in h["content-security-policy"] and h["cache-control"] == "no-store"


def test_cross_site_post_blocked_but_webhooks_allowed(client):
    r = client.post("/api/setup/save", json={}, headers={"origin": "https://evil.example"})
    assert r.status_code == 403
    r = client.post("/webhook/courier", json={"order_id": "nope", "status": "delivered"}, headers={"origin": "https://bosta.co"})
    assert r.status_code == 404                                            # reached the handler (order not found)


def test_login_rate_limit(monkeypatch):
    from ta2keed import security
    from ta2keed.server import app
    monkeypatch.setenv("ADMIN_PASSWORD", "right-password-1")
    security._fails.clear()
    with TestClient(app) as c:
        for _ in range(8):
            assert c.post("/login", json={"password": "wrong"}).status_code == 401
        assert c.post("/login", json={"password": "right-password-1"}).status_code == 429
    security._fails.clear()


def test_backup_zip(client):
    agent.handle("test", "u1", "عايزة شنطة كروس سودا")
    r = client.get("/api/admin/backup")
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert "ta2keed.db" in z.namelist() and ".master.key" not in z.namelist()


def test_customer_export_and_erase(client):
    for t in ["عايزة شنطة كروس بيج", "اسمي ياسمين حسن ورقمي 01122223333",
              "العنوان الدقي شارع التحرير عمارة 20 الدور 3", "لا شكرا", "تمام"]:
        agent.handle("test", "yas", t)
    exp = client.get("/api/admin/customer/01122223333").json()
    assert exp["orders"] and exp["messages"]
    r = client.delete("/api/admin/customer/01122223333").json()
    assert r["orders_anonymised"] == 1
    o = db.one("SELECT * FROM orders")
    assert o["customer_phone"] == "[erased]" and o["address"] == "[erased]" and o["total"] > 0   # totals kept
    assert not db.q("SELECT * FROM messages WHERE text LIKE '%01122223333%'")
    assert db.customer("01122223333") is None
    ev = db.one("SELECT data FROM events WHERE type='customer_erased'")
    assert json.loads(ev["data"])["orders_anonymised"] == 1
