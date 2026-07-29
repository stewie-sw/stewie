"""Structures router (ARCH-3): custom structure-template CRUD + parametric expansion over the
file-backed object store (server.objects). Auth comes from server.deps, the audit log from
server.services -- no import of the app module (no cycle)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from stewie.server import objects as OBJ
from stewie.server.deps import require_auth, require_role
from stewie.server.services import log_event

router = APIRouter()


@router.post("/structures/custom/{name}")
def structure_save(name: str, doc: dict, _auth: str = Depends(require_role("operator"))):
    # #294 (AG-07): a custom structure is saved into the SHARED LIVE template library (save_structure
    # namespace="live") and expands into ANY operator's plan, so WRITING it is operator+ -- a guest/trainee
    # (below operator on the AG-01 ladder) must not pollute the shared pool. Reads stay any-auth (S-06).
    # SR-01: operator+ was necessary but not sufficient -- being AN operator let you overwrite ANOTHER
    # operator's template, which then expands into everyone's plans. Same gate as the sibling DELETE.
    from stewie.server import auth as AUTH
    try:
        out = OBJ.save_structure_authorized(
            name, doc, actor=_auth, is_director=AUTH.role_of(_auth) == "director")
    except PermissionError:
        return JSONResponse(status_code=403, content={
            "ok": False,
            "error": f"structure {name!r} belongs to another operator; only its owner or a director "
                     "may overwrite it"})
    except ValueError as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
    else:
        log_event(_auth, "structure.save", out["name"])
        return {"ok": True, **out}


@router.get("/structures/custom")
def structure_list(_auth: str = Depends(require_auth)):
    """S-06: operational reads require auth (the custom-structure library is not public)."""
    return {"ok": True, "structures": OBJ.list_structures()}


@router.get("/structures/custom/{name}/expand")
def structure_expand(name: str, x: float, y: float, _auth: str = Depends(require_auth)):
    orders = OBJ.expand_structure(name, x, y)
    if orders is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"no structure {name!r}"})
    return {"ok": True, "orders": orders}


@router.delete("/structures/custom/{name}")
def structure_delete(name: str, identity: str = Depends(require_auth)):
    """AG-06: recoverable soft-delete with ownership escalation -- delete your OWN template;
    another operator's (or an unowned) template requires a director."""
    from stewie.server import auth as AUTH
    try:
        ok = OBJ.delete_authorized(
            "structures", name, actor=identity, is_director=AUTH.role_of(identity) == "director")
    except PermissionError:
        return JSONResponse(status_code=403, content={
            "ok": False, "error": "deleting a shared (live) structure template requires a director"})
    log_event(identity, "structure.delete", f"{name} ns=live")
    return {"ok": ok, "recoverable": True}
