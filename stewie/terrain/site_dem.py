"""Real-DEM site loaders for the work area (ARCH-2: extracted from lode.mission_planner).

Terrain-layer data loading -- below lode (planning) and dart (perception), both of which consume
real LOLA DEMs. Loaders resolve the bundle via $STEWIE_DEM_DIR / the SITES registry, stream a
km-scale map a window at a time, and project selenographic lat/lon to the DEM order-frame. No
fabricated terrain: a missing bundle raises (the server degrades to a flat slope-check), never
invents a surface.
"""
from __future__ import annotations

import json
import math
import os

import numpy as np

# repo root from stewie/terrain/site_dem.py -> stewie/terrain -> stewie -> <repo>
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _haworth_bundle(bundle_dir=None):
    # RB-06 explicit asset mode: the (large, unpackaged) Haworth DEM bundle is located explicitly via
    # $STEWIE_DEM_DIR for a deployment, else the in-repo samples path for dev. Absence degrades to a
    # flat slope-check in the server (_moon_dem), it does not crash the request.
    return (bundle_dir or os.environ.get("STEWIE_DEM_DIR", os.environ.get("STEWIE_DEM_DIR"))
            or os.path.join(_REPO_ROOT, "samples", "lunar_dem", "haworth_10km_5m"))


def load_site_dem(site: str = "haworth"):
    """#77 REG-01: load the real LOLA 5 m DEM for ANY imported site (not just Haworth). Resolves the
    bundle via the SITES registry (stewie.specs.sites); returns (heightmap [m], cell_m). Raises if the
    site is unknown or not imported -- no fabricated terrain. PLAN-ANYWHERE: an ad-hoc lat/lon-derived
    ``adhoc_*`` id crops the global LDEM on demand (stewie.terrain.adhoc_dem)."""
    if _is_adhoc(site):
        from stewie.terrain.adhoc_dem import parse_adhoc_site, resolve_adhoc_bundle
        return load_haworth_dem(bundle_dir=resolve_adhoc_bundle(*parse_adhoc_site(site)))
    from stewie.specs.sites import SITES
    s = SITES.get(site)
    if s is None:
        raise KeyError(f"unknown site {site!r} (known: {sorted(SITES)})")
    if site == "haworth":
        return load_haworth_dem()                 # the work site honors $STEWIE_DEM_DIR (deployment override)
    if not s.bundle_dir:
        raise FileNotFoundError(f"site {site!r} is not imported (no DEM bundle); fetch it first")
    return load_haworth_dem(bundle_dir=s.bundle_dir)


def bundle_for_site(site: str = "haworth") -> str:
    """REG-01: resolve the on-disk DEM bundle DIRECTORY for an imported site -- for the loaders + endpoints
    that take a ``bundle_dir`` (dem_georef_corners, latlon_to_dem_origin, the preview PNGs, the globe drape).
    Haworth honors the $STEWIE_DEM_DIR deployment override; other sites come from the SITES registry. Raises
    KeyError for an unknown site and FileNotFoundError for a known-but-not-imported one -- never points at a
    fabricated or wrong-site surface (the caller maps these to 404). PLAN-ANYWHERE: an ad-hoc
    ``adhoc_<lat>_<lon>`` id crops the global LDEM on demand (stewie.terrain.adhoc_dem)."""
    if _is_adhoc(site):
        from stewie.terrain.adhoc_dem import parse_adhoc_site, resolve_adhoc_bundle
        return resolve_adhoc_bundle(*parse_adhoc_site(site))
    from stewie.specs.sites import SITES
    s = SITES.get(site)
    if s is None:
        raise KeyError(f"unknown site {site!r} (known: {sorted(SITES)})")
    if site == "haworth":
        return _haworth_bundle()
    if not s.bundle_dir:
        raise FileNotFoundError(f"site {site!r} is not imported (no DEM bundle); fetch it first")
    return s.bundle_dir


def _is_adhoc(site: str) -> bool:
    """True for a PLAN-ANYWHERE ad-hoc lat/lon-derived site id (kept as a light local check so this module
    does not import adhoc_dem at import time -- the crop path is imported lazily only when one is resolved)."""
    return isinstance(site, str) and site.startswith("adhoc_")


