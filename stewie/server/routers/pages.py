"""Static public pages: the /landing marketing page.

In prod nginx serves the apex document itself, so the backend never sees the URL -- but a direct
/landing(.html) hit (the dev server, or a proxy that forwards the path) used to fall through to the
JSON 404 handler and return a raw {"ok": false} where a marketing page was expected. Same FileResponse
pattern as routers/program.py. GET-only, static, no secrets -> open, like the other GET page surfaces."""
from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter()

_SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LANDING = os.path.join(_SERVER_DIR, "web", "landing.html")
_VIZ_HAWORTH = os.path.join(_SERVER_DIR, "web", "viz_haworth.html")


@router.get("/landing")
@router.get("/landing.html")
def landing_page():
    if not os.path.exists(_LANDING):
        raise HTTPException(status_code=404, detail="landing page missing from this build")
    return FileResponse(_LANDING, media_type="text/html; charset=utf-8")


@router.get("/viz")
@router.get("/viz_haworth.html")
def viz_haworth_page():
    """The standalone FULL-RESOLUTION 3D terrain viewer (viz.stewie.space). Site-parametrized via ?site=
    (Haworth default); every imported site renders. GET-only, static, no secrets -> open, like /landing +
    /program. In prod nginx serves the apex document; this backend route covers a direct /viz hit + dev."""
    if not os.path.exists(_VIZ_HAWORTH):
        raise HTTPException(status_code=404, detail="viz page missing from this build")
    return FileResponse(_VIZ_HAWORTH, media_type="text/html; charset=utf-8")
