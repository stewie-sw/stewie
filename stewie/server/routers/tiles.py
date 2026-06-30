"""Serve Cesium 3D Tiles tilesets -- the reconstruction-twin globe layer (a COLMAP dense cloud packed by
scripts/colmap/ply_to_3dtiles.py into tileset.json + points.pnts). Public read (the cockpit's globe fetches
it same-origin, CSP `connect-src 'self'`). Files come from STEWIE_TILES_DIR (default <repo>/out/colmap), so
`/tiles/<name>/tileset.json` -> <dir>/<name>/tileset.json. Path-traversal hardened (realpath must stay
under the base) like the rest of the static surface."""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, JSONResponse

from stewie.server.deps import require_auth

router = APIRouter()

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))   # routers -> server -> stewie -> <repo>
_TILES_DIR = os.path.realpath(os.environ.get("STEWIE_TILES_DIR") or os.path.join(_REPO, "out", "colmap"))
_CT = {".json": "application/json", ".pnts": "application/octet-stream",
       ".b3dm": "application/octet-stream", ".cmpt": "application/octet-stream",
       ".glb": "model/gltf-binary", ".bin": "application/octet-stream"}


@router.get("/tiles/{name}/{asset:path}")
def get_tile(name: str, asset: str, _auth: str = Depends(require_auth)):
    """Serve a tileset file. `name` = tileset dir (e.g. 'twin'); `asset` = tileset.json or points.pnts."""
    path = os.path.realpath(os.path.join(_TILES_DIR, name, asset))
    # #302 path-traversal guard: the resolved path must stay under the FIXED tiles dir. Validating against
    # a base recomputed from the attacker-controlled {name} (e.g. name='..') moved the containment dir up a
    # level and served files outside _TILES_DIR; pin it to _TILES_DIR (already realpath'd at import).
    if not path.startswith(_TILES_DIR + os.sep):
        return JSONResponse(status_code=400, content={"ok": False, "error": "bad tile path"})
    if not os.path.isfile(path):
        return JSONResponse(status_code=404, content={"ok": False, "error": f"no tile {name}/{asset}"})
    ext = os.path.splitext(asset)[1].lower()
    return FileResponse(path, media_type=_CT.get(ext, "application/octet-stream"))
