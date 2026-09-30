"""Setup wizard, settings precedence, owner login and deployment-safety tests."""
import os

import pytest
from fastapi.testclient import TestClient

from ta2keed import config, setup
from ta2keed.config import settings


@pytest.fixture
def client():
    from ta2keed.server import app
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_on(monkeypatch):
    monkeypatch.setenv("TA2KEED_AUTH", "on")


def test_settings_precedence_env_over_wizard(monkeypatch):
    config.save_wizard_values({"LLM_MODEL": "from-wizard"})
    assert settings.llm_model == "from-wizard"
    monkeypatch.setenv("LLM_MODEL", "from-env")
    assert settings.llm_model == "from-env"
    assert config.source_of("LLM_MODEL") == "environment"


def test_wizard_save_is_live_and_masks_secrets(client):
    r = client.post("/api/setup/save", json={"settings": {"TELEGRAM_BOT_TOKEN": "123456:ABCDEFGHIJ", "OWNER_WHATSAPP": "201000000009"}})
    assert r.status_code == 200 and "TELEGRAM_BOT_TOKEN" in r.json()["saved"]
    assert settings.telegram_bot_token == "123456:ABCDEFGHIJ"          # applied without restart
    st = client.get("/api/setup/state").json()
    assert st["fields"]["TELEGRAM_BOT_TOKEN"]["value"].startswith("••") and "ABCDEFGHIJ" not in str(st)
    assert st["fields"]["OWNER_WHATSAPP"]["value"] == "201000000009"
    # sending the masked value back must not overwrite the real secret
    client.post("/api/setup/save", json={"settings": {"TELEGRAM_BOT_TOKEN": st["fields"]["TELEGRAM_BOT_TOKEN"]["value"]}})
    assert settings.telegram_bot_token == "123456:ABCDEFGHIJ"
    assert client.get("/health").json()["owner_channels"] == ["whatsapp"]


def test_env_locked_fields_are_not_overwritten(client, monkeypatch):
    monkeypatch.setenv("BOSTA_API_KEY", "env-key")
    r = client.post("/api/setup/save", json={"settings": {"BOSTA_API_KEY": "wizard-key"}}).json()
    assert r["env_locked"] == ["BOSTA_API_KEY"] and settings.bosta_api_key == "env-key"


def test_shop_profile_and_products_save(client):
    from ta2keed import agent, db
    r = client.post("/api/setup/save", json={"store": {
        "store": {"name": "Salma Shoes", "name_ar": "سلمى شوز", "agent_name_ar": "سلمى"},
        "policy": {"instapay_handle": "salma@instapay"},
        "products": [
            {"name_ar": "صندل جلد", "name_en": "Leather Sandal", "price": "650", "sizes": "38, 39, 40", "colors": "اسود, بيج",
             "keywords": "صندل, صنادل, sandal", "upsell_sku": ""},
            {"name_ar": "شنطة ظهر", "name_en": "Backpack", "price": "480", "colors": "black"},
        ]}})
    assert r.status_code == 200, r.text
    s = config.store()
    assert s["store"]["name"] == "Salma Shoes" and s["policy"]["instapay_handle"] == "salma@instapay"
    sandal = s["products"][0]
    assert sandal["sizes"] == ["38", "39", "40"] and sandal["colors"] == ["black", "beige"] and sandal["price"] == 650
    # the bundled demo profile is untouched
    assert "Nour Boutique" in (config.ROOT / "data" / "store.json").read_text(encoding="utf-8")
    # the agent immediately sells the new catalogue
    reply = agent.handle("test", "salma-cust", "عايزة صندل مقاس 39 اسود")
    assert "الاسم" in reply[0]
    assert db.get_conversation("test", "salma-cust")["draft"]["items"][0]["size"] == "39"
    st = client.get("/api/setup/state").json()
    assert st["steps"]["shop"] and st["steps"]["products"]


def test_products_csv_import(client):
    csv_text = "name_ar,name_en,price,sizes,colors\nتيشيرت قطن,Cotton Tee,250,S / M / L,white / black\n"
    r = client.post("/api/setup/products-csv", content=csv_text.encode("utf-8"))
    ps = r.json()["products"]
    assert ps[0]["name_en"] == "Cotton Tee" and ps[0]["sizes"] == ["S", "M", "L"] and ps[0]["colors"] == ["white", "black"]
    assert "name_ar,name_en,price" in client.get("/api/setup/products-template.csv").text


def test_empty_products_rejected(client):
    assert client.post("/api/setup/save", json={"store": {"products": [{"name_ar": "", "name_en": ""}]}}).status_code == 400


