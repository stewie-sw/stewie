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
          ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css",
          ".wasm": "application/wasm"}   # Cesium ships draco/basis .wasm workers (WEB-01 /cesium dev route)


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


@router.get("/assets/{path:path}")
def get_asset(path: str):
    """ARCH-02: read-only static assets bundled in the server package (web/assets/: the cockpit script
    cockpit.js, brand images, fonts). Path-confined to web/assets/ (no traversal). Production nginx
    serves /assets/ directly from the image; this is the dev-server (uvicorn) equivalent so the cockpit
    loads its external script in BOTH environments."""
    base = os.path.join(_PKG, "web", "assets")
    full = os.path.normpath(os.path.join(base, path))
    if not (full == base or full.startswith(base + os.sep)) or not os.path.isfile(full):
        return JSONResponse(status_code=404, content={"ok": False, "error": f"no asset {path!r}"})
    ext = os.path.splitext(full)[1]
    return FileResponse(full, media_type=_CTYPE.get(ext, "application/octet-stream"))


@router.get("/cesium/{path:path}")
def get_cesium(path: str):
    """Dev-server equivalent of nginx serving the vendored CesiumJS bundle at /cesium/ (WEB-01). In
    production the frontend image downloads cesium 1.119 into /usr/share/nginx/html/cesium and nginx
    serves it; on the uvicorn dev server the same bundle -- if present at server/cesium/ (e.g. docker-cp'd
    from the frontend image for a local cockpit/UI harness) -- is served here so the globe loads in BOTH
    environments. Path-confined to server/cesium/ (no traversal). 404 when the bundle isn't present
    locally: the dev server simply has no globe then, exactly as before this route existed."""
    base = os.path.join(_PKG, "cesium")
    full = os.path.normpath(os.path.join(base, path))
    if not (full == base or full.startswith(base + os.sep)) or not os.path.isfile(full):
        return JSONResponse(status_code=404, content={"ok": False, "error": f"no cesium asset {path!r}"})
    ext = os.path.splitext(full)[1]
    return FileResponse(full, media_type=_CTYPE.get(ext, "application/octet-stream"))


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
