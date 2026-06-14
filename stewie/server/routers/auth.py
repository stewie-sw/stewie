"""Auth router (ARCH-3 / §21): the operator login flow + the auth-config probe. Self-contained --
uses server.deps for require_auth and stewie.server.auth for the token/whitelist; no app-module import.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from stewie.server.deps import require_auth

router = APIRouter()


@router.get("/auth/config")
def auth_config():
    return {"ok": True, "operator_login": os.environ.get("STEWIE_OPERATOR_LOGIN", "1") != "0"}


@router.post("/auth/login")
def auth_login(body: dict, _auth: str = Depends(require_auth)):
    """#52: email + the API key -> a 12 h identity token. The email MUST be whitelisted.
    STEWIE_OPERATOR_LOGIN=0 disables the flow (key-only deployments; Aaron 2026-06-10)."""
    from stewie.server import auth as AUTH
    if os.environ.get("STEWIE_OPERATOR_LOGIN", "1") == "0":
        return JSONResponse(status_code=403,
                            content={"ok": False, "error": "operator login is disabled "
                                     "(STEWIE_OPERATOR_LOGIN=0); use the API key"})
    email = str(body.get("email", "")).strip().lower()
    if not AUTH.is_allowed(email):
        return JSONResponse(status_code=403,
                            content={"ok": False, "error": f"{email!r} is not a whitelisted operator"})
    return {"ok": True, "operator": email, "token": AUTH.issue_token(email),
            "ttl_s": AUTH.TOKEN_TTL_S}