def test_first_run_redirects_to_setup_then_skip(client):
    config.save_wizard_values({"_setup_skipped": None})
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/setup"
    client.post("/api/setup/save", json={"flags": {"_setup_skipped": True}})
    assert client.get("/", follow_redirects=False).status_code == 200


def test_demo_mode_off_hides_demo_tools(client):
    client.post("/api/setup/save", json={"settings": {"DEMO_MODE": "off"}})
    assert client.get("/api/scenarios").json() == {}
    assert client.post("/api/reset").status_code == 403
    assert client.get("/health").json()["demo"] is False


def test_llm_preset_and_test_without_key(client):
    client.post("/api/setup/save", json={"settings": {"LLM_PROVIDER": "openai", "LLM_BASE_URL": setup.LLM_PRESETS["gemini"]["base_url"]}})
    r = client.post("/api/setup/test/llm", json={}).json()
    assert r["ok"] is False and "API key" in r["message"]


def test_wizard_tests_report_missing_config(client):
    for what in ("whatsapp", "telegram", "bosta"):
        r = client.post(f"/api/setup/test/{what}", json={}).json()
        assert r["ok"] is False and r["message"]
    assert client.post("/api/setup/test/public-url", json={"url": "http://insecure"}).json()["ok"] is False


def test_webhook_urls_use_public_url(client):
    client.post("/api/setup/save", json={"settings": {"PUBLIC_URL": "https://shop.example.com/"}})
    st = client.get("/api/setup/state").json()
    assert st["webhooks"]["whatsapp"] == "https://shop.example.com/webhook/whatsapp"


def test_whatsapp_templates_meet_meta_rules():
    for name, cat, body, ex in setup.WA_TEMPLATES:
        n = body.count("{{")
        assert n == len(ex) and not body.startswith("{{") and not body.rstrip(" .!").endswith("}}"), name
        assert name.islower() and cat in ("UTILITY", "MARKETING")


# ---------------- auth
def test_local_access_without_password(client, auth_on):
    assert client.get("/api/orders").status_code == 200        # no password yet + local request -> allowed


def test_remote_requires_setup_token_then_password(auth_on, monkeypatch):
    from ta2keed import auth
    from ta2keed.server import app
    monkeypatch.setattr(auth, "is_local", lambda request: False)
    with TestClient(app) as c:
        assert c.get("/api/orders").status_code == 401
        assert c.get("/webhook/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "ta2keed-verify",
                                                  "hub.challenge": "7"}).text == "7"   # webhooks stay public
        assert c.get("/health").status_code == 200
        tok = auth.setup_token()
        assert c.get("/setup", params={"token": "wrong"}).status_code == 403
        assert c.get("/setup", params={"token": tok}).status_code == 200           # sets a setup cookie
        assert c.get("/api/setup/state").status_code == 200
        r = c.post("/api/setup/save", json={"settings": {"ADMIN_PASSWORD": "short"}})
        assert r.status_code == 400
        r = c.post("/api/setup/save", json={"settings": {"ADMIN_PASSWORD": "correct horse battery"}})
        assert r.status_code == 200 and settings.admin_password.startswith("pbkdf2$")
        assert c.get("/api/orders").status_code == 200                             # logged in by the save

    with TestClient(app) as c2:                                                    # a new browser
        assert c2.get("/api/orders").status_code == 401
        assert c2.get("/setup", params={"token": tok}).status_code in (303, 307, 200) and \
            c2.get("/api/setup/state").status_code == 401                          # token no longer works
        assert c2.post("/login", json={"password": "nope"}).status_code == 401
        assert c2.post("/login", json={"password": "correct horse battery"}).status_code == 200
        assert c2.get("/api/orders").status_code == 200


def test_env_plain_password_login(auth_on, monkeypatch):
    from ta2keed import auth
    from ta2keed.server import app
    monkeypatch.setenv("ADMIN_PASSWORD", "render-generated-123")
    monkeypatch.setattr(auth, "is_local", lambda request: False)
    with TestClient(app) as c:
        assert c.get("/", follow_redirects=False).status_code == 303
        assert c.post("/login", json={"password": "render-generated-123"}).status_code == 200
        assert c.get("/api/impact").status_code == 200


def test_telegram_owner_claim_code_is_stable():
    a, b = setup.owner_claim_code(), setup.owner_claim_code()
    assert a == b and len(a) == 6 and a.isdigit()


def test_data_dir_is_isolated():
    assert config.data_dir() == config.Path(os.environ["TA2KEED_DATA_DIR"])
