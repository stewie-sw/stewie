"""DEM router (ARCH-3): the Haworth work-area DEM surface for the cockpit -- the tile's selenographic
georef + a lat/lon -> site-frame transform (both delegating to lode.mission_planner) and the bundled
LOLA preview PNGs. The two compute routes are declared BEFORE the /dem/{name} param route so the
specific paths win (route order is preserved within the router). No app-module import (no cycle); no
server-owned shared state (the planner owns the DEM)."""
from __future__ import annotations

import json
import os

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, JSONResponse, Response

from stewie.server.deps import require_auth
from stewie.specs.config import data_dir

router = APIRouter()


@router.get("/clasts/scene")
def clasts_scene(_auth: str = Depends(require_auth)):
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
def dem_georef(site: str = "haworth", _auth: str = Depends(require_auth)):
    """The chosen site's tile globe footprint (selenographic corners) for the cockpit overlay (REG-01:
    any imported site, not just Haworth -- so selecting a site overlays ITS tile on the globe)."""
    from lode import mission_planner as MP
    from stewie.server import state
    try:
        out = {"ok": True, "site": site, **MP.dem_georef_corners(bundle_dir=MP.bundle_for_site(site))}
        # #audit-2b: the work area's TRUE anchor (the auto-selected flattest buildable patch, tile-meters) so
        # the cockpit draws the WORK AREA rect WHERE the work actually is -- the inset + planner use this origin,
        # but drawWorkAreaRect was pinning the rect to the tile's (0,0) corner (~8 km away). (None DEM -> 0,0.)
        _dem, origin = state.moon_dem(site)
        out["anchor_xy"] = [float(origin[0]), float(origin[1])]
        return out
    except KeyError as e:
        return JSONResponse(status_code=404, content={"ok": False, "error": str(e)})
    except (ImportError, FileNotFoundError, ValueError) as e:
        return JSONResponse(status_code=503, content={"ok": False, "error": str(e)})


@router.get("/dem/site_xy")
def dem_site_xy(lat: float, lon: float, site: str = "haworth", _auth: str = Depends(require_auth)):
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
def dem_site_lonlat(x: float, y: float, site: str = "haworth", _auth: str = Depends(require_auth)):
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
def dem_sources_catalog(_auth: str = Depends(require_auth)):
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
def dem_heightfield(site: str = "haworth", n: int = 129, window_m: float = 300.0,
                    _auth: str = Depends(require_auth)):
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


# #239 DoS cache: /dem/workarea.png is unauthenticated and the psr/illumination layers run an O(P^2..P^3)
# horizon sweep (kind=psr = 12 azimuths). Cache the rendered PNG bytes per quantized key so repeats are O(1).
# Plain dict + FIFO cap, matching the unlocked gis_layers._GLOBE_CACHE precedent (values are a deterministic
# pure function of the key, so a concurrent miss-miss just recomputes identical bytes -- no lock needed).
_WORKAREA_CACHE: dict = {}
_WORKAREA_CACHE_MAX = 256


@router.get("/dem/workarea.png")
def dem_workarea_png(site: str = "haworth", window_m: float = 640.0, kind: str = "dem",
                     sun_az: float = 315.0, sun_el: float = 45.0, _auth: str = Depends(require_auth)):
    """GIS-WA1/WA2: a CLEAN, axis-free raster of the WORK-AREA order frame [0, window_m]^2 (x East, y North
    from the site origin), sampled from the chosen site's real LOLA DEM at NATIVE cell resolution -- no
    matplotlib axes/title/margins. `kind` selects the LAYER: dem (315/45 hillshade, the plan-canvas authoring
    backdrop), slope, hazard, illumination, psr -- all rendered in the order frame via the SAME gis_layers
    _layer_rgba the globe drape uses, so the 3D view (GIS-WA2) can texture the relief with the chosen layer
    at the heightfield's exact window. Image row 0 = top = max y (North); col 0 = left = x=0 (West) -- the
    plan canvas's North-up, West-left convention. Declared BEFORE /dem/{name} so the literal path is not
    captured as a preview name."""
    import numpy as np

    from stewie.server import state
    from stewie.server.gis_layers import _layer_rgba, _to_png
    from stewie.terrain.site_dem import bundle_for_site
    win = max(10.0, min(float(window_m), 2000.0))        # clamp BEFORE keying (an attacker can't inflate the key)
    az = round(float(sun_az)) % 360                      # quantize the sun to int degrees (sub-degree is invisible)
    el = max(-90, min(90, round(float(sun_el))))
    # #239: slope/hazard/psr IGNORE the sun (psr sweeps its own 12 azimuths) -- so do NOT key on the sun for
    # them, else varying sun_az would bust the cache and re-trigger the expensive psr sweep every call.
    sun_part = (az, el) if kind in ("dem", "hillshade", "illumination", "incidence") else None
    ckey = (site, kind, round(win), sun_part)
    cached = _WORKAREA_CACHE.get(ckey)
    if cached is not None:
        return Response(content=cached, media_type="image/png")
    try:
        bundle_for_site(site)                           # validate the site (404 on unknown / unimported)
    except (KeyError, FileNotFoundError) as e:
        return JSONResponse(status_code=404, content={"ok": False, "error": str(e)})
    dem, origin = state.moon_dem(site)
    if dem is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"no DEM for site {site!r}"})
    Z, cell = dem
    ox, oy = origin
    Zf = np.asarray(Z, dtype=float)
    H, W = Zf.shape
    npx = max(2, int(round(win / float(cell))) + 1)     # NATIVE sampling over the window (no fabricated detail)
    xs = np.linspace(0.0, win, npx)
    cols = np.clip(np.round((ox + xs) / cell).astype(int), 0, W - 1)
    rows = np.clip(np.round((oy + xs) / cell).astype(int), 0, H - 1)
    patch = Zf[np.ix_(rows, cols)]                       # [row=y(North as j incr), col=x(East)] -- TRUE orientation
    rgba = _layer_rgba(patch, float(cell), kind, az, el)   # compute on the true-orient patch at the quantized sun
    if rgba is None:
        return JSONResponse(status_code=400,
                            content={"ok": False, "error": f"unknown layer kind {kind!r}"})
    rgba = np.flipud(rgba)                               # image row 0 = top = max y (North) = the plan canvas's top
    png = _to_png(rgba)
    _WORKAREA_CACHE[ckey] = png
    if len(_WORKAREA_CACHE) > _WORKAREA_CACHE_MAX:
        _WORKAREA_CACHE.pop(next(iter(_WORKAREA_CACHE)), None)   # FIFO: evict the oldest entry
    return Response(content=png, media_type="image/png")


@router.get("/dem/terrain_grid")
def dem_terrain_grid_route(site: str = "haworth", n: int = 64, _auth: str = Depends(require_auth)):
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
def get_dem(name: str, site: str = "haworth", _auth: str = Depends(require_auth)):   # real LOLA work-area DEM previews (REG-01: per site)
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
