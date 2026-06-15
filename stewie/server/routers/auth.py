"""Auth router (ARCH-3 / #52 / #117): operator login + self-registration + self-service password.

Login is now PUBLIC and password-based -- email + the operator's own salted-PBKDF2 password
(server.operators) -> the existing 12 h HMAC token. The shared STEWIE_API_KEY never leaves the
server. A LEGACY bootstrap path is preserved: an allowlisted email with no password yet may still
mint a token by presenting the shared key (or a valid token/Tailscale identity), so the founding
directors are not locked out mid-migration; that token is flagged must_set_password. Auth deps
come from server.deps; the token/whitelist/role machinery from server.auth -- no app-module import.
"""
from __future__ import annotations

import hmac
import os
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from stewie.server.deps import CSRF_COOKIE, SESSION_COOKIE, _env, _truthy, require_auth
from stewie.server.ratelimit import RateLimiter, client_ip
from stewie.server.services import log_event

router = APIRouter()

# S-07: conservative field caps at the typed-contract boundary. A login/registration password is a
# human secret -- a few hundred chars is already generous; refusing megabyte inputs keeps PBKDF2 (and
# the JSON-rewrite-per-mutation cost) bounded. The email cap mirrors operators._MAX_EMAIL_LEN.
_MAX_EMAIL_LEN = 254
_MAX_PASSWORD_LEN = 256


class LoginRequest(BaseModel):
    email: str = Field(default="", max_length=_MAX_EMAIL_LEN)
    password: str | None = Field(default=None, max_length=_MAX_PASSWORD_LEN)


class RegisterRequest(BaseModel):
    email: str = Field(default="", max_length=_MAX_EMAIL_LEN)
    password: str = Field(default="", max_length=_MAX_PASSWORD_LEN)


class PasswordRequest(BaseModel):
    new_password: str = Field(default="", max_length=_MAX_PASSWORD_LEN)
    old_password: str | None = Field(default=None, max_length=_MAX_PASSWORD_LEN)


# S-07: per-IP / per-account fixed-window limiters (dependency-free, process-local -- one worker).
# Defaults are abuse-control caps, overridable via env for tests/tuning.
def _rl_max() -> int:
    return int(os.environ.get("STEWIE_AUTH_RATE_MAX", "10"))


def _rl_window() -> float:
    return float(os.environ.get("STEWIE_AUTH_RATE_WINDOW_S", "60"))


_login_ip_limiter = RateLimiter(_rl_max(), _rl_window())
_login_acct_limiter = RateLimiter(_rl_max(), _rl_window())
_register_ip_limiter = RateLimiter(_rl_max(), _rl_window())


def _registration_open() -> bool:
    # SEC-06: fail CLOSED. An internet-facing deployment must not accept self-service enrollment unless an
    # operator explicitly opts in (STEWIE_REGISTRATION=1). The prior `!= "0"` default left registration OPEN
    # on any host that did not think to disable it -- the wrong fail-direction for a public service.
    return os.environ.get("STEWIE_REGISTRATION", "0") == "1"


def _legacy_authed(email: str, x_api_key: str | None, authorization: str | None,
                   tailscale: str | None, peer_ip: str | None = None) -> bool:
    """S-01: the password-less legacy bootstrap, IDENTITY-BOUND. The bootstrap may mint a token only
    for `email`, and it is authorized exactly two ways:

      1. The raw shared API key. The key carries no subject of its own, so the holder may claim any
         ALLOWLISTED email (this is the founding-director / automation bring-up path). Constant-time
         compare -> no timing oracle.
      2. A trusted-proxy identity (Tailscale) that EQUALS the requested email, accepted only from a
         verified proxy peer (S-03). A proxy identity for A may bootstrap only A's own account.

    A valid SESSION TOKEN is accepted ONLY when its subject EQUALS `email` (self-enrollment). Before
    S-01 any operator's token was taken as proof for an INDEPENDENTLY-supplied allowlisted email, so
    an operator could mint a DIRECTOR token; now a token for A can bootstrap only A's own account."""
    from stewie.server import auth as AUTH
    e = (email or "").strip().lower()
    # trusted-proxy identity must MATCH the requested email (no cross-identity) and come from a
    # verified proxy peer (S-03: a direct client cannot spoof the Tailscale header)
    ts = AUTH.tailscale_identity({"tailscale-user-login": tailscale or ""}, peer_ip=peer_ip)
    if ts and ts == e:
        return True
    supplied = x_api_key or (authorization or "").removeprefix("Bearer ").strip()
    # a session token bootstraps ONLY its own subject (no cross-identity escalation)
    if supplied:
        subj = AUTH.verify_token(supplied)
        if subj and subj == e:
            return True
    key = _env("API_KEY")
    if not key:
        return False
    # the RAW shared key carries no subject -> the holder may claim any allowlisted email
    return hmac.compare_digest(supplied.encode(), key.encode())


