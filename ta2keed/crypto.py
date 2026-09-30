"""Encryption at rest for secrets (API keys, tokens) stored by the setup wizard.

Key source (first match wins):
  1. TA2KEED_SECRET_KEY env var (recommended on hosts: keep the key OUT of the data disk)
  2. <data dir>/.master.key, auto-generated with 0600 permissions

Values are stored as "enc:v1:<fernet token>" (AES-128-CBC + HMAC-SHA256). If the key is lost the
secrets can't be decrypted: the wizard just shows them as "not set" and they must be re-entered.
"""
from __future__ import annotations

import base64
import hashlib
import os
import secrets
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

PREFIX = "enc:v1:"
_cache: dict[str, Fernet] = {}


def _key_file(data_dir: Path) -> Path:
    return data_dir / ".master.key"


def _fernet(data_dir: Path) -> Fernet:
    env = os.environ.get("TA2KEED_SECRET_KEY")
    cache_key = f"env:{hashlib.sha256(env.encode()).hexdigest()}" if env else str(data_dir)
    if cache_key in _cache:
        return _cache[cache_key]
    if env:
        key = base64.urlsafe_b64encode(hashlib.sha256(env.encode()).digest())
    else:
        f = _key_file(data_dir)
        if not f.exists():
            f.write_bytes(Fernet.generate_key())
            try:
                os.chmod(f, 0o600)
            except OSError:
                pass
        key = f.read_bytes().strip()
    _cache[cache_key] = Fernet(key)
    return _cache[cache_key]


def encrypt(value: str, data_dir: Path) -> str:
    if not value or value.startswith(PREFIX):
        return value
    return PREFIX + _fernet(data_dir).encrypt(value.encode()).decode()


def decrypt(value: str, data_dir: Path) -> str:
    if not isinstance(value, str) or not value.startswith(PREFIX):
        return value
    try:
        return _fernet(data_dir).decrypt(value[len(PREFIX):].encode()).decode()
    except InvalidToken:
        return ""  # wrong/rotated key: treat as unset


def random_key() -> str:
    return secrets.token_urlsafe(32)
