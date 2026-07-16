"""Visibility-as-measurement.

From the orbital DEM (L0) + a candidate pose, predict WHICH persistent landmarks SHOULD be visible vs
terrain-occluded. "From here I should see crater A and NOT ridge B" is itself a localization measurement
-- nearly free, and robust to local excavation because the occluders are DISTANT ridges, not the soil the
rover is reshaping. Compare the predicted visibility to the rover's actual detections -> a binary/where
localization factor that pins position even when shadows and local terrain have changed. Real DEM only.
"""
# PROVENANCE: STEWIE DART subsystem (A. Storey)
from __future__ import annotations

import math

import numpy as np


def _height_at(z, cell, origin, x, y):
    c = (x - origin[0]) / cell
    r = (y - origin[1]) / cell
    ri, ci = int(round(r)), int(round(c))
    if 0 <= ri < z.shape[0] and 0 <= ci < z.shape[1]:
        return float(z[ri, ci])
    return None


def is_visible(dem, dem_origin, observer_xy, target_xy, *, observer_height_m: float = 1.5,
               target_height_m: float = 0.0) -> bool:
    """Line-of-sight: march from observer to target; occluded if any terrain cell along the ray rises
    above the straight line of sight (the ridge between them blocks it)."""
    z = np.asarray(dem[0], dtype=float)
    cell = float(dem[1])
    ox, oy = observer_xy
    tx, ty = target_xy
    z0 = _height_at(z, cell, dem_origin, ox, oy)
    zt = _height_at(z, cell, dem_origin, tx, ty)
    if z0 is None or zt is None:
        return False
    z0 += observer_height_m
    zt += target_height_m
    dist = math.hypot(tx - ox, ty - oy)
    if dist < cell:
        return True
    n = max(2, int(math.ceil(dist / cell)) + 1)   # step < cell so a thin (1-cell) occluder cannot be
    # stepped over by the floor division (audit L22)
    for i in range(1, n):
        f = i / n
        xx, yy = ox + (tx - ox) * f, oy + (ty - oy) * f
        zh = _height_at(z, cell, dem_origin, xx, yy)
        if zh is None:
            return False
        los = z0 + (zt - z0) * f                     # the straight line-of-sight height at this fraction
        if zh > los + 1e-6:                           # terrain rises above the sightline -> occluded
            return False
    return True


def viewshed(dem, dem_origin, anchors, *, observer_height_m: float = 1.5,
             target_height_m: float = 0.0) -> np.ndarray:
    """r.viewshed-class line-of-sight raster (terrain.los) from the site DEM + localization anchor(s).

    For every ground cell, marks True where a mast-height observer standing at that cell has line-of-sight
    to AT LEAST ONE anchor, False where every anchor is terrain-occluded. This is exactly the sightline a
    fiducial pose-lock needs: a cell blind to all anchors cannot get an AprilTag fix. The result is the
    ``terrain.los`` raster that SN-05's visibility route-cost term consumes (a named producer instead of the
    inline per-route march). Reuses the audited per-cell ``is_visible`` LOS march, so the raster is the exact
    cell-wise line-of-sight over the REAL DEM -- no fabricated drape, no fitted surrogate.

    dem: (heightmap, cell_m). dem_origin: world (x0, y0) of cell (0, 0). anchors: [(x, y), ...] world
    positions of localization anchors (lander / fiducials). Returns a (H, W) boolean array.
    """
    z = np.asarray(dem[0], dtype=float)
    cell = float(dem[1])
    demc = (z, cell)
    ox0, oy0 = float(dem_origin[0]), float(dem_origin[1])
    los = np.zeros(z.shape, dtype=bool)
    anchor_xy = [(float(ax), float(ay)) for ax, ay in anchors]
    for ri in range(z.shape[0]):
        wy = oy0 + ri * cell
        for ci in range(z.shape[1]):
            wx = ox0 + ci * cell
            los[ri, ci] = any(
                is_visible(demc, dem_origin, (wx, wy), a,
                           observer_height_m=observer_height_m, target_height_m=target_height_m)
                for a in anchor_xy)
    return los


def predict_visibility(dem, dem_origin, observer_xy, landmarks, **kw) -> list:
    """Per-landmark predicted visibility from observer_xy. Returns [(landmark, visible:bool)]."""
    return [(lm, is_visible(dem, dem_origin, observer_xy, (lm.x, lm.y), **kw)) for lm in landmarks]


def visibility_consistency(predicted, observed_visible_ids) -> float:
    """Match score in [0,1]: fraction of landmarks whose predicted visibility agrees with what the rover
    actually detected (observed_visible_ids). A localization measurement -- maximized at the true pose."""
    obs = set(observed_visible_ids)
    if not predicted:
        return 0.0
    agree = sum(1 for lm, vis in predicted if (lm.id in obs) == vis)
    return agree / len(predicted)