def _cookie_secure(request: Request) -> bool:
    """SEC-01: mark the cookies Secure on a real (HTTPS-terminated) deployment, but NOT on a plain-http
    loopback dev server / the in-process test client -- a Secure cookie would never be stored over http,
    locking dev out of its own session."""
    return _truthy(_env("TLS_TERMINATED")) or request.url.scheme == "https"


def _set_session_cookies(response: Response, request: Request, token: str) -> None:
    """SEC-01: issue the browser's credential as cookies, not a JSON body the page must persist.
    stewie_session is HttpOnly (XSS cannot read it); stewie_csrf is readable so the page can echo it in
    the X-CSRF-Token header (double-submit). Both SameSite=Strict + Secure (in production)."""
    from stewie.server import auth as AUTH
    secure = _cookie_secure(request)
    response.set_cookie(SESSION_COOKIE, token, max_age=int(AUTH.TOKEN_TTL_S), httponly=True,
                        secure=secure, samesite="strict", path="/")
    response.set_cookie(CSRF_COOKIE, secrets.token_urlsafe(32), max_age=int(AUTH.TOKEN_TTL_S),
                        httponly=False, secure=secure, samesite="strict", path="/")


def _token_response(email: str, *, must_set_password: bool,
                    response: Response | None = None, request: Request | None = None):
    from stewie.server import auth as AUTH
    token = AUTH.issue_token(email)
    # SEC-01: set the HttpOnly session + readable CSRF cookies for the browser path. The token is still
    # returned in the body for header-auth automation (CLI/CI); the browser ignores it and uses the cookie.
    if response is not None and request is not None:
        _set_session_cookies(response, request, token)
    return {"ok": True, "operator": email, "token": token,
            "ttl_s": AUTH.TOKEN_TTL_S, "role": AUTH.role_of(email),
            "must_set_password": must_set_password}


@router.get("/auth/config")
def auth_config():
    return {"ok": True,
            "operator_login": os.environ.get("STEWIE_OPERATOR_LOGIN", "1") != "0",
            "registration_open": _registration_open()}


@router.post("/auth/login")
def auth_login(body: LoginRequest, request: Request, response: Response,
               x_api_key: str | None = Header(default=None, alias="X-API-Key"),
               authorization: str | None = Header(default=None),
               tailscale_user_login: str | None = Header(default=None,
                                                         alias="Tailscale-User-Login")):
    """#52/#117: email + password -> a 12 h identity token (the shared key is NOT required).
    STEWIE_OPERATOR_LOGIN=0 disables the flow. Accounts with no password yet fall back to the
    legacy shared-key bootstrap (must_set_password=True). S-07: typed model (field caps) + per-IP /
    per-account rate limits so a failed-login burst cannot monopolize PBKDF2 / the single worker."""
    from stewie.server import auth as AUTH
    from stewie.server import operators as OPS
    if os.environ.get("STEWIE_OPERATOR_LOGIN", "1") == "0":
        return JSONResponse(status_code=403,
                            content={"ok": False, "error": "operator login is disabled "
                                     "(STEWIE_OPERATOR_LOGIN=0); use the API key"})
    email = body.email.strip().lower()
    password = body.password
    # S-07: rate-limit BEFORE the expensive credential path. An automation/API-key bootstrap (no
    # password) is exempt -- the key is already a bounded constant-time check, and CI must not 429.
    if not (x_api_key or authorization):
        ip = client_ip(request)
        if not _login_ip_limiter.allow(ip) or (email and not _login_acct_limiter.allow(email)):
            return JSONResponse(status_code=429,
                                content={"ok": False, "error": "too many login attempts; slow down"})

    if password is not None and str(password) != "":
        op = OPS.verify_credentials(email, str(password))
        if not op:
            # generic -- no account-existence / lockout leak
            return JSONResponse(status_code=403,
                                content={"ok": False, "error": "invalid credentials"})
        log_event(op, "auth.login", "password")
        return _token_response(op, must_set_password=False, response=response, request=request)

    # ---- legacy bootstrap: an allowlisted, password-less account proving the shared key (or its
    # OWN trusted-proxy identity). S-01: the bootstrap is bound to `email`; a session token cannot
    # mint a token for a different identity. ----
    _peer = request.client.host if request.client else None
    if not _legacy_authed(email, x_api_key, authorization, tailscale_user_login, peer_ip=_peer):
        raise HTTPException(status_code=401, detail="invalid or missing API key")
    if not AUTH.is_allowed(email):
        return JSONResponse(status_code=403,
                            content={"ok": False, "error": f"{email!r} is not a whitelisted operator"})
    if OPS.has_password(email):
        return JSONResponse(status_code=403,
                            content={"ok": False, "error": "this account has a password -- sign in with it"})
    log_event(email, "auth.login", "bootstrap")
    return _token_response(email, must_set_password=True, response=response, request=request)


