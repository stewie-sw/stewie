"""Static-asset router (ARCH-3): read-only file serving for the brand assets bundled in the server
package (fonts/icons/bodies.json) and the generated mission-control reports (data_dir/reports). Every
route is basename-confined (no path traversal); the reports dir is resolved at call time so a
relocated data_dir is honored. No app-module import (no cycle).

NOTE: /dem/{name} and /figures stay in server.py for now -- /dem/{name} would shadow the sibling
/dem/georef + /dem/site_xy compute routes if registered early, and /figures couples to the repo-root
validation dir; both are a separate careful follow-up."""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, JSONResponse

from stewie.server.deps import require_auth

router = APIRouter()

# the server package dir (server/), one level up from routers/ -- holds fonts/, icons/, bodies.json
_PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CTYPE = {".json": "application/json", ".pdf": "application/pdf",
          ".md": "text/markdown; charset=utf-8", ".png": "image/png",
          ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css"}


def _reports_dir() -> str:
    from stewie.specs import config as CFG
    return CFG.reports_dir()


@router.get("/fonts/{name}")
def get_font(name: str):
    """Vendored brand fonts (Orbitron, OFL -- license shipped alongside). No CDN at runtime."""
    safe = os.path.basename(name)
    path = os.path.join(_PKG, "fonts", safe)
    if not os.path.isfile(path):
        return JSONResponse(status_code=404, content={"ok": False, "error": f"no font {safe}"})
    return FileResponse(path, media_type="font/ttf" if safe.endswith(".ttf") else "text/plain")


@router.get("/icons/{name}")
def get_icon(name: str):
    """The app-icon set (cropped from the brand board's 1024 tile)."""
    safe = os.path.basename(name)
    path = os.path.join(_PKG, "icons", safe)
    if not os.path.isfile(path):
        return JSONResponse(status_code=404, content={"ok": False, "error": f"no icon {safe}"})
    return FileResponse(path, media_type="image/png")


@router.get("/bodies.json")
def get_bodies():
    p = os.path.join(_PKG, "bodies.json")
    if not os.path.isfile(p):
        return JSONResponse(status_code=404, content={"ok": False, "error": "not found: bodies.json"})
    return FileResponse(p, media_type=_CTYPE[".json"])


@router.get("/reports/{name}")
def get_report(name: str, _auth: str = Depends(require_auth)):
    """S-06: generated mission-control reports are operational artifacts -> auth required, and the
    report id is an OPAQUE token (see routers.plan._plan_stem), not a derivable name+hash."""
    safe = os.path.basename(name)                       # basename only -> no path traversal
    p = os.path.join(_reports_dir(), safe)
    if not os.path.isfile(p):
        return JSONResponse(status_code=404, content={"ok": False, "error": f"not found: {safe}"})
    ext = os.path.splitext(safe)[1]
    return FileResponse(p, media_type=_CTYPE.get(ext, "application/octet-stream"))
