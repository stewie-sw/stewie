"""Shared FastAPI dependencies + env helpers for the cockpit server (ARCH-3).

Extracted from server.py so the per-concern routers can import the auth dependencies without importing
the app module (which would cycle: server imports the routers to include them). Self-contained: stdlib
+ fastapi + a lazy stewie.server.auth import.
"""
from __future__ import annotations

import hmac
import os

from fastapi import Depends, Header, HTTPException, Request

from stewie.server.ratelimit import RateLimiter


def _env(name: str, default=None):
    """Read the STEWIE_<name> environment variable."""
    return os.environ.get(f"STEWIE_{name}", default)


def _truthy(v) -> bool:
    return bool(v) and str(v).strip().lower() in ("1", "true", "yes", "on")


# SEC-01: the browser's session credential lives in these cookies, never in localStorage. The session
# cookie is HttpOnly (JS cannot read it); the CSRF cookie is readable so the page can echo it back in a
# double-submit header on state-changing requests.
SESSION_COOKIE = "stewie_session"
CSRF_COOKIE = "stewie_csrf"
_CSRF_SAFE_METHODS = ("GET", "HEAD", "OPTIONS", "TRACE")


def _enforce_csrf(request: Request) -> None:
    """SEC-01 double-submit CSRF. A state-changing request authenticated by the session COOKIE (the
    browser path) must echo the readable stewie_csrf cookie in the X-CSRF-Token header. Read-only
    methods are exempt; header-authenticated automation never reaches this check."""
    if request.method in _CSRF_SAFE_METHODS:
        return
    sent = request.headers.get("X-CSRF-Token", "")
    cookie = request.cookies.get(CSRF_COOKIE, "")
    if not cookie or not sent or not hmac.compare_digest(sent.encode(), cookie.encode()):
        raise HTTPException(status_code=403, detail="CSRF token missing or invalid")


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
    # Desktop local-trust: the bundled desktop app (Electron) sets STEWIE_DESKTOP=1 when it spawns the
    # sidecar on loopback, so the single-user app opens straight to the cockpit instead of an operator
    # login. The public/docker deploy NEVER sets this flag, so this branch cannot activate there;
    # loopback is an additional barrier, mirroring the STEWIE_DEV_OPEN flag+loopback gate above.
    if _truthy(_env("DESKTOP")) and _is_loopback(request):
        return "desktop-local"
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
    # SEC-01: an EXPLICIT header credential (Bearer session token / X-API-Key) is automation. It takes
    # precedence over the browser session cookie and is CSRF-exempt -- an attacker cannot set these
    # headers cross-site, and honouring an explicit header keeps every existing CLI/CI caller working.
    supplied = x_api_key or (authorization or "").removeprefix("Bearer ").strip()
    if supplied:
        op = AUTH.verify_token(supplied)
        if op:
            return op
        if hmac.compare_digest(supplied.encode(), key.encode()):   # constant-time -> no timing oracle
            return "api-key"
        raise HTTPException(status_code=401, detail="invalid or missing API key")
    # SEC-01: no explicit header -> fall back to the HttpOnly session cookie (the browser path). A
    # state-changing method authenticated this way must carry a matching double-submit CSRF token.
    cookie_tok = request.cookies.get(SESSION_COOKIE)
    if cookie_tok:
        op = AUTH.verify_token(cookie_tok)
        if op:
            _enforce_csrf(request)
            return op
    raise HTTPException(status_code=401, detail="invalid or missing API key")


def require_director(identity: str = Depends(require_auth)) -> str:
    """#68 [REQ:AG-02]: the truth/training surface is director-only."""
    from stewie.server import auth as AUTH
    if AUTH.role_of(identity) != "director":
        raise HTTPException(status_code=403,
                            detail=f"director role required (signed in as operator {identity!r})")
    return identity


def require_role(min_role: str):
    """AG-02 (PRD §7.12): a dependency FACTORY admitting an identity only if its role ranks at or
    above `min_role` on the guest<trainee<operator<director ladder. Role resolution reuses
    auth.role_of (so store accounts, env directors, and the api-key/dev-open automation identities
    resolve exactly as require_director sees them); the comparison fails CLOSED for an unknown role.
    Real rover-command + live-write routes gate on require_role("operator"); admin on
    require_role("director"). A typo'd `min_role` raises at import (fail-fast, never fail-open)."""
    from stewie.server import operators as OPS
    floor = OPS.role_rank(min_role)
    if floor < 0:
        raise ValueError(f"require_role: unknown min_role {min_role!r}")

    def _dep(identity: str = Depends(require_auth)) -> str:
        from stewie.server import auth as AUTH
        from stewie.server import operators as _OPS
        role = AUTH.role_of(identity)
        if _OPS.role_rank(role) < floor:
            raise HTTPException(
                status_code=403,
                detail=f"{min_role}+ role required (signed in as {role} {identity!r})")
        return identity

    return _dep


def namespace_for(identity: str, requested: str = "live") -> tuple[str, str | None]:
    """AG-07 (PRD §7.12): resolve (namespace, sandbox_owner) for a request. A sub-operator
    (trainee/guest) is CONFINED to their own sandbox -- they cannot read or write live regardless of
    what they ask for. An operator+ defaults to live but may target their own sandbox with ?ns=sandbox.
    The sandbox owner is always the caller (you only ever see your own sandbox)."""
    from stewie.server import auth as AUTH
    from stewie.server import operators as OPS
    if OPS.role_rank(AUTH.role_of(identity)) < OPS.role_rank("operator"):
        return "sandbox", identity
    if requested == "sandbox":
        return "sandbox", identity
    return "live", None


# ---- [REQ:EG-09] S-08 heavy-route quota (relocated from routers.plan to shared-core deps) ---------
# Home here in deps (shared-core, already imported by every auth-gated router) so BOTH the plan
# (mission-service) and gis_export (world-service) routers depend on it from core, not across services --
# the world->mission import-DAG back-edge the service-separation guard (EG-09) forbids.
def _heavy_quota_max() -> int:
    return int(os.environ.get("STEWIE_HEAVY_QUOTA_MAX", "30"))


def _heavy_quota_window() -> float:
    return float(os.environ.get("STEWIE_HEAVY_QUOTA_WINDOW_S", "60"))


_heavy_quota = RateLimiter(_heavy_quota_max(), _heavy_quota_window())


def heavy_quota(identity: str = Depends(require_auth)) -> str:
    """Auth + a per-identity heavy-route quota (S-08). Returns the identity; raises 429 when the
    identity exceeds its compute budget in the window. The limit is re-read from the env on each check
    (runtime-tunable; the shared limiter's bucket state persists) -- deps is imported early, so freezing
    the limit at import would ignore a later env override."""
    _heavy_quota.max_hits = _heavy_quota_max()
    _heavy_quota.window_s = _heavy_quota_window()
    if not _heavy_quota.allow(identity):
        raise HTTPException(status_code=429,
                            detail="per-identity compute quota exceeded for heavy planning; slow down")
    return identity
