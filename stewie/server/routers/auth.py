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

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse

from stewie.server.deps import _env, require_auth
from stewie.server.services import log_event

router = APIRouter()


def _registration_open() -> bool:
    return os.environ.get("STEWIE_REGISTRATION", "1") != "0"


def _legacy_authed(email: str, x_api_key: str | None, authorization: str | None,
                   tailscale: str | None) -> bool:
    """S-01: the password-less legacy bootstrap, IDENTITY-BOUND. The bootstrap may mint a token only
    for `email`, and it is authorized exactly two ways:

      1. The raw shared API key. The key carries no subject of its own, so the holder may claim any
         ALLOWLISTED email (this is the founding-director / automation bring-up path). Constant-time
         compare -> no timing oracle.
      2. A trusted-proxy identity (Tailscale) that EQUALS the requested email. A proxy identity for
         A may bootstrap only A's own account.

    A valid SESSION TOKEN is accepted ONLY when its subject EQUALS `email` (self-enrollment). Before
    S-01 any operator's token was taken as proof for an INDEPENDENTLY-supplied allowlisted email, so
    an operator could mint a DIRECTOR token; now a token for A can bootstrap only A's own account."""
    from stewie.server import auth as AUTH
    e = (email or "").strip().lower()
    # trusted-proxy identity must MATCH the requested email (no cross-identity)
    ts = AUTH.tailscale_identity({"tailscale-user-login": tailscale or ""})
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


def _token_response(email: str, *, must_set_password: bool):
    from stewie.server import auth as AUTH
    return {"ok": True, "operator": email, "token": AUTH.issue_token(email),
            "ttl_s": AUTH.TOKEN_TTL_S, "role": AUTH.role_of(email),
            "must_set_password": must_set_password}


@router.get("/auth/config")
def auth_config():
    return {"ok": True,
            "operator_login": os.environ.get("STEWIE_OPERATOR_LOGIN", "1") != "0",
            "registration_open": _registration_open()}


@router.post("/auth/login")
def auth_login(body: dict,
               x_api_key: str | None = Header(default=None, alias="X-API-Key"),
               authorization: str | None = Header(default=None),
               tailscale_user_login: str | None = Header(default=None,
                                                         alias="Tailscale-User-Login")):
    """#52/#117: email + password -> a 12 h identity token (the shared key is NOT required).
    STEWIE_OPERATOR_LOGIN=0 disables the flow. Accounts with no password yet fall back to the
    legacy shared-key bootstrap (must_set_password=True)."""
    from stewie.server import auth as AUTH
    from stewie.server import operators as OPS
    if os.environ.get("STEWIE_OPERATOR_LOGIN", "1") == "0":
        return JSONResponse(status_code=403,
                            content={"ok": False, "error": "operator login is disabled "
                                     "(STEWIE_OPERATOR_LOGIN=0); use the API key"})
    email = str(body.get("email", "")).strip().lower()
    password = body.get("password")

    if password is not None and str(password) != "":
        op = OPS.verify_credentials(email, str(password))
        if not op:
            # generic -- no account-existence / lockout leak
            return JSONResponse(status_code=403,
                                content={"ok": False, "error": "invalid credentials"})
        log_event(op, "auth.login", "password")
        return _token_response(op, must_set_password=False)

    # ---- legacy bootstrap: an allowlisted, password-less account proving the shared key (or its
    # OWN trusted-proxy identity). S-01: the bootstrap is bound to `email`; a session token cannot
    # mint a token for a different identity. ----
    if not _legacy_authed(email, x_api_key, authorization, tailscale_user_login):
        raise HTTPException(status_code=401, detail="invalid or missing API key")
    if not AUTH.is_allowed(email):
        return JSONResponse(status_code=403,
                            content={"ok": False, "error": f"{email!r} is not a whitelisted operator"})
    if OPS.has_password(email):
        return JSONResponse(status_code=403,
                            content={"ok": False, "error": "this account has a password -- sign in with it"})
    log_event(email, "auth.login", "bootstrap")
    return _token_response(email, must_set_password=True)


@router.post("/auth/register")
def auth_register(body: dict):
    """#117: self-service access request. Creates a PENDING operator account (the operator picks
    their own password); a director approves it in the admin panel before it can sign in."""
    from stewie.server import operators as OPS
    if not _registration_open():
        return JSONResponse(status_code=403,
                            content={"ok": False, "error": "registration is closed"})
    email = str(body.get("email", "")).strip().lower()
    password = str(body.get("password", ""))
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
def auth_set_password(body: dict, identity: str = Depends(require_auth)):
    """#117: set or change one's OWN password. A first-time set (a bootstrap director, or an account
    with no password) needs no old password and PROMOTES the identity into a real active account
    preserving its role; a change requires the current password."""
    from stewie.server import auth as AUTH
    from stewie.server import operators as OPS
    if identity in ("api-key", "dev-open"):
        return JSONResponse(status_code=400,
                            content={"ok": False, "error": "an automation identity has no password"})
    new = str(body.get("new_password", ""))
    rec = OPS.get(identity)
    try:
        if rec is None:
            # bootstrap: a fallback-allowlist identity becomes a real active account (role preserved)
            OPS.create_active(identity, new, role=AUTH.role_of(identity), by=identity)
        elif OPS.has_password(identity):
            if not OPS.verify_old_password(identity, str(body.get("old_password", ""))):
                return JSONResponse(status_code=403,
                                    content={"ok": False, "error": "current password is incorrect"})
            OPS.set_password(identity, new)
        else:
            OPS.set_password(identity, new)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
    log_event(identity, "auth.password", "set")
    return {"ok": True, "message": "password set"}
