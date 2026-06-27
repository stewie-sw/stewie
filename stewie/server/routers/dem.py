"""DEM router (ARCH-3): the Haworth work-area DEM surface for the cockpit -- the tile's selenographic
georef + a lat/lon -> site-frame transform (both delegating to lode.mission_planner) and the bundled
LOLA preview PNGs. The two compute routes are declared BEFORE the /dem/{name} param route so the
specific paths win (route order is preserved within the router). No app-module import (no cycle); no
server-owned shared state (the planner owns the DEM)."""
from __future__ import annotations

import json
import os

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse

from stewie.specs.config import data_dir

router = APIRouter()


@router.get("/clasts/scene")
def clasts_scene():
    """#147 tier-3 (Chrono brick): the latest REAL Chrono-settled boulder scene -- scripts/chrono_clast_scene.py
    runs a ChSystemSMC rigid-body solve (settled vs analytic g) and writes <data_dir>/clasts_scene.json with
    {clasts:[{x,y,z,r}], ...} in the ORDER FRAME. The cockpit 3D view places each boulder ON the DEM surface.
    Returns an empty scene if none produced yet. Open GET (read-only terrain feature). NOT the force-accurate
    drum-excavation tier (that stays blocked on the Chrono vehicle/SCM module + GPU DEM; see task #147)."""
    path = os.path.join(data_dir(), "clasts_scene.json")
    if not os.path.exists(path):
        return JSONResponse({"present": False, "n": 0, "clasts": []})
    try:
        with open(path) as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return JSONResponse({"present": False, "n": 0, "clasts": []})
    doc["present"] = True
    return JSONResponse(doc)

# the server package dir (server/), one level up from routers/ -- the DEM bundle sits two levels above
_PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@router.get("/dem/georef")
def dem_georef(site: str = "haworth"):
    """The chosen site's tile globe footprint (selenographic corners) for the cockpit overlay (REG-01:
    any imported site, not just Haworth -- so selecting a site overlays ITS tile on the globe)."""
    from lode import mission_planner as MP
    try:
        return {"ok": True, "site": site, **MP.dem_georef_corners(bundle_dir=MP.bundle_for_site(site))}
    except KeyError as e:
        return JSONResponse(status_code=404, content={"ok": False, "error": str(e)})
    except (ImportError, FileNotFoundError, ValueError) as e:
        return JSONResponse(status_code=503, content={"ok": False, "error": str(e)})


@router.get("/dem/site_xy")
def dem_site_xy(lat: float, lon: float, site: str = "haworth"):
    """Selenographic lat/lon -> the chosen site's frame (x, y) [m] (the cursor-meters readout). REG-01:
    site-aware, so a click on a non-Haworth tile resolves against THAT tile's georef, not Haworth's."""
    from lode import mission_planner as MP
    try:
        x, y = MP.latlon_to_dem_origin(lat, lon, bundle_dir=MP.bundle_for_site(site))
    except KeyError as e:
        return JSONResponse(status_code=404, content={"ok": False, "error": str(e)})
    except ValueError as e:
        return JSONResponse(status_code=422, content={"ok": False, "error": str(e)})
    except (ImportError, FileNotFoundError) as e:
        return JSONResponse(status_code=503, content={"ok": False, "error": f"DEM/pyproj absent: {e}"})
    return {"ok": True, "site": site, "x_m": round(x, 1), "y_m": round(y, 1)}


@router.get("/dem/site_lonlat")
def dem_site_lonlat(x: float, y: float, site: str = "haworth"):
    """#174: the chosen site's order-frame (x, y) [m] -> selenographic lat/lon (deg) -- the INVERSE of
    /dem/site_xy, so the cockpit can show the actual coordinates next to the site metres for the lander,
    the rover's pose, and placed landmarks (Aaron: "why are these in meters vs actual coordinates?")."""
    from lode import mission_planner as MP
    try:
        lat, lon = MP.dem_origin_to_latlon(x, y, bundle_dir=MP.bundle_for_site(site))
    except KeyError as e:
        return JSONResponse(status_code=404, content={"ok": False, "error": str(e)})
    except ValueError as e:
        return JSONResponse(status_code=422, content={"ok": False, "error": str(e)})
    except (ImportError, FileNotFoundError) as e:
        return JSONResponse(status_code=503, content={"ok": False, "error": f"DEM/pyproj absent: {e}"})
    return {"ok": True, "site": site, "lat": round(lat, 6), "lon": round(lon, 6)}


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


