"""Shared FastAPI dependencies + env helpers for the cockpit server (ARCH-3).

Extracted from server.py so the per-concern routers can import the auth dependencies without importing
the app module (which would cycle: server imports the routers to include them). Self-contained: stdlib
+ fastapi + a lazy stewie.server.auth import.
"""
from __future__ import annotations

import hmac
import os

from fastapi import Depends, Header, HTTPException, Request


def _env(name: str, default=None):
    """Read the STEWIE_<name> environment variable."""
    return os.environ.get(f"STEWIE_{name}", default)


def _truthy(v) -> bool:
    return bool(v) and str(v).strip().lower() in ("1", "true", "yes", "on")


def _is_loopback(request: Request) -> bool:
    """True for an in-process (ASGI TestClient) or loopback client. dev-open is permitted only here,
    so a STEWIE_DEV_OPEN flag accidentally left on in a (proxied) deployment still cannot be used by a
    remote client -- the backend behind nginx sees the proxy's container IP, not loopback."""
    c = getattr(request, "client", None)
    if c is None:
        return True
    return c.host in ("127.0.0.1", "::1", "localhost", "testclient")


def require_auth(request: Request,
                 x_api_key: str | None = Header(default=None, alias="X-API-Key"),
                 authorization: str | None = Header(default=None),
                 tailscale_user_login: str | None = Header(default=None,
                                                           alias="Tailscale-User-Login")) -> str:
    """N8 + #52 + audit C-01: identity-bearing auth on mutating routes, FAIL CLOSED.
    Accepted, in order: a WHITELISTED Tailscale identity (opt-in via STEWIE_TRUST_TAILSCALE=1
    behind `tailscale serve`), an HMAC session token from /auth/login (Bearer), or the raw API
    key (automation; identity "api-key"). When NO key is configured the route is LOCKED (503)
    unless STEWIE_DEV_OPEN is explicitly set AND the client is loopback/in-process -- a keyless
    deployment is no longer silently director-open. Returns the operator identity."""
    from stewie.server import auth as AUTH
    key = _env("API_KEY")
    if not key:
        if _truthy(_env("DEV_OPEN")) and _is_loopback(request):
            return "dev-open"
        raise HTTPException(status_code=503, detail=(
            "auth not configured: set STEWIE_API_KEY for authenticated access, or STEWIE_DEV_OPEN=1 "
            "on a loopback-only dev server. Privileged routes are locked (fail-closed)."))
    # S-03: only honor the Tailscale identity header from a verified proxy peer.
    _peer = request.client.host if request.client else None
    ts = AUTH.tailscale_identity({"tailscale-user-login": tailscale_user_login or ""}, peer_ip=_peer)
    if ts:
        return ts
    supplied = x_api_key or (authorization or "").removeprefix("Bearer ").strip()
    op = AUTH.verify_token(supplied)
    if op:
        return op
    if hmac.compare_digest(supplied.encode(), key.encode()):   # constant-time -> no timing oracle
        return "api-key"
    raise HTTPException(status_code=401, detail="invalid or missing API key")


def require_director(identity: str = Depends(require_auth)) -> str:
    """#68 [REQ:PO-04]: the truth/training surface is director-only."""
    from stewie.server import auth as AUTH
    if AUTH.role_of(identity) != "director":
        raise HTTPException(status_code=403,
                            detail=f"director role required (signed in as operator {identity!r})")
    return identity
