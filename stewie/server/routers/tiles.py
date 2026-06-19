"""Serve Cesium 3D Tiles tilesets -- the reconstruction-twin globe layer (a COLMAP dense cloud packed by
scripts/colmap/ply_to_3dtiles.py into tileset.json + points.pnts). Public read (the cockpit's globe fetches
it same-origin, CSP `connect-src 'self'`). Files come from STEWIE_TILES_DIR (default <repo>/out/colmap), so
`/tiles/<name>/tileset.json` -> <dir>/<name>/tileset.json. Path-traversal hardened (realpath must stay
under the base) like the rest of the static surface."""
from __future__ import annotations

import os

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse

router = APIRouter()

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))   # routers -> server -> stewie -> <repo>
_TILES_DIR = os.path.realpath(os.environ.get("STEWIE_TILES_DIR") or os.path.join(_REPO, "out", "colmap"))
_CT = {".json": "application/json", ".pnts": "application/octet-stream",
       ".b3dm": "application/octet-stream", ".cmpt": "application/octet-stream",
       ".glb": "model/gltf-binary", ".bin": "application/octet-stream"}


@router.get("/tiles/{name}/{asset:path}")
def get_tile(name: str, asset: str):
    """Serve a tileset file. `name` = tileset dir (e.g. 'twin'); `asset` = tileset.json or points.pnts."""
    base = os.path.join(_TILES_DIR, name)
    path = os.path.realpath(os.path.join(base, asset))
    # path-traversal guard: the resolved path must stay under the tileset's own dir.
    if not path.startswith(os.path.realpath(base) + os.sep):
        return JSONResponse(status_code=400, content={"ok": False, "error": "bad tile path"})
    if not os.path.isfile(path):
        return JSONResponse(status_code=404, content={"ok": False, "error": f"no tile {name}/{asset}"})
    ext = os.path.splitext(asset)[1].lower()
    return FileResponse(path, media_type=_CT.get(ext, "application/octet-stream"))
