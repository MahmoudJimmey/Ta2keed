"""HTTP hardening: security headers, CSRF-origin check, login rate-limit, request size cap."""
from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import Request
from fastapi.responses import JSONResponse

MAX_BODY = 12 * 1024 * 1024  # 12 MB (receipt photos / voice notes)
CSP = ("default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
       "script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")

_fails: dict[str, deque] = defaultdict(deque)
LOGIN_WINDOW, LOGIN_MAX = 15 * 60, 8


def client_ip(request: Request) -> str:
    # the LAST entry is the one added by our own proxy (Render/Cloudflare/Codespaces); earlier entries can be
    # forged by the client, so they must not be used for rate limiting
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[-1].strip() if fwd else (request.client.host if request.client else "?")


def login_blocked(ip: str) -> bool:
    q = _fails[ip]
    now = time.time()
    while q and now - q[0] > LOGIN_WINDOW:
        q.popleft()
    return len(q) >= LOGIN_MAX


def login_failed(ip: str) -> None:
    _fails[ip].append(time.time())


def login_ok(ip: str) -> None:
    _fails.pop(ip, None)


def _same_origin(request: Request) -> bool:
    origin = request.headers.get("origin") or request.headers.get("referer")
    if not origin:
        return True  # non-browser clients (curl, webhooks)
    o = origin.split("//", 1)[-1].split("/", 1)[0].lower()
    hosts = {(request.headers.get("x-forwarded-host") or "").lower(), request.headers.get("host", "").lower()}
    from .config import settings
    if settings.public_url:  # e.g. the Codespaces / Render / tunnel address
        hosts.add(settings.public_url.split("//", 1)[-1].split("/", 1)[0].lower())
    return o in hosts - {""}


async def middleware(request: Request, call_next):
    path = request.url.path
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        cl = request.headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > MAX_BODY:
            return JSONResponse({"error": "request too large"}, status_code=413)
        # Browser-originated writes must come from our own pages (blocks CSRF). Webhooks are server-to-server.
        if not path.startswith("/webhook/") and not _same_origin(request):
            return JSONResponse({"error": "cross-site request blocked"}, status_code=403)
    resp = await call_next(request)
    h = resp.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("X-Frame-Options", "DENY")
    h.setdefault("Referrer-Policy", "same-origin")
    h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    h.setdefault("Content-Security-Policy", CSP)
    if request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https":
        h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if path.startswith("/api/"):
        h.setdefault("Cache-Control", "no-store")
    return resp
