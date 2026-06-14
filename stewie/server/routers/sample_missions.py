"""Sample-missions router (ARCH-3): the bundled intern sample missions shipped beside the server
package (server/sample_missions/*.json) -- list them + serve one by allowlisted name (only the names
the list endpoint returns, so no path traversal). Read-only + public; no app-module import (no cycle)."""
from __future__ import annotations

import glob
import json
import os

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()

# the bundled missions live beside the server package (server/sample_missions/), one level up from routers/
_SAMPLES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sample_missions")


def _sample_missions() -> dict:
    """{name -> path} for the bundled intern sample missions (server/sample_missions/*.json)."""
    return {os.path.splitext(os.path.basename(p))[0]: p
            for p in sorted(glob.glob(os.path.join(_SAMPLES_DIR, "*.json")))}


@router.get("/sample_missions")
def get_sample_missions():
    """List the bundled intern sample missions; load one (into the build queue) via /sample_mission/{name}."""
    return {"ok": True, "samples": [{"name": n, "url": "/sample_mission/" + n} for n in _sample_missions()]}


@router.get("/sample_mission/{name}")
def get_sample_mission(name: str):
    """Serve a bundled sample mission by allowlisted name (only the names /sample_missions lists)."""
    p = _sample_missions().get(name)
    if not p:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"no sample mission {name}"})
    with open(p) as f:
        return json.load(f)