def bundle_crs(bundle_dir=None):
    """The tile's CRS. A PLAN-ANYWHERE ad-hoc bundle carries a LOCAL azimuthal-equidistant frame in its
    ``metadata.json`` ``georeference.proj4`` (centred on the pick -- ~0 warp at any latitude); a curated
    site has none, so this returns the shared south-polar-stereographic IAU_2015:30135. This is the ONE
    place the georeference helpers below + the globe drape resolve the frame, so the 8 curated sites stay
    byte-identical while an ad-hoc tile georeferences through its own local frame."""
    from pyproj import CRS
    try:
        meta = json.load(open(os.path.join(_haworth_bundle(bundle_dir), "metadata.json")))
        proj4 = (meta.get("georeference") or {}).get("proj4")
        if proj4:
            return CRS.from_user_input(proj4)
    except (OSError, ValueError, KeyError):
        pass
    return CRS.from_user_input("IAU_2015:30135")


def load_haworth_dem(bundle_dir=None):
    """Load a real LOLA 5 m DEM from a sim bundle: returns (heightmap [m], cell_m). Defaults to the
    Haworth work-site bundle; ``bundle_dir`` selects another imported site (REG-01)."""
    bundle = _haworth_bundle(bundle_dir)
    if not os.path.exists(os.path.join(bundle, "heightmap.rf32")):
        raise FileNotFoundError(
            f"Haworth DEM not found at {bundle}. It is NOT bundled in the wheel -- fetch it "
            "(PGDA Product 78): run `stewie-fetch-dem --source <mirror>` or set STEWIE_DEM_URL "
            "(see stewie/server/assets_manifest.json).")
    g = json.load(open(os.path.join(bundle, "metadata.json")))["grid"]
    Z = np.fromfile(os.path.join(bundle, "heightmap.rf32"), dtype="<f4").reshape(g["height"], g["width"])
    return Z.astype(np.float64), float(g["cell_m"])


# ---- P4: stream a km-scale DEM by window, without holding the whole map in RAM ------------------
def dem_grid_info(bundle_dir=None):
    """Grid metadata (width/height/cell_m) for a DEM bundle WITHOUT loading the heightfield -- the basis
    for streaming a km-scale map a window at a time instead of holding the whole array in RAM."""
    g = json.load(open(os.path.join(_haworth_bundle(bundle_dir), "metadata.json")))["grid"]
    return {"width": int(g["width"]), "height": int(g["height"]), "cell_m": float(g["cell_m"])}


def read_dem_window(r0, c0, h, w, bundle_dir=None):
    """Read ONLY the [r0:r0+h, c0:c0+w] window of the DEM (seek per row -> exactly h*w*4 bytes of I/O),
    returning (window [m], cell_m). The full 2000x2000 array is never materialised, so this scales to
    km-scale maps with a fixed memory ceiling. The window is clamped to the grid bounds."""
    bundle = _haworth_bundle(bundle_dir)
    info = dem_grid_info(bundle)
    W, H, cell = info["width"], info["height"], info["cell_m"]
    r0 = max(0, min(int(r0), H)); c0 = max(0, min(int(c0), W))
    h = max(0, min(int(h), H - r0)); w = max(0, min(int(w), W - c0))
    out = np.empty((h, w), dtype=np.float64)
    with open(os.path.join(bundle, "heightmap.rf32"), "rb") as f:
        for i in range(h):
            f.seek(((r0 + i) * W + c0) * 4)
            out[i] = np.frombuffer(f.read(w * 4), dtype="<f4").astype(np.float64)
    return out, float(cell)


