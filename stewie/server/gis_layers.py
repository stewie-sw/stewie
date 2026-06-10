"""GIS raster layers over the REAL Haworth work-area DEM (the 2D planning substrate).

Each layer is computed by the existing dart machinery and rendered as an RGBA PNG overlay sized to
the work-area frame: slope (height-field gradient), hazard (build_hazard_map cost: graded amber ->
no-go red), illumination/shadow (horizon_clip at a commanded south-pole sun geometry -- shadows are
the NAVIGATION signal at Haworth, the same physics the shadow-SLAM track estimates against), and
PSR candidates (never lit across a sweep of sun azimuths at polar elevation). Rasters are cached by
(kind, params); the DEM never changes under the server.
"""
from __future__ import annotations

import io

import numpy as np

_CACHE: dict = {}


def _work_area(mp):
    """The work-area crop the planner frames: load_haworth_dem returns (heightmap, cell_m); the
    flattest-anchor gives the site center in DEM meters."""
    pair = mp.load_haworth_dem()                         # the (heightmap, cell_m) tuple
    dem, cell_m = pair
    ax, ay = mp.flattest_anchor(pair)                    # takes the PAIR; returns (x, y) DEM meters
    r0 = int(ay / cell_m); c0 = int(ax / cell_m)
    half = 64                                            # 128x128 cells @5 m = 640 m frame
    r0 = max(0, min(dem.shape[0] - 2 * half, r0 - half))
    c0 = max(0, min(dem.shape[1] - 2 * half, c0 - half))
    return dem[r0:r0 + 2 * half, c0:c0 + 2 * half], (r0, c0), float(cell_m)


def _to_png(rgba: np.ndarray) -> bytes:
    from imageio.v3 import imwrite
    buf = io.BytesIO()
    imwrite(buf, rgba.astype(np.uint8), extension=".png")
    return buf.getvalue()


def _upscale(a: np.ndarray, k: int = 4) -> np.ndarray:
    return np.repeat(np.repeat(a, k, axis=0), k, axis=1)


def render(kind: str, *, cell_m: float = 5.0, sun_el: float = 6.0, sun_az: float = 90.0,
           mp=None) -> bytes | None:
    """Render one raster layer as PNG bytes; None for unknown kinds."""
    if mp is None:
        from lode import mission_planner as mp
    key = (kind, round(float(sun_el), 2), round(float(sun_az), 2))
    if key in _CACHE:
        return _CACHE[key]
    dem, _, cell_m = _work_area(mp)

    if kind == "slope":
        gy, gx = np.gradient(dem, cell_m)
        slope = np.degrees(np.arctan(np.hypot(gx, gy)))
        t = np.clip(slope / 30.0, 0, 1)
        rgba = np.zeros((*slope.shape, 4))
        rgba[..., 0] = 60 + 195 * t                      # green->red ramp
        rgba[..., 1] = 200 * (1 - t)
        rgba[..., 2] = 40
        rgba[..., 3] = 90 + 120 * t                      # steeper = more opaque
    elif kind == "hazard":
        from dart.hazard_map import build_hazard_map
        hm = build_hazard_map((dem, cell_m))             # the (Z, cell_m) pair convention
        cost = np.asarray(hm.cost, dtype=float)
        nogo = ~np.isfinite(cost)
        graded = np.clip((np.where(np.isfinite(cost), cost, 0.0) - 1.0) / 4.0, 0, 1)
        rgba = np.zeros((*cost.shape, 4))
        rgba[..., 0] = 255
        rgba[..., 1] = 140 * (1 - graded)
        rgba[..., 3] = np.where(nogo, 230, 170 * graded)  # transparent where benign
        rgba[nogo, 1] = 0
    elif kind == "illumination":
        from dart.illumination import horizon_clip
        lit = horizon_clip(dem, cell_m, float(sun_az), float(sun_el))
        rgba = np.zeros((*lit.shape, 4))
        rgba[..., 2] = 180                               # shadow = translucent blue-black
        rgba[..., 3] = np.where(lit, 0, 165)
    elif kind == "psr":
        from dart.illumination import horizon_clip
        ever_lit = np.zeros(dem.shape, dtype=bool)
        for az in range(0, 360, 30):                     # polar sun sweep at max elevation
            ever_lit |= horizon_clip(dem, cell_m, float(az), 3.0)
        rgba = np.zeros((*dem.shape, 4))
        rgba[..., 0] = 90; rgba[..., 2] = 200
        rgba[..., 3] = np.where(ever_lit, 0, 200)        # PSR candidates: never lit in the sweep
    else:
        return None
    png = _to_png(_upscale(rgba))
    _CACHE[key] = png
    return png


RASTER_DEFS = [
    {"key": "slope", "name": "Slope (deg, from the real DEM)", "kind": "raster", "group": "terrain"},
    {"key": "hazard", "name": "Hazard / no-go (nav cost)", "kind": "raster", "group": "safety",
     "default": True},   # T6.1: the routing round-trip -- routes detour on the SAME layer the user sees
    {"key": "illumination", "name": "Shadow (horizon-clipped sun)", "kind": "raster", "group": "sun"},
    {"key": "psr", "name": "PSR candidates (never lit)", "kind": "raster", "group": "sun"},
]


