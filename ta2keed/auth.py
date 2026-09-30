"""Owner login for the dashboard and wizard.

Rules
  * Webhooks (/webhook/*) and /health are always public (Meta, Bosta and uptime checks must reach them).
  * If ADMIN_PASSWORD is set (env or wizard): everything else needs a login (signed cookie, 30 days).
  * If no password is set yet:
        - requests from this computer (localhost) are allowed, so `run.bat` just works;
        - remote requests need the one-time setup link printed in the server log (/setup?token=...),
          whose first step is creating the password. Nobody can claim a fresh online server without the log.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse

from . import db
from .config import data_dir, settings

COOKIE = "ta2keed_session"
MAX_AGE = 30 * 86400
PUBLIC_PREFIXES = ("/webhook/", "/health", "/login", "/static/")
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}


def _secret() -> bytes:
    f = data_dir() / ".session_secret"
    if not f.exists():
        f.write_text(secrets.token_hex(32), encoding="utf-8")
        try:
            os.chmod(f, 0o600)
        except OSError:
            pass
    return f.read_text(encoding="utf-8").strip().encode()


def secure_cookie(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"


def setup_token() -> str:
    tok = db.kv_get("setup_token")
    if not tok:
        tok = secrets.token_urlsafe(18)
        db.kv_set("setup_token", tok)
    return tok


def hash_password(pw: str) -> str:
    salt = secrets.token_hex(8)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 120_000).hex()
    return f"pbkdf2${salt}${dk}"


def check_password(pw: str) -> bool:
    stored = settings.admin_password or ""
    if not stored:
        return False
    if stored.startswith("pbkdf2$"):
        _, salt, dk = stored.split("$", 2)
        cand = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 120_000).hex()
        return hmac.compare_digest(cand, dk)
    return hmac.compare_digest(pw, stored)  # plain value from env (e.g. Render generateValue)


def make_session() -> str:
    exp = str(int(time.time()) + MAX_AGE)
    sig = hmac.new(_secret(), exp.encode(), hashlib.sha256).hexdigest()
    return f"{exp}.{sig}"


def valid_session(val: str | None) -> bool:
    if not val or "." not in val:
        return False
    exp, sig = val.split(".", 1)
    good = hmac.new(_secret(), exp.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, good) and exp.isdigit() and int(exp) > time.time()


def is_local(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host in LOCAL_HOSTS


def auth_enabled() -> bool:
    return os.environ.get("TA2KEED_AUTH", "on").lower() not in ("off", "0", "false")


def allowed(request: Request) -> bool:
    path = request.url.path
    if not auth_enabled() or path.startswith(PUBLIC_PREFIXES):
        return True
    if settings.admin_password:
        return valid_session(request.cookies.get(COOKIE))
    if is_local(request):
        return True
    tok = request.query_params.get("token") or request.cookies.get("ta2keed_setup")
    return bool(tok) and hmac.compare_digest(tok, setup_token())


async def middleware(request: Request, call_next):
    if allowed(request):
        resp = await call_next(request)
        tok = request.query_params.get("token")
        if tok and not settings.admin_password and hmac.compare_digest(tok, setup_token()):
            resp.set_cookie("ta2keed_setup", tok, max_age=86400, httponly=True, samesite="strict",
                            secure=secure_cookie(request))
        return resp
    if request.url.path.startswith("/api/"):
        return JSONResponse({"error": "login required"}, status_code=401)
    if not settings.admin_password:
        return JSONResponse({"error": "This Ta2keed server has not been set up yet. Open the setup link printed in "
                                      "the server log (it looks like /setup?token=...)."}, status_code=403)
    return RedirectResponse(f"/login?next={request.url.path}", status_code=303)