def flattest_anchor_streamed(window_m=20.0, tile=400, bundle_dir=None):
    """Streamed equivalent of `flattest_anchor`: find the flattest buildable region of a km-scale DEM by
    scanning it TILE BY TILE (each tile read with a halo so the slope + window-mean are correct at tile
    edges), never holding the whole map in RAM. Returns the (x, y) in DEM meters of the global min mean-slope."""
    bundle = _haworth_bundle(bundle_dir)
    info = dem_grid_info(bundle)
    W, H, cell = info["width"], info["height"], info["cell_m"]
    k = max(1, int(round(window_m / cell)))
    halo = k + 1
    try:
        from scipy.ndimage import uniform_filter
    except Exception:
        uniform_filter = None
    best = (math.inf, 0, 0)                                  # (mean_slope, row, col) in global indices
    for tr in range(0, H, tile):
        for tc in range(0, W, tile):
            r0, c0 = max(0, tr - halo), max(0, tc - halo)
            r1, c1 = min(H, tr + tile + halo), min(W, tc + tile + halo)
            Zt, _ = read_dem_window(r0, c0, r1 - r0, c1 - c0, bundle)
            smap = slope_deg_map(Zt, cell)
            sm = uniform_filter(smap, size=k, mode="nearest") if uniform_filter else smap
            ir0, ic0 = tr - r0, tc - c0                      # this tile's interior within the haloed read
            ir1, ic1 = min(r1, tr + tile) - r0, min(c1, tc + tile) - c0
            sub = sm[ir0:ir1, ic0:ic1]
            if sub.size == 0:
                continue
            lr, lc = np.unravel_index(int(np.argmin(sub)), sub.shape)
            val = float(sub[lr, lc])
            if val < best[0]:
                best = (val, tr + lr, tc + lc)
    return float(best[2] * cell), float(best[1] * cell)


def slope_deg_map(Z, cell_m):
    """Per-cell surface slope [deg] from a heightmap (gradient magnitude -> arctan)."""
    gy, gx = np.gradient(Z, cell_m)
    return np.degrees(np.arctan(np.hypot(gx, gy)))


def flattest_anchor(dem, *, window_m=20.0):
    """M11: auto-find the flattest buildable region on a DEM. Returns the (x, y) in DEM meters of the
    cell that minimizes mean slope over a `window_m` box (a pad-sized patch, not a single lucky cell).
    Haworth is ~62% steeper than 15 deg, so an automatic flat-site finder is a real planning aid; this
    is the origin the local order frame anchors to so the slope gate fires on actual buildable ground."""
    Z, cell = dem
    smap = slope_deg_map(Z, cell)
    k = max(1, int(round(window_m / cell)))
    try:
        from scipy.ndimage import uniform_filter
        sm = uniform_filter(smap, size=k, mode="nearest")
    except Exception:
        sm = smap
    row, col = np.unravel_index(int(np.argmin(sm)), sm.shape)
    return float(col * cell), float(row * cell)


_PROJ_CACHE: dict = {}


def _proj_ctx(bundle_dir=None):
    """council #55 pass2 [7]: cache the per-bundle projection context (metadata + both pyproj Transformers) so a
    transect (up to 512 latlon_to_dem_origin calls) does NOT reload metadata.json + rebuild the Transformer per
    sample. Keyed by the resolved bundle path. Raises ImportError if pyproj (the [planner] extra) is absent."""
    bd = _haworth_bundle(bundle_dir)
    hit = _PROJ_CACHE.get(bd)
    if hit is not None:
        return hit
    from pyproj import Transformer
    meta = json.load(open(os.path.join(bd, "metadata.json")))
    g, b = meta["grid"], meta["world_bounds_m"]
    cell, W, H = float(g["cell_m"]), int(g["width"]), int(g["height"])
    crs = bundle_crs(bundle_dir)                                         # REG-01 / PLAN-ANYWHERE: the tile's own frame
    ax0, ay0 = float(b["x0"]) + cell / 2.0, float(b["y1"]) - cell / 2.0  # pixel(0,0) CENTER (north-up raster)
    fwd = Transformer.from_crs(crs.geodetic_crs, crs, always_xy=True)    # selenographic -> tile-frame m
    inv = Transformer.from_crs(crs, crs.geodetic_crs, always_xy=True)    # tile-frame m -> selenographic
    out = (cell, W, H, ax0, ay0, fwd, inv)
    _PROJ_CACHE[bd] = out
    return out


