"""Missions router (ARCH-3): build-mission CRUD over the file-backed object store
(server.objects). Auth comes from server.deps, the audit log from server.services -- no
import of the app module (no cycle)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from stewie.server import objects as OBJ
from stewie.server.deps import require_auth
from stewie.server.services import log_event

router = APIRouter()


@router.post("/missions/{name}")
def mission_save(name: str, doc: dict, _auth: str = Depends(require_auth)):
    try:
        out = OBJ.save_mission(name, doc, owner=_auth)        # AG-05: stamp the creating operator
        log_event(_auth, "mission.save", out["name"])
        return {"ok": True, **out}
    except ValueError as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})


@router.get("/missions")
def mission_list(_auth: str = Depends(require_auth)):
    """S-06: operational reads require auth (a mission queue is not public)."""
    return {"ok": True, "missions": OBJ.list_missions()}


@router.get("/missions/{name}")
def mission_load(name: str, _auth: str = Depends(require_auth)):
    d = OBJ.load_mission(name)
    if d is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"no mission {name!r}"})
    return {"ok": True, "doc": d}


@router.delete("/missions/{name}")
def mission_delete(name: str, _auth: str = Depends(require_auth)):
    ok = OBJ.delete_mission(name)
    log_event(_auth, "mission.delete", name)
    return {"ok": ok}
