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
    {"key": "psr", "name": "Permanently shadowed regions (PSR, never lit)", "kind": "raster", "group": "sun"},
    {"key": "grid", "name": "Site grid (100 m / 500 m)", "kind": "raster", "group": "reference", "default": True},
]


# ---- the GLOBE drape: reproject polar-stereo rasters to GEOGRAPHIC grids -----------------------
# Aaron's screenshot (2026-06-10): a stereographic image draped into a lat/lon rectangle renders
# ROTATED/misaligned. The standard GIS fix: resample onto a lat/lon grid server-side; every layer
# carries ITS OWN bbox. Implementation: build the output lat/lon grid, forward-project each output
# pixel into the polar-stereo frame (pyproj, IAU_2015:30135 -- the SAME CRS as the tile bounds),
# and sample the source raster. Vectorized numpy; cached by (kind, sun params).

_GLOBE_CACHE: dict = {}

def _np_load_rgba(path):
    import numpy as _np
    return _np.load(path)



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


def render_globe(kind: str, *, sun_el: float = 6.0, sun_az: float = 90.0, mp=None,
                 grid_color: str = "39ff14"):
    """The geographic drape for the globe: 'dem' = the full-tile hillshade; the GIS rasters
    reproject over the WORK AREA's own extent. Returns (rgba uint8, bbox)."""
    if mp is None:
        from lode import mission_planner as mp
    key = ("globe", kind, round(float(sun_el), 2), round(float(sun_az), 2),
           grid_color if kind == "grid" else "")
    if key in _GLOBE_CACHE:
        return _GLOBE_CACHE[key]
    # disk cache: survive restarts; PSR/illumination cost seconds-to-minutes to compute
    import json as _json
    import os as _oss
    from stewie.specs import config as _CFG
    cdir = _oss.path.join(_CFG.data_dir(), "globe_cache")
    _oss.makedirs(cdir, exist_ok=True)
    stem = _oss.path.join(cdir, f"{kind}_{key[2]}_{key[3]}" + (f"_{grid_color}" if kind == "grid" else ""))
    if _oss.path.exists(stem + ".npy") and _oss.path.exists(stem + ".json"):
        out = (_np_load_rgba(stem + ".npy"), _json.load(open(stem + ".json")))
        _GLOBE_CACHE[key] = out
        return out
    import os as _os

    import numpy as _np
    from imageio.v3 import imread
    dem_full, cell_m, b, fwd = _tile_geo(mp)
    if kind == "dem":
        # CLEAN cartographic hillshade computed from the RAW heightmap (Aaron's 2nd screenshot:
        # preview_hillshade.png is a matplotlib FIGURE -- axis labels + white margins were being
        # draped onto the Moon). Standard 315/45 lambertian; the real-sun SHADOW layer is separate.
        gy, gx = _np.gradient(_np.asarray(dem_full, dtype=float), cell_m)
        az, el = _np.radians(315.0), _np.radians(45.0)
        nx, ny, nz = -gx, -gy, _np.ones_like(gx)
        norm = _np.sqrt(nx * nx + ny * ny + nz * nz)
        lx = _np.cos(el) * _np.sin(az); ly = _np.cos(el) * _np.cos(az); lz = _np.sin(el)
        shade01 = _np.clip((nx * lx + ny * ly + nz * lz) / norm, 0.0, 1.0)
        g8 = (40 + shade01 * 200).astype("uint8")        # lift the floor so shadows stay readable
        rgba = _np.dstack([g8, g8, g8, _np.full(g8.shape, 255, dtype="uint8")])
        out = _reproject(rgba, b, fwd, out_px=1024)
    else:
        # FULL-TILE analysis rasters for the globe (Aaron 2026-06-10: "when hazard is clicked the
        # full tile isn't loaded") -- computed from the whole heightmap at a working downsample;
        # the work-area crop remains the inset's product. Disclosure: ROCK hazards exist only
        # where mapped (the surveyed crop); the full-tile hazard is slope-derived.
        # PSR's 12-azimuth horizon sweep measured 44 s at 768px (Aaron: "psr does not load in
        # main screen") -- the sweep runs at 384px (~4x faster, same 30-deg azimuth step); other
        # kinds keep 768. Products disk-cache under data_dir so each computes ONCE per sun key.
        if kind == "grid":
            # #54: the site reference grid (the lunar-ops analog of MGRS): site-frame eastings/
            # northings every 100 m (minor) and 500 m (major). Labels live in the inset axes +
            # the cursor's site-meters readout; the drape carries the LINES.
            n = 1000                                       # 10 m/px over the 10 km tile
            # color chosen by the operator (Aaron: white is unreadable over hazard/slope;
            # default = neon wiremesh green)
            h = grid_color.lstrip("#")
            try:
                cr, cg, cb = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            except (ValueError, IndexError):
                cr, cg, cb = 0x39, 0xFF, 0x14
            rgba = _np.zeros((n, n, 4), dtype="uint8")
            for m in range(0, 10001, 100):
                i = min(n - 1, int(m / 10000 * n))
                major = (m % 500 == 0)
                a = 170 if major else 80
                for ch, v in ((0, cr), (1, cg), (2, cb)):
                    rgba[i, :, ch] = v; rgba[:, i, ch] = v
                rgba[i, :, 3] = _np.maximum(rgba[i, :, 3], a)
                rgba[:, i, 3] = _np.maximum(rgba[:, i, 3], a)
            out = _reproject(rgba, b, fwd, out_px=1024)
            _GLOBE_CACHE[key] = out
            return out
        px = 384 if kind == "psr" else 768
        stride = max(1, dem_full.shape[0] // px)
        dem = _np.asarray(dem_full, dtype=float)[::stride, ::stride]
        cm = cell_m * stride
        if kind == "slope":
            gy, gx = _np.gradient(dem, cm)
            slope = _np.degrees(_np.arctan(_np.hypot(gx, gy)))
            t = _np.clip(slope / 30.0, 0, 1)
            rgba = _np.zeros((*slope.shape, 4))
            rgba[..., 0] = 60 + 195 * t; rgba[..., 1] = 200 * (1 - t); rgba[..., 2] = 40
            rgba[..., 3] = 90 + 120 * t
        elif kind == "hazard":
            gy, gx = _np.gradient(dem, cm)
            slope = _np.degrees(_np.arctan(_np.hypot(gx, gy)))
            nogo = slope > 20.0                            # the TESTED envelope [WHEELTEST]
            graded = _np.clip((slope - 15.0) / 5.0, 0, 1)  # nominal->tested band
            rgba = _np.zeros((*slope.shape, 4))
            rgba[..., 0] = 255; rgba[..., 1] = 140 * (1 - graded)
            rgba[..., 3] = _np.where(nogo, 230, 170 * graded)
            rgba[nogo, 1] = 0
        elif kind == "illumination":
            from dart.illumination import horizon_clip
            lit = horizon_clip(dem, cm, float(sun_az), float(sun_el))
            rgba = _np.zeros((*lit.shape, 4))
            rgba[..., 2] = 180; rgba[..., 3] = _np.where(lit, 0, 165)
        elif kind == "psr":
            from dart.illumination import horizon_clip
            ever_lit = _np.zeros(dem.shape, dtype=bool)
            for az in range(0, 360, 30):
                ever_lit |= horizon_clip(dem, cm, float(az), 3.0)
            rgba = _np.zeros((*dem.shape, 4))
            rgba[..., 0] = 90; rgba[..., 2] = 200
            rgba[..., 3] = _np.where(ever_lit, 0, 200)
        else:
            return None
        out = _reproject(rgba.astype("uint8"), b, fwd, out_px=1024)
    _GLOBE_CACHE[key] = out
    try:
        import json as _json
        import numpy as _np2
        _np2.save(stem + ".npy", out[0])
        _json.dump(out[1], open(stem + ".json", "w"))
    except OSError:
        pass
    return out