def latlon_to_dem_origin(lat, lon, *, bundle_dir=None):
    """M11: project a selenographic lat/lon (deg) to the Haworth DEM order-frame origin (x, y) [m] -- the
    SAME pixel-meter frame flattest_anchor returns -- so a globe site-pick anchors the plan where the user
    clicked instead of the auto flattest site. The DEM is south-polar stereographic on the R=1737400 m Moon
    sphere (IAU_2015:30135; see dem_import). Raises ValueError if the point falls outside the committed
    tile, ImportError if pyproj (the [planner] extra) is absent so the caller can fall back to the anchor."""
    cell, W, H, ax0, ay0, fwd, _inv = _proj_ctx(bundle_dir)
    xs, ys = fwd.transform(float(lon), float(lat))                       # selenographic -> tile-frame m
    col, row = (xs - ax0) / cell, (ay0 - ys) / cell
    if not (-0.5 <= col <= W - 0.5 and -0.5 <= row <= H - 0.5):
        raise ValueError(f"site lat/lon ({lat:.3f}, {lon:.3f}) is outside the mapped Haworth tile "
                         f"({W}x{H} @ {cell:g} m, IAU_2015:30135)")
    ci, ri = min(max(int(round(col)), 0), W - 1), min(max(int(round(row)), 0), H - 1)
    return float(ci * cell), float(ri * cell)                            # matches flattest_anchor's frame


def dem_origin_to_latlon(x, y, *, bundle_dir=None):
    """#174 (Aaron: "why are these in meters vs actual coordinates?"): the INVERSE of
    latlon_to_dem_origin -- project an order-frame position (x, y) [m] back to a selenographic lat/lon
    (deg), so the cockpit can show the actual coordinates next to the site metres for the lander, the
    rover's pose, and the placed landmarks. Same IAU_2015:30135 south-polar stereographic frame +
    pixel-center convention as the forward transform. Raises ValueError if (x, y) falls outside the
    committed tile, ImportError if pyproj (the [planner] extra) is absent so the caller can degrade to
    metres-only."""
    cell, W, H, ax0, ay0, _fwd, inv = _proj_ctx(bundle_dir)             # council #55 pass2 [7]: cached per bundle
    col, row = float(x) / cell, float(y) / cell
    if not (-0.5 <= col <= W - 0.5 and -0.5 <= row <= H - 0.5):
        raise ValueError(f"site (x, y) = ({x:.0f}, {y:.0f}) m is outside the mapped tile "
                         f"({W}x{H} @ {cell:g} m)")
    xs, ys = ax0 + col * cell, ay0 - row * cell                          # order-frame metres -> polar-stereographic m
    lon, lat = inv.transform(xs, ys)                                     # -> selenographic deg
    return float(lat), float(lon)


def grid_north_bearing_deg(x, y, *, bundle_dir=None):
    """#266: the TRUE selenographic bearing [deg, CW from north] of the DEM GRID's +row direction
    (dart.illumination's azimuth-0 axis) at order-frame point (x, y) [m]. The DEM is south-polar
    stereographic (IAU_2015:30135) kept north-up (row 0 = max stereo-Y), so +row points roughly SOUTH
    plus the meridian convergence -- NOT true north (empirically ~205.5 deg at the Haworth tile centre,
    lon -25.5). Measured by finite-difference of dem_origin_to_latlon along +y_dem (= +row), so it
    captures BOTH the projection convergence and the raster row orientation for any imported tile;
    gis_layers.grid_sun_az(true_az, this) then re-expresses a true sun azimuth in the grid frame.
    Raises ImportError if pyproj is absent (caller may skip the correction), ValueError only if (x, y)
    is off-tile by more than a cell either way."""
    import math
    g = json.load(open(os.path.join(_haworth_bundle(bundle_dir), "metadata.json")))["grid"]
    cell = float(g["cell_m"])
    lat0, lon0 = dem_origin_to_latlon(x, y, bundle_dir=bundle_dir)
    try:                                                          # +1 row = +y_dem = grid azimuth 0
        lat1, lon1 = dem_origin_to_latlon(x, y + cell, bundle_dir=bundle_dir); flip = 0.0
    except ValueError:                                           # at the top edge: step -row, reverse
        lat1, lon1 = dem_origin_to_latlon(x, y - cell, bundle_dir=bundle_dir); flip = 180.0
    p1, p2, dl = math.radians(lat0), math.radians(lat1), math.radians(lon1 - lon0)
    east = math.sin(dl) * math.cos(p2)
    north = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(east, north)) + flip) % 360.0


