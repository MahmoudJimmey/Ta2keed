"""Optional LLM layer (Anthropic or any OpenAI-compatible endpoint).

The agent never lets the LLM move money or change order state directly: the LLM only
(a) extracts structured fields, (b) reads payment screenshots, (c) answers free-form
product questions. All actions go through deterministic, audited tools in agent.py.
"""
from __future__ import annotations

import base64
import json
import re

import httpx

from .config import settings, store

TIMEOUT = 40


def _catalog_brief() -> str:
    lines = []
    for p in store()["products"]:
        lines.append(f"- {p['sku']}: {p['name_ar']} / {p['name_en']} — {p['price']} EGP; sizes={p['sizes'] or 'one-size'}; colors={p['colors'] or 'n/a'}")
    return "\n".join(lines)


def _chat(system: str, user_content, max_tokens: int = 600) -> str:
    if settings.llm_provider == "anthropic":
        model = settings.llm_model or "claude-sonnet-4-5"
        r = httpx.post(
            (settings.llm_base_url or "https://api.anthropic.com") + "/v1/messages",
            headers={"x-api-key": settings.llm_api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": model, "max_tokens": max_tokens, "system": system,
                  "messages": [{"role": "user", "content": user_content}]},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        return "".join(b.get("text", "") for b in r.json()["content"])
    # OpenAI-compatible (OpenAI, Gemini openai-compat, Groq, OpenRouter, local Ollama...)
    model = settings.llm_model or "gpt-4o-mini"
    base = settings.llm_base_url or "https://api.openai.com/v1"
    r = httpx.post(
        base.rstrip("/") + "/chat/completions",
        headers={"Authorization": f"Bearer {settings.llm_api_key}"},
        json={"model": model, "max_tokens": max_tokens, "temperature": 0,
              "messages": [{"role": "system", "content": system}, {"role": "user", "content": user_content}]},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}


EXTRACT_SYSTEM = """You extract e-commerce order details from Egyptian customers' chat messages
(Egyptian Arabic, Franco-Arabic, English, or transcribed voice notes).
Catalog:
{catalog}
Return ONLY JSON with any of these keys you can fill (omit unknown ones):
{{"items":[{{"sku":"...","qty":1,"size":"S|M|L|XL|null","color":"black|navy|beige|pink|white|olive|null"}}],
 "name":"...", "phone":"01xxxxxxxxx", "address":"full delivery address as written",
 "zone":"cairo|giza|alex|delta|canal|upper",
 "intent":"order|confirm|decline|cancel|question|payment|other",
 "question":"the customer's question if any"}}
Only include items the customer actually wants in THIS message."""


def extract(text: str, draft: dict) -> dict:
    if not settings.llm_enabled:
        return {}
    try:
        sys = EXTRACT_SYSTEM.format(catalog=_catalog_brief())
        user = f"Current draft order: {json.dumps(draft, ensure_ascii=False)}\nCustomer message: {text}"
        return _json(_chat(sys, user))
    except Exception as e:  # never let the LLM take the agent down
        return {"_error": str(e)}


ANSWER_SYSTEM = """You are {agent}, the WhatsApp sales assistant of {store} (Egyptian online fashion shop).
Reply in short, warm Egyptian Arabic (1-3 sentences). Never invent products, prices or policies.
Catalog:
{catalog}
Policies: cash on delivery; delivery {days} days; shipping fees by zone {zones}; InstaPay deposit may be requested for some orders.
After answering, gently steer back to completing the order."""


def answer(question: str, draft: dict) -> str | None:
    if not settings.llm_enabled:
        return None
    s = store()
    zones = {k: v["fee"] for k, v in s["shipping"]["zones"].items()}
    try:
        sys = ANSWER_SYSTEM.format(agent=s["store"]["agent_name_ar"], store=s["store"]["name_ar"],
                                   catalog=_catalog_brief(), days=s["policy"]["delivery_days"], zones=zones)
        return _chat(sys, f"Draft order: {json.dumps(draft, ensure_ascii=False)}\nCustomer: {question}", 300).strip()
    except Exception:
        return None


RECEIPT_SYSTEM = """You read Egyptian mobile-payment receipt screenshots (InstaPay, Vodafone Cash, bank apps).
Return ONLY JSON: {"is_receipt":true|false,"method":"instapay|vodafone_cash|bank|other","amount":number,
"reference":"transaction/reference number","recipient":"recipient name/handle/number shown","datetime":"as shown",
"status":"success|failed|pending","edited_suspicion":"none|low|high","notes":"short"}"""


def read_receipt(image: bytes, mime: str = "image/png") -> dict:
    if not settings.llm_enabled:
        return {}
    b64 = base64.b64encode(image).decode()
    try:
        if settings.llm_provider == "anthropic":
            content = [{"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}},
                       {"type": "text", "text": "Extract the receipt."}]
        else:
            content = [{"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                       {"type": "text", "text": "Extract the receipt."}]
        return _json(_chat(RECEIPT_SYSTEM, content, 400))
    except Exception as e:
        return {"_error": str(e)}


def transcribe(audio: bytes, filename: str = "voice.ogg") -> str | None:
    """Voice notes -> text via any OpenAI-compatible Whisper endpoint (Groq is free/fast)."""
    base = settings.stt_base_url or (settings.llm_base_url if settings.llm_provider == "openai" else "")
    key = settings.stt_api_key or (settings.llm_api_key if settings.llm_provider == "openai" else "")
    if not base or not key:
        return None
    try:
        r = httpx.post(base.rstrip("/") + "/audio/transcriptions", headers={"Authorization": f"Bearer {key}"},
                       files={"file": (filename, audio)}, data={"model": settings.stt_model, "language": "ar"},
                       timeout=60)
        r.raise_for_status()
        return r.json().get("text")
    except Exception:
        return None
