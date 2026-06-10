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
