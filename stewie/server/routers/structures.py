"""Structures router (ARCH-3): custom structure-template CRUD + parametric expansion over the
file-backed object store (server.objects). Auth comes from server.deps, the audit log from
server.services -- no import of the app module (no cycle)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from stewie.server import objects as OBJ
from stewie.server.deps import require_auth
from stewie.server.services import log_event

router = APIRouter()


@router.post("/structures/custom/{name}")
def structure_save(name: str, doc: dict, _auth: str = Depends(require_auth)):
    try:
        out = OBJ.save_structure(name, doc, owner=_auth)      # AG-05: stamp the creating operator
        log_event(_auth, "structure.save", out["name"])
        return {"ok": True, **out}
    except ValueError as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})


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
    owner = OBJ.owner_of("structures", name)
    if not OBJ.deletion_allowed(owner, identity, AUTH.role_of(identity) == "director"):
        return JSONResponse(status_code=403, content={
            "ok": False, "error": "deleting another operator's structure requires a director"})
    ok = OBJ.delete_structure(name)
    log_event(identity, "structure.delete", name)
    return {"ok": ok, "recoverable": True}
