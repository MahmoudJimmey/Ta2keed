"""Setup wizard backend: read/save settings + shop profile, live connection tests, one-click helpers."""
from __future__ import annotations

import copy
import csv
import io
import re
import secrets
import time

import httpx

from . import db
from .config import FIELDS, save_store, save_wizard_values, settings, source_of, store, wizard_values

GRAPH = "https://graph.facebook.com/v21.0"

LLM_PRESETS = {
    "offline": {"provider": "offline", "base_url": "", "model": ""},
    "anthropic": {"provider": "anthropic", "base_url": "", "model": "claude-sonnet-4-5"},
    "openai": {"provider": "openai", "base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
    "gemini": {"provider": "openai", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
               "model": "gemini-2.5-flash"},
    "groq": {"provider": "openai", "base_url": "https://api.groq.com/openai/v1", "model": "llama-3.3-70b-versatile"},
    "openrouter": {"provider": "openai", "base_url": "https://openrouter.ai/api/v1", "model": "openai/gpt-4o-mini"},
}

# Meta rules: body can't start/end with a variable; examples are required for every variable.
WA_TEMPLATES = [
    ("ta2keed_out_for_delivery", "UTILITY",
     "أهلاً {{1}} 🚚 أوردرك {{2}} خرج مع المندوب النهارده. جهزي {{3}} ج كاش، ولو مش هتكوني موجودة ردي على الرسالة دي.",
     ["منى", "NB-1001", "950"]),
    ("ta2keed_delivered", "UTILITY", "يا {{1}}، أوردرك {{2}} وصل 🎉 نتمنى يعجبك!", ["منى", "NB-1001"]),
    ("ta2keed_delivery_failed", "UTILITY",
     "يا {{1}}، المندوب حاول يوصل أوردر {{2}} ومقدرش. ردي على الرسالة دي بالميعاد المناسب ليكي.", ["منى", "NB-1001"]),
    ("ta2keed_review_request", "UTILITY",
     "أهلاً {{1}} 🌸 أوردر {{2}} عجبك؟ قيّمينا من 1 لـ 5 برد على الرسالة دي.", ["منى", "NB-1001"]),
    ("ta2keed_reorder_offer", "MARKETING",
     "وحشتينا يا {{1}} 💕 خصم {{2}} على طلبك الجاي بكود {{3}} لمدة أسبوع. ابعتيلنا اسم المنتج ونسجله فوراً.",
     ["منى", "10%", "NOUR1234"]),
    ("ta2keed_owner_digest", "UTILITY",
     "ملخص يوم {{1}}: اتأكد {{2}} أوردر بقيمة {{3}} ج، اتسلم {{4}} وكاش متحصل {{5}} ج، ورفض {{6}}. التفاصيل في لوحة التحكم.",
     ["2026-10-01", "12", "9,400", "10", "7,900", "1"]),
    ("ta2keed_owner_alert", "UTILITY", "تنبيه من Ta2keed: {{1}} — افتحي لوحة التحكم للتفاصيل.",
     ["أوردر NB-1003 اترفض"]),
]


def mask(v: str) -> str:
    if not v:
        return ""
    return ("•" * 6) + v[-4:] if len(v) > 8 else "••••"


def public_url(request_base: str | None = None) -> str:
    if settings.public_url:
        return settings.public_url.rstrip("/")
    if request_base and not re.search(r"//(localhost|127\.0\.0\.1|\[::1\])", request_base):
        return request_base.rstrip("/")
    return ""


def owner_claim_code() -> str:
    code = db.kv_get("owner_claim_code")
    if not code:
        code = f"{secrets.randbelow(900000) + 100000}"
        db.kv_set("owner_claim_code", code)
    return code


def steps_status() -> dict:
    s = store()
    wiz = wizard_values()
    return {
        "admin": bool(settings.admin_password),
        "shop": bool(wiz.get("_shop_saved")) or s["store"]["name"] != "Nour Boutique",
        "products": bool(wiz.get("_products_saved")),
        "shipping": bool(wiz.get("_shipping_saved")),
        "ai": settings.llm_enabled,
        "whatsapp": bool(settings.wa_access_token and settings.wa_phone_number_id),
        "telegram": bool(settings.telegram_bot_token),
        "owner": bool(settings.owner_whatsapp or settings.owner_telegram_chat_id),
        "courier": bool(settings.bosta_api_key) or wiz.get("_courier_mode") == "own_driver",
        "numbers": bool(wiz.get("_numbers_saved")),
    }


def state(request_base: str | None = None) -> dict:
    fields = {}
    for attr, (key, default, secret) in FIELDS.items():
        val = getattr(settings, attr)
        fields[key] = {"value": mask(val) if secret else val, "set": bool(val), "secret": secret,
                       "source": source_of(key)}
    base = public_url(request_base)
    s = store()
    return {
        "fields": fields,
        "store": {k: copy.deepcopy(s.get(k)) for k in ("store", "policy", "shipping", "notifications", "economics", "products")},
        "store_is_demo": not wizard_values().get("_products_saved"),
        "steps": steps_status(),
        "public_url": base,
        "webhooks": {
            "whatsapp": f"{base}/webhook/whatsapp" if base else "",
            "bosta": f"{base}/webhook/bosta" if base else "",
            "courier": f"{base}/webhook/courier" if base else "",
        },
        "owner_claim_code": owner_claim_code(),
        "llm_presets": LLM_PRESETS,
        "courier_mode": wizard_values().get("_courier_mode", "bosta" if settings.bosta_api_key else "mock"),
        "demo_mode": settings.demo,
        "setup_complete": bool(wizard_values().get("_setup_complete")),
    }


# ------------------------------------------------------------------ saving

def _slug_sku(name: str, i: int) -> str:
    base = re.sub(r"[^A-Za-z0-9]", "", name.upper())[:4] or "ITEM"
    return f"P{i:02d}-{base}"


def _split(v) -> list[str]:
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return [x.strip() for x in re.split(r"[,،/|]", str(v or "")) if x.strip()]


def normalize_products(items: list[dict]) -> list[dict]:
    from .nlu import COLORS, normalize
    out, used = [], set()
    for i, p in enumerate(items, 1):
        name_ar, name_en = str(p.get("name_ar", "")).strip(), str(p.get("name_en", "")).strip()
        if not (name_ar or name_en):
            continue
        try:
            price = int(float(str(p.get("price", 0)).replace(",", "")))
        except ValueError:
            price = 0
        sku = str(p.get("sku") or "").strip() or _slug_sku(name_en or f"item{i}", i)
        while sku in used:
            sku += "X"
        used.add(sku)
        colors = []
        for c in _split(p.get("colors")):
            c2 = COLORS.get(normalize(c), c.lower())
            if c2 not in colors:
                colors.append(c2)
        kws = _split(p.get("keywords"))
        for w in (name_ar.split()[:1] + name_en.lower().split()[:1]):
            if w and w not in kws:
                kws.append(w)
        up = None
        if p.get("upsell_sku"):
            try:
                up = {"sku": str(p["upsell_sku"]).strip(), "price": int(float(p.get("upsell_price") or 0))}
            except ValueError:
                up = None
        elif isinstance(p.get("upsell"), dict):
            up = p["upsell"]
        out.append({"sku": sku, "name_ar": name_ar or name_en, "name_en": name_en or name_ar, "price": price,
                    "sizes": [s.upper() for s in _split(p.get("sizes"))], "colors": colors, "keywords": kws,
                    "upsell": up})
    skus = {p["sku"] for p in out}
    for p in out:
        if p["upsell"] and (p["upsell"]["sku"] not in skus or p["upsell"]["sku"] == p["sku"]):
            p["upsell"] = None
    return out


def parse_products_csv(text: str) -> list[dict]:
    """Columns (header row, any order): name_ar, name_en, price, sizes, colors, keywords, upsell_sku, upsell_price, sku."""
    rows = list(csv.DictReader(io.StringIO(text.strip().lstrip("\ufeff"))))
    return normalize_products([{k.strip().lower(): (v or "") for k, v in r.items() if k} for r in rows])


def save(payload: dict) -> dict:
    """payload = {"settings": {ENV_KEY: value}, "store": {section: {...}}, "flags": {...}}"""
    updates = {}
    env_locked = []
    known = {key: secret for key, _, secret in FIELDS.values()}
    for key, val in (payload.get("settings") or {}).items():
        if key not in known:
            continue
        if source_of(key) == "environment":
            env_locked.append(key)
            continue
        if known[key] and isinstance(val, str) and val.startswith("••"):
            continue  # masked value sent back unchanged
        if key == "ADMIN_PASSWORD" and val:
            from .auth import hash_password
            if len(val) < 8:
                raise ValueError("Password must be at least 8 characters")
            val = hash_password(val)
        updates[key] = (val.strip() if isinstance(val, str) else val)
    for flag, val in (payload.get("flags") or {}).items():
        if flag.startswith("_"):
            updates[flag] = val
    if updates:
        save_wizard_values(updates)

    sections = payload.get("store") or {}
    if sections:
        data = copy.deepcopy(store())
        for sec, val in sections.items():
            if sec == "products":
                prods = normalize_products(val)
                if not prods:
                    raise ValueError("Add at least one product")
                data["products"] = prods
                save_wizard_values({"_products_saved": True})
            elif sec in ("store", "policy", "shipping", "notifications", "economics") and isinstance(val, dict):
                data.setdefault(sec, {}).update(val)
                save_wizard_values({f"_{ {'store': 'shop', 'economics': 'numbers'}.get(sec, sec)}_saved": True})
        save_store(data)
    return {"ok": True, "saved": sorted(updates), "env_locked": env_locked, "steps": steps_status()}


# ------------------------------------------------------------------ live tests

def test_llm() -> dict:
    if not settings.llm_enabled:
        return {"ok": False, "message": "Choose a provider and paste an API key first."}
    from . import llm
    try:
        out = llm._chat("Reply with exactly: OK", "ping", 5)
        return {"ok": True, "message": f"Connected — model replied “{out.strip()[:40]}”."}
    except httpx.HTTPStatusError as e:
        return {"ok": False, "message": f"Provider said {e.response.status_code}: {e.response.text[:200]}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "message": f"Could not reach the provider: {e}"}


def test_whatsapp() -> dict:
    if not (settings.wa_access_token and settings.wa_phone_number_id):
        return {"ok": False, "message": "Paste the access token and phone number ID first."}
    try:
        r = httpx.get(f"{GRAPH}/{settings.wa_phone_number_id}",
                      params={"fields": "display_phone_number,verified_name,quality_rating"},
                      headers={"Authorization": f"Bearer {settings.wa_access_token}"}, timeout=20)
        if r.status_code >= 400:
            return {"ok": False, "message": f"Meta said {r.status_code}: {r.json().get('error', {}).get('message', r.text[:200])}"}
        d = r.json()
        return {"ok": True, "message": f"Connected to {d.get('verified_name', '?')} ({d.get('display_phone_number', '?')}), "
                                       f"quality {d.get('quality_rating', 'n/a')}."}
    except httpx.HTTPError as e:
        return {"ok": False, "message": f"Could not reach Meta: {e}"}


def test_whatsapp_send(to: str) -> dict:
    """Sends Meta's built-in hello_world template (works outside the 24h window, no approval needed)."""
    from .outbound import wa_post
    to = re.sub(r"\D", "", to or settings.owner_whatsapp or "")
    if not to:
        return {"ok": False, "message": "Enter a phone number (international format, e.g. 2010…)."}
    payload = {"messaging_product": "whatsapp", "to": to, "type": "template",
               "template": {"name": "hello_world", "language": {"code": "en_US"}}}
    ok = wa_post(payload)
    return {"ok": ok, "message": "Sent! Check WhatsApp on that phone." if ok else
            "Meta refused the message — on the test number, add this phone as a recipient first."}


def whatsapp_templates(create: bool = False) -> dict:
    if not (settings.wa_access_token and settings.wa_business_account_id):
        return {"ok": False, "message": "Paste the WhatsApp Business Account ID (WABA ID) first.", "templates": []}
    h = {"Authorization": f"Bearer {settings.wa_access_token}"}
    base = f"{GRAPH}/{settings.wa_business_account_id}/message_templates"
    created, errors = [], []
    try:
        existing = {t["name"]: t.get("status") for t in
                    httpx.get(base, params={"fields": "name,status", "limit": 200}, headers=h, timeout=20).json().get("data", [])}
        if create:
            for name, cat, body, ex in WA_TEMPLATES:
                if name in existing:
                    continue
                r = httpx.post(base, headers=h, timeout=20, json={
                    "name": name, "language": "ar", "category": cat,
                    "components": [{"type": "BODY", "text": body, "example": {"body_text": [ex]}}]})
                if r.status_code < 400:
                    created.append(name)
                    existing[name] = r.json().get("status", "PENDING")
                else:
                    errors.append(f"{name}: {r.json().get('error', {}).get('error_user_msg') or r.text[:150]}")
        rows = [{"name": n, "category": c, "status": existing.get(n, "missing")} for n, c, _, _ in WA_TEMPLATES]
        approved = sum(r["status"] == "APPROVED" for r in rows)
        msg = f"{approved}/{len(rows)} approved."
        if created:
            msg += f" Submitted {len(created)} for review (usually minutes to a few hours)."
        return {"ok": not errors, "message": msg + (" Errors: " + "; ".join(errors) if errors else ""), "templates": rows}
    except httpx.HTTPError as e:
        return {"ok": False, "message": f"Could not reach Meta: {e}", "templates": []}


def test_telegram() -> dict:
    if not settings.telegram_bot_token:
        return {"ok": False, "message": "Paste the bot token from @BotFather first."}
    try:
        r = httpx.get(f"https://api.telegram.org/bot{settings.telegram_bot_token}/getMe", timeout=20).json()
        if not r.get("ok"):
            return {"ok": False, "message": f"Telegram said: {r.get('description')}"}
        u = r["result"]["username"]
        return {"ok": True, "message": f"Connected to @{u}. Now send  /owner {owner_claim_code()}  to @{u} from your "
                                       "own Telegram to receive alerts and the daily summary.", "bot": u}
    except httpx.HTTPError as e:
        return {"ok": False, "message": f"Could not reach Telegram: {e}"}


def test_bosta() -> dict:
    if not settings.bosta_api_key:
        return {"ok": False, "message": "Paste your Bosta API key first (Bosta dashboard → Settings → API integration)."}
    try:
        r = httpx.get("https://app.bosta.co/api/v2/cities", headers={"Authorization": settings.bosta_api_key}, timeout=20)
        if r.status_code in (401, 403):
            return {"ok": False, "message": "Bosta rejected the key (401/403)."}
        return {"ok": r.status_code < 400, "message": f"Bosta answered {r.status_code}. "
                + ("Key looks valid." if r.status_code < 400 else r.text[:150])}
    except httpx.HTTPError as e:
        return {"ok": False, "message": f"Could not reach Bosta: {e}"}


def test_public_url(url: str) -> dict:
    url = (url or public_url() or "").rstrip("/")
    if not url.startswith("https://"):
        return {"ok": False, "message": "Meta needs an https:// address. Run  run.bat online  or deploy to a host."}
    try:
        t0 = time.time()
        r = httpx.get(url + "/health", timeout=15)
        ok = r.status_code == 200 and r.json().get("ok")
        return {"ok": bool(ok), "message": f"Reachable from the internet in {int((time.time() - t0) * 1000)} ms." if ok
                else f"Got {r.status_code} from {url}/health"}
    except (httpx.HTTPError, ValueError) as e:
        return {"ok": False, "message": f"Not reachable: {e}"}


def generate_secret() -> str:
    return secrets.token_urlsafe(24)
