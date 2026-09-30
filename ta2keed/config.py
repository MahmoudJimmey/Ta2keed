"""Runtime configuration.

Where a setting comes from (first match wins):
  1. real environment variables / .env   (hosting dashboards, Docker, CI — shown as "locked" in the wizard)
  2. the setup wizard                    ($TA2KEED_DATA_DIR/settings.json, written by /setup)
  3. built-in defaults

Settings are read live, so wizard changes apply without a restart.
The shop profile (catalogue, fees, policies) is $TA2KEED_DATA_DIR/store.json once the wizard saved it,
otherwise the bundled demo profile data/store.json. TA2KEED_DATA_DIR defaults to ./instance (gitignored);
on a host, point it at a persistent disk (Docker image uses /data).
"""
from __future__ import annotations

import json
import os
import threading
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


def data_dir() -> Path:
    d = Path(os.environ.get("TA2KEED_DATA_DIR") or ROOT / "instance")  # per-install data (gitignored)
    d.mkdir(parents=True, exist_ok=True)
    return d


# attribute -> (ENV_KEY, default, secret?)
FIELDS: dict[str, tuple[str, str, bool]] = {
    "llm_provider": ("LLM_PROVIDER", "offline", False),
    "llm_model": ("LLM_MODEL", "", False),
    "llm_api_key": ("LLM_API_KEY", "", True),
    "llm_base_url": ("LLM_BASE_URL", "", False),
    "stt_base_url": ("STT_BASE_URL", "", False),
    "stt_api_key": ("STT_API_KEY", "", True),
    "stt_model": ("STT_MODEL", "whisper-large-v3", False),
    "telegram_bot_token": ("TELEGRAM_BOT_TOKEN", "", True),
    "owner_telegram_chat_id": ("OWNER_TELEGRAM_CHAT_ID", "", False),
    "wa_verify_token": ("WHATSAPP_VERIFY_TOKEN", "ta2keed-verify", False),
    "wa_access_token": ("WHATSAPP_ACCESS_TOKEN", "", True),
    "wa_phone_number_id": ("WHATSAPP_PHONE_NUMBER_ID", "", False),
    "wa_app_secret": ("WHATSAPP_APP_SECRET", "", True),
    "wa_business_account_id": ("WHATSAPP_BUSINESS_ACCOUNT_ID", "", False),
    "owner_whatsapp": ("OWNER_WHATSAPP", "", False),
    "bosta_api_key": ("BOSTA_API_KEY", "", True),
    "courier_webhook_secret": ("COURIER_WEBHOOK_SECRET", "", True),
    "scheduler": ("SCHEDULER", "on", False),
    "demo_mode": ("DEMO_MODE", "on", False),
    "admin_password": ("ADMIN_PASSWORD", "", True),
    "public_url": ("PUBLIC_URL", "", False),
}

_lock = threading.RLock()


def secure_file(f: Path) -> None:
    try:
        os.chmod(f, 0o600)
    except OSError:
        pass


def settings_file() -> Path:
    return data_dir() / "settings.json"


def wizard_values() -> dict:
    f = settings_file()
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


SECRET_KEYS = {key for key, _, secret in FIELDS.values() if secret}


def save_wizard_values(updates: dict) -> dict:
    """Merge updates into settings.json (None/'' removes a key). Secrets are encrypted at rest."""
    from .crypto import encrypt
    with _lock:
        cur = wizard_values()
        for k, v in updates.items():
            if v is None or v == "":
                cur.pop(k, None)
            elif k in SECRET_KEYS and k != "ADMIN_PASSWORD":  # password is already a one-way hash
                cur[k] = encrypt(str(v), data_dir())
            else:
                cur[k] = v if isinstance(v, (dict, list, bool)) else str(v)
        f = settings_file()
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(f)
        try:
            os.chmod(f, 0o600)
        except OSError:
            pass
        return cur


def source_of(env_key: str) -> str:
    if env_key in os.environ:
        return "environment"
    if env_key in wizard_values():
        return "wizard"
    return "default"


class Settings:
    """Live view over env > wizard > defaults. Tests may monkeypatch attributes directly."""

    def __getattr__(self, name: str):
        if name == "db_path":
            return os.environ.get("TA2KEED_DB") or str(data_dir() / "ta2keed.db")
        if name == "store_path":
            if os.environ.get("TA2KEED_STORE"):
                return os.environ["TA2KEED_STORE"]
            custom = data_dir() / "store.json"
            return str(custom) if custom.exists() else str(ROOT / "data" / "store.json")
        if name not in FIELDS:
            raise AttributeError(name)
        key, default, secret = FIELDS[name]
        v = os.environ.get(key)
        if v is None:
            v = wizard_values().get(key, default)
            if secret:
                from .crypto import decrypt
                v = decrypt(v, data_dir())
        if name == "llm_provider":
            return (v or "offline").lower()
        return v

    def __setattr__(self, name, value):
        # Tests may monkeypatch a setting; restoring must not leave a stale shadow value behind.
        if name in FIELDS and value == FIELDS[name][1] and name in self.__dict__:
            del self.__dict__[name]
            return
        object.__setattr__(self, name, value)

    @property
    def scheduler_enabled(self) -> bool:
        return str(self.scheduler).lower() not in ("0", "off", "false", "no")

    @property
    def demo(self) -> bool:
        return str(self.demo_mode).lower() not in ("0", "off", "false", "no")

    @property
    def llm_enabled(self) -> bool:
        return self.llm_provider in ("anthropic", "openai") and bool(self.llm_api_key)


settings = Settings()


@lru_cache(maxsize=1)
def store() -> dict:
    return json.loads(Path(settings.store_path).read_text(encoding="utf-8"))


def save_store(data: dict) -> None:
    """Write the shop profile to the data dir (keeps the bundled demo profile untouched)."""
    with _lock:
        f = data_dir() / "store.json"
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(f)
        store.cache_clear()


def product(sku: str) -> dict | None:
    return next((p for p in store()["products"] if p["sku"] == sku), None)
