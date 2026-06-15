"""Operator-administration router (ARCH-3 / #117): the director-only account panel.

List / approve / revoke / re-role / reset-password / delete operator accounts (server.operators).
Every route is director-gated (server.deps.require_director) and audit-logged (server.services).
A last-active-director guard refuses any change that would drop the active-director count to zero
(no self-lockout). The audit-log view reuses the existing director-only /events endpoint.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from stewie.server.deps import require_director
from stewie.server.services import log_event

router = APIRouter()


def _active_directors() -> list:
    from stewie.server import operators as OPS
    return [r for r in OPS.list_all() if r["status"] == "active" and r["role"] == "director"]


def _guard_last_director(email: str, *, still_director_after: bool) -> None:
    """Refuse a change that would drop the active-director count to zero. A no-op unless the TARGET
    is itself a currently-active director that the change demotes/removes (revoking an operator, or
    a non-director, has no director-count impact)."""
    if still_director_after:
        return
    e = email.strip().lower()
    actives = _active_directors()
    if not any(r["email"] == e for r in actives):
        return                                          # target isn't an active director
    if not [r for r in actives if r["email"] != e]:
        raise HTTPException(status_code=409,
                            detail="refused: this is the last active director (would lock out admin)")


@router.get("/admin/operators")
def operators_list(_d: str = Depends(require_director)):
    from stewie.server import operators as OPS
    return {"ok": True, "operators": OPS.list_all()}


@router.post("/admin/operators/approve")
def operators_approve(body: dict, director: str = Depends(require_director)):
    from stewie.server import operators as OPS
    email = str(body.get("email", "")).strip().lower()
    role = str(body.get("role", "operator"))
    try:
        rec = OPS.approve(email, by=director, role=role)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
    log_event(director, "admin.operator.approve", f"{email} as {role}")
    return {"ok": True, "operator": rec}


@router.post("/admin/operators/revoke")
def operators_revoke(body: dict, director: str = Depends(require_director)):
    from stewie.server import operators as OPS
    email = str(body.get("email", "")).strip().lower()
    _guard_last_director(email, still_director_after=False)
    try:
        rec = OPS.revoke(email, by=director)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
    log_event(director, "admin.operator.revoke", email)
    return {"ok": True, "operator": rec}


@router.post("/admin/operators/role")
def operators_set_role(body: dict, director: str = Depends(require_director)):
    from stewie.server import operators as OPS
    email = str(body.get("email", "")).strip().lower()
    role = str(body.get("role", "operator"))
    _guard_last_director(email, still_director_after=(role == "director"))
    try:
        rec = OPS.set_role(email, role, by=director)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
    log_event(director, "admin.operator.role", f"{email} -> {role}")
    return {"ok": True, "operator": rec}


@router.post("/admin/operators/reset")
def operators_reset_password(body: dict, director: str = Depends(require_director)):
    from stewie.server import operators as OPS
    email = str(body.get("email", "")).strip().lower()
    new = str(body.get("new_password", ""))
    try:
        OPS.set_password(email, new)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
    log_event(director, "admin.operator.reset", email)
    return {"ok": True, "message": f"password reset for {email}"}


@router.delete("/admin/operators/{email}")
def operators_delete(email: str, director: str = Depends(require_director)):
    from stewie.server import operators as OPS
    e = email.strip().lower()
    _guard_last_director(e, still_director_after=False)
    ok = OPS.delete(e)
    log_event(director, "admin.operator.delete", e)
    return {"ok": ok}


@router.get("/events")
def get_events(n: int = 50, actor: str | None = None, action: str | None = None,
               _auth: str = Depends(require_director)):
    """The newest-first event history (who did what when). SEC-2: director-only -- it carries
    operator identities + the full mutation trail (an audit surface, not public).

    Optional ``actor`` / ``action`` filters give an admin a PER-USER history (e.g. every login for one
    operator: ``?actor=alice@x.com&action=auth.login``). When a filter is set the whole ledger is
    scanned (output still capped) so sparse matches are not lost in the unfiltered tail."""
    import json as _json

    from stewie.specs import config as CFG
    path = os.path.join(CFG.data_dir(), "events.jsonl")
    cap = max(1, min(int(n), 500))
    filtering = bool(actor) or bool(action)
    a = (actor or "").strip().lower()
    out: list = []
    if os.path.exists(path):
        lines = open(path).read().splitlines()
        if not filtering:
            lines = lines[-cap:]
        for ln in reversed(lines):                       # newest-first
            try:
                ev = _json.loads(ln)
            except ValueError:
                continue
            if a and str(ev.get("actor", "")).strip().lower() != a:
                continue
            if action and str(ev.get("action", "")) != action:
                continue
            out.append(ev)
            if len(out) >= cap:
                break
    return {"ok": True, "events": out}