# ---- the GLOBE drape: reproject polar-stereo rasters to GEOGRAPHIC grids -----------------------
# Aaron's screenshot (2026-06-10): a stereographic image draped into a lat/lon rectangle renders
# ROTATED/misaligned. The standard GIS fix: resample onto a lat/lon grid server-side; every layer
# carries ITS OWN bbox. Implementation: build the output lat/lon grid, forward-project each output
# pixel into the polar-stereo frame (pyproj, IAU_2015:30135 -- the SAME CRS as the tile bounds),
# and sample the source raster. Vectorized numpy; cached by (kind, sun params).

_GLOBE_CACHE: dict = {}


def _tile_geo(mp):
    """(heightmap, cell_m, world_bounds dict, the pyproj fwd transformer)."""
    import json as _json
    import os as _os

    from pyproj import CRS, Transformer
    pair = mp.load_haworth_dem()
    meta = _json.load(open(_os.path.join(mp._haworth_bundle(None), "metadata.json")))
    crs = CRS.from_user_input("IAU_2015:30135")
    fwd = Transformer.from_crs(crs.geodetic_crs, crs, always_xy=True)
    return pair[0], float(pair[1]), meta["world_bounds_m"], fwd


def _reproject(source_rgba, b, fwd, *, out_px: int = 1024, sub=None):
    """Resample an RGBA raster (north-up in the stereo frame, extent = b or the sub-window) onto a
    geographic grid. Returns (rgba_geo uint8, bbox{south,north,west,east})."""
    import numpy as _np
    if sub is not None:
        x0, y0, x1, y1 = sub
    else:
        x0, y0, x1, y1 = b["x0"], b["y0"], b["x1"], b["y1"]
    # the geographic bbox: project a dense ring of the extent's boundary to lat/lon
    t = _np.linspace(0.0, 1.0, 64)
    ring_x = _np.concatenate([x0 + (x1 - x0) * t, _np.full(64, x1), x1 - (x1 - x0) * t, _np.full(64, x0)])
    ring_y = _np.concatenate([_np.full(64, y0), y0 + (y1 - y0) * t, _np.full(64, y1), y1 - (y1 - y0) * t])
    from pyproj import CRS, Transformer
    crs = CRS.from_user_input("IAU_2015:30135")
    inv = Transformer.from_crs(crs, crs.geodetic_crs, always_xy=True)
    lons, lats = inv.transform(ring_x, ring_y)
    bbox = {"south": float(lats.min()), "north": float(lats.max()),
            "west": float(lons.min()), "east": float(lons.max())}
    # the output grid -> stereo coords -> source pixel indices
    H = out_px
    W = max(64, int(out_px * (bbox["east"] - bbox["west"])
                    / max(1e-9, (bbox["north"] - bbox["south"])) *
                    _np.cos(_np.radians((bbox["south"] + bbox["north"]) / 2.0))))
    W = min(W, 4096)
    lon_g, lat_g = _np.meshgrid(_np.linspace(bbox["west"], bbox["east"], W),
                                _np.linspace(bbox["north"], bbox["south"], H))
    xs, ys = fwd.transform(lon_g, lat_g)
    sh, sw = source_rgba.shape[:2]
    col = (xs - x0) / (x1 - x0) * (sw - 1)
    row = (y1 - ys) / (y1 - y0) * (sh - 1)              # north-up raster: row 0 = y1
    valid = (col >= 0) & (col <= sw - 1) & (row >= 0) & (row <= sh - 1)
    ci = _np.clip(col.round().astype(int), 0, sw - 1)
    ri = _np.clip(row.round().astype(int), 0, sh - 1)
    out = source_rgba[ri, ci]
    out[~valid] = 0                                      # transparent outside the true footprint
    return out.astype("uint8"), bbox


def render_globe(kind: str, *, sun_el: float = 6.0, sun_az: float = 90.0, mp=None):
    """The geographic drape for the globe: 'dem' = the full-tile hillshade; the GIS rasters
    reproject over the WORK AREA's own extent. Returns (rgba uint8, bbox)."""
    if mp is None:
        from lode import mission_planner as mp
    key = ("globe", kind, round(float(sun_el), 2), round(float(sun_az), 2))
    if key in _GLOBE_CACHE:
        return _GLOBE_CACHE[key]
    import os as _os

    import numpy as _np
    from imageio.v3 import imread
    dem_full, cell_m, b, fwd = _tile_geo(mp)
    if kind == "dem":
        shade = imread(_os.path.join(mp._haworth_bundle(None), "preview_hillshade.png"))
        if shade.ndim == 2:
            shade = _np.stack([shade] * 3, axis=2)
        rgba = _np.dstack([shade[..., :3], _np.full(shade.shape[:2], 255, dtype="uint8")])
        out = _reproject(rgba, b, fwd, out_px=1024)
    else:
        png = render(kind, sun_el=sun_el, sun_az=sun_az, mp=mp)
        if png is None:
            return None
        import io as _io
        rgba = imread(_io.BytesIO(png))
        # the work-area window inside the tile (the SAME crop _work_area uses)
        _, (r0, c0), _ = _work_area(mp)
        side = 128
        sub = (b["x0"] + c0 * cell_m, b["y1"] - (r0 + side) * cell_m,
               b["x0"] + (c0 + side) * cell_m, b["y1"] - r0 * cell_m)
        out = _reproject(rgba, {"x0": sub[0], "y0": sub[1], "x1": sub[2], "y1": sub[3]},
                         fwd, out_px=512, sub=None)
    _GLOBE_CACHE[key] = out
    return out
