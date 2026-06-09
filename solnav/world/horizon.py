"""Horizon-profile localization factor.

Ray-cast the expected skyline -- the maximum terrain elevation angle per azimuth -- from the orbital DEM
(L0) at a candidate pose, and match it to the rover's observed horizon. The skyline is made of DISTANT
ridges, rims, and massifs, so it is IMMUNE to local excavation: even after the rover reshapes everything
around it, the horizon profile still pins its global position. Pairs with landmarks.py (the immutable
anchors). Real DEM only.
"""
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


def horizon_profile(dem, dem_origin, x, y, *, observer_height_m: float = 1.5, n_az: int = 72,
                    max_range_m: float = 5000.0, step_m: float | None = None) -> np.ndarray:
    """Skyline elevation-angle profile (radians) at (x,y): for each of n_az azimuths, ray-march outward
    and take the MAX elevation angle to the terrain (the horizon crest). Excavation-immune (distant)."""
    z = np.asarray(dem[0], dtype=float)
    cell = float(dem[1])
    step = step_m if step_m else cell
    z0 = _height_at(z, cell, dem_origin, x, y)
    if z0 is None:
        return np.full(n_az, -math.pi / 2)
    z0 += observer_height_m
    prof = np.full(n_az, -math.pi / 2)
    for a in range(n_az):
        az = 2 * math.pi * a / n_az
        dx, dy = math.cos(az), math.sin(az)
        best = -math.pi / 2
        s = step
        while s <= max_range_m:
            zh = _height_at(z, cell, dem_origin, x + dx * s, y + dy * s)
            if zh is None:
                break
            ang = math.atan2(zh - z0, s)
            if ang > best:
                best = ang
            s += step
        prof[a] = best
    return prof


def horizon_distance(p_observed, p_candidate) -> float:
    """RMS angular difference (rad) between two horizon profiles -> the match residual."""
    a = np.asarray(p_observed, dtype=float)
    b = np.asarray(p_candidate, dtype=float)
    return float(np.sqrt(np.mean((a - b) ** 2)))


def match_horizon(observed_profile, dem, dem_origin, candidates, **kw):
    """Best-fit candidate pose by horizon match -> (best_xy, residual, all_residuals). A global-position
    constraint robust to local terrain change."""
    res = [(horizon_distance(observed_profile, horizon_profile(dem, dem_origin, cx, cy, **kw)), (cx, cy))
           for cx, cy in candidates]
    res.sort()
    return res[0][1], res[0][0], res