def dem_georef_corners(bundle_dir=None) -> dict:
    """The committed tile's GLOBE footprint: world_bounds_m corners (IAU_2015:30135 south-polar
    stereographic) inverse-projected to selenographic lat/lon -- so the cockpit can OVERLAY the
    Haworth work area on the Cesium globe at its true location (Aaron 2026-06-10: 'doesn't overlay
    the haworth site, this is the primary location')."""
    from pyproj import Transformer
    meta = json.load(open(os.path.join(_haworth_bundle(bundle_dir), "metadata.json")))
    b = meta["world_bounds_m"]
    crs = bundle_crs(bundle_dir)                                         # REG-01 / PLAN-ANYWHERE: the tile's own frame
    crs_label = (meta.get("georeference") or {}).get("crs_kind") or "IAU_2015:30135"
    inv = Transformer.from_crs(crs, crs.geodetic_crs, always_xy=True)
    corners = []
    for xs, ys in ((b["x0"], b["y0"]), (b["x1"], b["y0"]), (b["x1"], b["y1"]), (b["x0"], b["y1"])):
        lon, lat = inv.transform(float(xs), float(ys))
        corners.append({"lat": float(lat), "lon": float(lon)})
    cx, cy = (b["x0"] + b["x1"]) / 2.0, (b["y0"] + b["y1"]) / 2.0
    lon, lat = inv.transform(cx, cy)
    tile_km = round(abs(float(b["x1"]) - float(b["x0"])) / 1000.0, 3)
    return {"corners": corners, "center": {"lat": float(lat), "lon": float(lon)},
            "crs": crs_label, "tile_km": tile_km}


def dem_terrain_grid(n: int = 64, *, bundle_dir=None) -> dict:
    """REG-01 globe 3D layer: an ``n`` x ``n`` decimation of the chosen site's REAL LOLA DEM, every node
    georeferenced to selenographic lat/lon, for draping the work-area terrain as a 3D mesh layer on the
    Cesium globe (the same IAU_2015:30135 south-polar stereographic frame + pixel-center convention as
    dem_origin_to_latlon). ``z`` are the real DEM elevations [m]; lon/lat come from ONE VECTORIZED inverse
    projection of all n*n nodes (pyproj transforms arrays in a single call), NOT the ~1.8 ms-per-call
    point transform -- so an n=64 grid is one transform, not 4096. Row-major y-then-x like
    /dem/heightfield: index ``j*n + i`` is the node at DEM row ``ri[j]`` (North), col ``ci[i]`` (East).
    Raises ImportError if pyproj (the [planner] extra) is absent."""
    from pyproj import Transformer
    bundle = _haworth_bundle(bundle_dir)
    meta = json.load(open(os.path.join(bundle, "metadata.json")))
    g, b = meta["grid"], meta["world_bounds_m"]
    cell, W, H = float(g["cell_m"]), int(g["width"]), int(g["height"])
    Z, _cell = load_haworth_dem(bundle_dir=bundle_dir)
    n = max(2, min(int(n), 192))                                    # bound the browser grid / transport size
    ci = np.linspace(0, W - 1, n).round().astype(int)               # decimated col (East) + row (North) indices
    ri = np.linspace(0, H - 1, n).round().astype(int)
    heights = np.asarray(Z, dtype=float)[np.ix_(ri, ci)]            # n x n, row = y (North), col = x (East)
    ax0, ay0 = float(b["x0"]) + cell / 2.0, float(b["y1"]) - cell / 2.0   # pixel(0,0) CENTER (north-up raster)
    xs = ax0 + ci * cell                                            # tile-frame x per col
    ys = ay0 - ri * cell                                            # tile-frame y per row
    XS, YS = np.meshgrid(xs, ys)                                    # n x n projected coords
    crs = bundle_crs(bundle_dir)                                    # REG-01 / PLAN-ANYWHERE: the tile's own frame
    inv = Transformer.from_crs(crs, crs.geodetic_crs, always_xy=True)
    lon, lat = inv.transform(XS.ravel(), YS.ravel())               # ONE vectorized projected -> selenographic call
    lon = np.asarray(lon).reshape(n * n)
    lat = np.asarray(lat).reshape(n * n)
    return {"n": n, "cell_m": cell, "tile_m": [round(W * cell, 1), round(H * cell, 1)],
            "lat": [round(v, 6) for v in lat.tolist()],
            "lon": [round(v, 6) for v in lon.tolist()],
            "z": [round(v, 2) for v in heights.ravel().tolist()],
            "z_min": float(heights.min()), "z_max": float(heights.max())}