@router.post("/auth/logout")
def auth_logout(request: Request, response: Response):
    """SEC-01: clear the browser's session + CSRF cookies. Idempotent and needs no prior auth (you can
    always sign yourself out). Best-effort: revoke the presented session token's jti so a stolen copy of
    the cookie value cannot be replayed after logout."""
    from stewie.server import auth as AUTH
    tok = request.cookies.get(SESSION_COOKIE)
    if tok:
        claims = AUTH.decode_claims(tok)
        if claims and claims.get("jti"):
            AUTH.revoke_jti(claims["jti"])
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return {"ok": True}


@router.post("/auth/register")
def auth_register(body: RegisterRequest, request: Request):
    """#117: self-service access request. Creates a PENDING operator account (the operator picks
    their own password); a director approves it in the admin panel before it can sign in. S-07: typed
    model (field caps) + a per-IP rate limit so the pending-account store cannot be flooded."""
    from stewie.server import operators as OPS
    if not _registration_open():
        return JSONResponse(status_code=403,
                            content={"ok": False, "error": "registration is closed"})
    if not _register_ip_limiter.allow(client_ip(request)):
        return JSONResponse(status_code=429,
                            content={"ok": False, "error": "too many registration attempts; slow down"})
    email = body.email.strip().lower()
    password = body.password
    try:
        rec = OPS.register(email, password)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
    log_event(email, "auth.register", "pending")
    return {"ok": True, "status": rec["status"],
            "message": "request received -- a director must approve this account before sign-in"}


@router.get("/auth/me")
def auth_me(identity: str = Depends(require_auth)):
    """The signed-in identity + role + whether a password has been set (drives the UI prompt)."""
    from stewie.server import auth as AUTH
    from stewie.server import operators as OPS
    return {"ok": True, "identity": identity, "role": AUTH.role_of(identity),
            "has_password": OPS.has_password(identity)}


@router.post("/auth/password")
def auth_set_password(body: PasswordRequest, identity: str = Depends(require_auth)):
    """#117: set or change one's OWN password. A first-time set (a bootstrap director, or an account
    with no password) needs no old password and PROMOTES the identity into a real active account
    preserving its role; a change requires the current password. S-07: typed model caps the password
    length so PBKDF2 cannot be fed attacker-sized input."""
    from stewie.server import auth as AUTH
    from stewie.server import operators as OPS
    if identity in ("api-key", "dev-open"):
        return JSONResponse(status_code=400,
                            content={"ok": False, "error": "an automation identity has no password"})
    new = body.new_password
    rec = OPS.get(identity)
    try:
        if rec is None:
            # bootstrap: a fallback-allowlist identity becomes a real active account (role preserved)
            OPS.create_active(identity, new, role=AUTH.role_of(identity), by=identity)
        elif OPS.has_password(identity):
            if not OPS.verify_old_password(identity, body.old_password or ""):
                return JSONResponse(status_code=403,
                                    content={"ok": False, "error": "current password is incorrect"})
            OPS.set_password(identity, new)
        else:
            OPS.set_password(identity, new)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
    log_event(identity, "auth.password", "set")
    return {"ok": True, "message": "password set"}