@router.get("/dem/heightfield")
def dem_heightfield(site: str = "haworth", n: int = 129, window_m: float = 300.0):
    """3D playback (#165): a decimated n*n height grid over the work-area ORDER FRAME [0, window_m]^2
    -- x metres East, y metres North from the site origin -- sampled from the chosen site's real LOLA
    DEM with the planner's exact convention (col = round((ox+x)/cell_m), row = round((oy+y)/cell_m),
    lode.planner_routing.haul_elevation_gain_m). An in-browser 3D viewer renders this surface and the
    rover's LAST_TIMELINE (x, y) samples the SAME grid, so the dry-run rover sits on the real terrain.
    `z` is row-major y-then-x: z[j*n + i] is the height at (x = i/(n-1)*window_m, y = j/(n-1)*window_m).
    Declared BEFORE /dem/{name} so the literal path is not captured as a preview name."""
    import numpy as np

    from stewie.server import state
    from stewie.terrain.site_dem import bundle_for_site
    try:
        bundle_for_site(site)                           # validate the site (404 on unknown / unimported)
    except (KeyError, FileNotFoundError) as e:
        return JSONResponse(status_code=404, content={"ok": False, "error": str(e)})
    dem, origin = state.moon_dem(site)
    if dem is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"no DEM for site {site!r}"})
    Z, cell = dem
    ox, oy = origin
    H, W = np.asarray(Z).shape
    n = max(2, min(int(n), 257))                        # bound the browser grid (n=257 -> ~66k samples)
    win = max(10.0, min(float(window_m), 2000.0))
    xs = np.linspace(0.0, win, n)
    cols = np.clip(np.round((ox + xs) / cell).astype(int), 0, W - 1)
    rows = np.clip(np.round((oy + xs) / cell).astype(int), 0, H - 1)
    grid = np.asarray(Z, dtype=float)[np.ix_(rows, cols)]   # n x n, row = y (North), col = x (East)
    return {"ok": True, "site": site, "n": n, "window_m": win, "cell_m": float(cell),
            "dem_origin": [float(ox), float(oy)],
            "z": [round(v, 3) for v in grid.flatten().tolist()],
            "z_min": float(grid.min()), "z_max": float(grid.max())}


@router.get("/dem/terrain_grid")
def dem_terrain_grid_route(site: str = "haworth", n: int = 64):
    """REG-01 globe 3D layer: an n*n georeferenced height grid (lat/lon + real elevation [m]) of the chosen
    site's LOLA DEM, for draping the work-area terrain as a 3D mesh layer on the Cesium globe. Reprojection
    is vectorized (one pyproj call for all nodes). Declared BEFORE /dem/{name} so the literal path wins.
    503 when pyproj (the [planner] extra) is absent; 404 on an unknown/unimported site."""
    from stewie.terrain.site_dem import bundle_for_site, dem_terrain_grid
    try:
        bundle = bundle_for_site(site)
    except (KeyError, FileNotFoundError) as e:
        return JSONResponse(status_code=404, content={"ok": False, "error": str(e)})
    try:
        return {"ok": True, "site": site, **dem_terrain_grid(n=n, bundle_dir=bundle)}
    except (FileNotFoundError, ValueError) as e:
        return JSONResponse(status_code=404, content={"ok": False, "error": str(e)})
    except ImportError as e:
        return JSONResponse(status_code=503, content={"ok": False, "error": f"DEM/pyproj absent: {e}"})


@router.get("/dem/{name}")
def get_dem(name: str, site: str = "haworth"):          # the real LOLA work-area DEM previews (REG-01: per site)
    from stewie.terrain.site_dem import bundle_for_site
    f = {"hillshade.png": "preview_hillshade.png", "height.png": "preview_height.png"}.get(os.path.basename(name))
    if not f:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"no dem {os.path.basename(name)}"})
    try:
        bundle = bundle_for_site(site)                  # the chosen imported site's bundle (not just Haworth)
    except (KeyError, FileNotFoundError) as e:
        return JSONResponse(status_code=404, content={"ok": False, "error": str(e)})
    path = os.path.join(bundle, f)
    if not os.path.isfile(path):                        # bundle absent (e.g. a wheel install) -> 404, not a 500
        return JSONResponse(status_code=404, content={"ok": False, "error": f"dem preview not available: {f}"})
    return FileResponse(path, media_type="image/png")
