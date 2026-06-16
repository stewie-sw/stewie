"""DEM router (ARCH-3): the Haworth work-area DEM surface for the cockpit -- the tile's selenographic
georef + a lat/lon -> site-frame transform (both delegating to lode.mission_planner) and the bundled
LOLA preview PNGs. The two compute routes are declared BEFORE the /dem/{name} param route so the
specific paths win (route order is preserved within the router). No app-module import (no cycle); no
server-owned shared state (the planner owns the DEM)."""
from __future__ import annotations

import os

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse

router = APIRouter()

# the server package dir (server/), one level up from routers/ -- the DEM bundle sits two levels above
_PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@router.get("/dem/georef")
def dem_georef():
    """The Haworth tile's globe footprint (selenographic corners) for the cockpit overlay."""
    from lode import mission_planner as MP
    try:
        return {"ok": True, **MP.dem_georef_corners()}
    except (ImportError, FileNotFoundError, ValueError) as e:
        return JSONResponse(status_code=503, content={"ok": False, "error": str(e)})


@router.get("/dem/site_xy")
def dem_site_xy(lat: float, lon: float):
    """Selenographic lat/lon -> the Haworth site frame (x, y) [m] (the cursor-meters readout)."""
    from lode import mission_planner as MP
    try:
        x, y = MP.latlon_to_dem_origin(lat, lon)
    except ValueError as e:
        return JSONResponse(status_code=422, content={"ok": False, "error": str(e)})
    except ImportError as e:
        return JSONResponse(status_code=503, content={"ok": False, "error": f"pyproj absent: {e}"})
    return {"ok": True, "x_m": round(x, 1), "y_m": round(y, 1)}


@router.get("/dem/sources")
def dem_sources_catalog():
    """#150: the lunar DEM source catalog -- every selectable base layer with provenance, license, and
    readiness. `bundled` tiles load offline (the 3 real LOLA tiles on disk); the rest are real-data-gated
    (you supply the downloaded product). `planning_grade` is false for render-only visualization products.
    Public read; the source of truth for the cockpit layer selector + the THIRD_PARTY provenance audit.
    Declared BEFORE /dem/{name} so the literal path is not captured as a preview name."""
    from dart.dem_sources import list_dem_sources
    return {"ok": True, "sources": [
        {"id": s.id, "name": s.name, "instrument": s.instrument, "resolution_m": s.resolution_m,
         "coverage": s.coverage, "crs": s.crs, "fmt": s.fmt, "bundled": s.bundled,
         "planning_grade": s.planning_grade, "ingest": s.ingest, "access_url": s.access_url,
         "license": s.license, "notes": s.notes} for s in list_dem_sources()]}


@router.get("/dem/{name}")
def get_dem(name: str):                                 # the real LOLA work-area DEM previews (Haworth)
    bundle = os.path.join(_PKG, "..", "..", "samples", "lunar_dem", "haworth_10km_5m")
    f = {"hillshade.png": "preview_hillshade.png", "height.png": "preview_height.png"}.get(os.path.basename(name))
    if not f:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"no dem {os.path.basename(name)}"})
    path = os.path.join(bundle, f)
    if not os.path.isfile(path):                        # bundle absent (e.g. a wheel install) -> 404, not a 500
        return JSONResponse(status_code=404, content={"ok": False, "error": f"dem preview not available: {f}"})
    return FileResponse(path, media_type="image/png")
