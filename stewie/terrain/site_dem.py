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
    site is unknown or not imported -- no fabricated terrain."""
    from stewie.specs.sites import SITES
    s = SITES.get(site)
    if s is None:
        raise KeyError(f"unknown site {site!r} (known: {sorted(SITES)})")
    if site == "haworth":
        return load_haworth_dem()                 # the work site honors $STEWIE_DEM_DIR (deployment override)
    if not s.bundle_dir:
        raise FileNotFoundError(f"site {site!r} is not imported (no DEM bundle); fetch it first")
    return load_haworth_dem(bundle_dir=s.bundle_dir)


def load_haworth_dem(bundle_dir=None):
    """Load a real LOLA 5 m DEM from a sim bundle: returns (heightmap [m], cell_m). Defaults to the
    Haworth work-site bundle; ``bundle_dir`` selects another imported site (REG-01)."""
    bundle = _haworth_bundle(bundle_dir)
    if not os.path.exists(os.path.join(bundle, "heightmap.rf32")):
        raise FileNotFoundError(
            f"Haworth DEM not found at {bundle}. It is NOT bundled in the wheel -- fetch it "
            "(PGDA Product 78): run `stewie-fetch-dem --source <mirror>` or set STEWIE_DEM_URL "
            "(see planet_browser/assets_manifest.json).")
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


def latlon_to_dem_origin(lat, lon, *, bundle_dir=None):
    """M11: project a selenographic lat/lon (deg) to the Haworth DEM order-frame origin (x, y) [m] -- the
    SAME pixel-meter frame flattest_anchor returns -- so a globe site-pick anchors the plan where the user
    clicked instead of the auto flattest site. The DEM is south-polar stereographic on the R=1737400 m Moon
    sphere (IAU_2015:30135; see dem_import). Raises ValueError if the point falls outside the committed
    tile, ImportError if pyproj (the [planner] extra) is absent so the caller can fall back to the anchor."""
    from pyproj import CRS, Transformer
    meta = json.load(open(os.path.join(_haworth_bundle(bundle_dir), "metadata.json")))
    g, b = meta["grid"], meta["world_bounds_m"]
    cell, W, H = float(g["cell_m"]), int(g["width"]), int(g["height"])
    crs = CRS.from_user_input("IAU_2015:30135")
    fwd = Transformer.from_crs(crs.geodetic_crs, crs, always_xy=True)
    xs, ys = fwd.transform(float(lon), float(lat))                       # selenographic -> polar-stereographic m
    ax0, ay0 = float(b["x0"]) + cell / 2.0, float(b["y1"]) - cell / 2.0  # pixel(0,0) CENTER (north-up raster)
    col, row = (xs - ax0) / cell, (ay0 - ys) / cell
    if not (-0.5 <= col <= W - 0.5 and -0.5 <= row <= H - 0.5):
        raise ValueError(f"site lat/lon ({lat:.3f}, {lon:.3f}) is outside the mapped Haworth tile "
                         f"({W}x{H} @ {cell:g} m, IAU_2015:30135)")
    ci, ri = min(max(int(round(col)), 0), W - 1), min(max(int(round(row)), 0), H - 1)
    return float(ci * cell), float(ri * cell)                            # matches flattest_anchor's frame


def dem_georef_corners(bundle_dir=None) -> dict:
    """The committed tile's GLOBE footprint: world_bounds_m corners (IAU_2015:30135 south-polar
    stereographic) inverse-projected to selenographic lat/lon -- so the cockpit can OVERLAY the
    Haworth work area on the Cesium globe at its true location (Aaron 2026-06-10: 'doesn't overlay
    the haworth site, this is the primary location')."""
    from pyproj import CRS, Transformer
    meta = json.load(open(os.path.join(_haworth_bundle(bundle_dir), "metadata.json")))
    b = meta["world_bounds_m"]
    crs = CRS.from_user_input("IAU_2015:30135")
    inv = Transformer.from_crs(crs, crs.geodetic_crs, always_xy=True)
    corners = []
    for xs, ys in ((b["x0"], b["y0"]), (b["x1"], b["y0"]), (b["x1"], b["y1"]), (b["x0"], b["y1"])):
        lon, lat = inv.transform(float(xs), float(ys))
        corners.append({"lat": float(lat), "lon": float(lon)})
    cx, cy = (b["x0"] + b["x1"]) / 2.0, (b["y0"] + b["y1"]) / 2.0
    lon, lat = inv.transform(cx, cy)
    return {"corners": corners, "center": {"lat": float(lat), "lon": float(lon)},
            "crs": "IAU_2015:30135", "tile_km": 10.0}
