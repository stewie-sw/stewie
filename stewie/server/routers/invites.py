"""Invite router (AG-03/04, PRD §7.12): a director MINTS a one-time, role-scoped, TTL-bounded invite
(`POST /admin/invite`, director-only per Open Decision 11); anyone holding the raw token REDEEMS it
(`POST /auth/invite/redeem`, public -- the token IS the credential) to create their own active account
and set their own password. The store keeps only the token's hash. No app-module import (no cycle)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from stewie.server import operators as OPS
from stewie.server.deps import require_role
from stewie.server.services import log_event

router = APIRouter()

_WEEK_S = 7 * 86400
_MAX_TTL_S = 90 * 86400


class InviteMintRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str = "operator"
    ttl_s: float = Field(default=_WEEK_S, gt=0, le=_MAX_TTL_S)
    max_uses: int = Field(default=1, ge=1, le=1000)


class InviteRedeemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=8, max_length=512)
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)


@router.post("/admin/invite")
def invite_mint(body: InviteMintRequest, identity: str = Depends(require_role("director"))):
    """AG-03: a director mints a one-time invite (Open Decision 11 = directors-only). Returns the raw
    token ONCE -> share it as `app.stewie.space/#invite=<token>`. Only the hash is stored."""
    try:
        token = OPS.create_invite(by=identity, role=body.role, ttl_s=body.ttl_s, max_uses=body.max_uses)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    log_event(identity, "invite.mint", body.role)
    return {"ok": True, "token": token, "role": body.role, "max_uses": body.max_uses}


@router.post("/auth/invite/redeem")
def invite_redeem(body: InviteRedeemRequest):
    """AG-04: redeem a one-time invite -> create an active account at the invite's role; the invitee
    sets their own password here. PUBLIC: the high-entropy token is the credential."""
    try:
        rec = OPS.redeem_invite(body.token, body.email, body.password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    log_event(rec["email"], "invite.redeem", rec.get("role", ""))
    return {"ok": True, "email": rec["email"], "role": rec.get("role", "operator")}
