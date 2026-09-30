"""Runtime configuration (env vars + store profile)."""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()


class Settings:
    db_path: str = os.getenv("TA2KEED_DB", str(ROOT / "data" / "ta2keed.db"))
    store_path: str = os.getenv("TA2KEED_STORE", str(ROOT / "data" / "store.json"))

    # LLM (optional). provider: offline | anthropic | openai
    llm_provider: str = os.getenv("LLM_PROVIDER", "offline").lower()
    llm_model: str = os.getenv("LLM_MODEL", "")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_base_url: str = os.getenv("LLM_BASE_URL", "")  # for OpenAI-compatible (Gemini, Groq, OpenRouter...)

    # Speech-to-text for voice notes (OpenAI-compatible /audio/transcriptions, e.g. Groq whisper)
    stt_base_url: str = os.getenv("STT_BASE_URL", "")
    stt_api_key: str = os.getenv("STT_API_KEY", "")
    stt_model: str = os.getenv("STT_MODEL", "whisper-large-v3")

    # Channels
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    owner_telegram_chat_id: str = os.getenv("OWNER_TELEGRAM_CHAT_ID", "")
    wa_verify_token: str = os.getenv("WHATSAPP_VERIFY_TOKEN", "ta2keed-verify")
    wa_access_token: str = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
    wa_phone_number_id: str = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")

    # Courier
    bosta_api_key: str = os.getenv("BOSTA_API_KEY", "")  # empty => mock courier

    @property
    def llm_enabled(self) -> bool:
        return self.llm_provider in ("anthropic", "openai") and bool(self.llm_api_key)


settings = Settings()


@lru_cache(maxsize=1)
def store() -> dict:
    return json.loads(Path(settings.store_path).read_text(encoding="utf-8"))


def product(sku: str) -> dict | None:
    return next((p for p in store()["products"] if p["sku"] == sku), None)
