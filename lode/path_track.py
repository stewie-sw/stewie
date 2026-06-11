"""Planned-vs-actual path tracking on the real DEM -- the 2D->3D->2D navigation loop.

Drape a 2-D map path onto the 3-D terrain (DEM heights), measure the cross-track deviation of the actual
driven path vs the planned route, and decide when to REPLAN (the actual deviated past a threshold, or a
classified D/E hazard was discovered within sensor range). Pure geometry: the planner (route_leg) and the
drive (slip physics) are INJECTED by the caller, so this stays dependency-light and testable. Closes
detect -> classify -> cost -> plan -> drive -> deviate -> replan on the actual map.
"""
# PROVENANCE: STEWIE DART subsystem (A. Storey)
from __future__ import annotations

import numpy as np


def drape_path(path_xy, dem, dem_origin=(0.0, 0.0)) -> np.ndarray:
    """2-D map path -> 3-D path on the terrain: append the DEM height at each (x, y). The 2D->3D step."""
    z, cell = np.asarray(dem[0]), float(dem[1])
    ox, oy = dem_origin
    out = []
    for x, y in path_xy:
        # world->cell uses MINUS origin (the +origin here was the same latent sign bug fixed in
        # hazard_map); off-DEM points get NaN height instead of a clamped-edge LIE (audit M11)
        r = int(round((y - oy) / cell))
        c = int(round((x - ox) / cell))
        hgt = float(z[r, c]) if (0 <= r < z.shape[0] and 0 <= c < z.shape[1]) else float("nan")
        out.append((float(x), float(y), hgt))
    return np.array(out)


def _point_segment_dist(pt, a, b) -> float:
    ab = b - a
    t = float(np.clip(np.dot(pt - a, ab) / (np.dot(ab, ab) + 1e-12), 0.0, 1.0))
    return float(np.linalg.norm(pt - (a + t * ab)))


def cross_track_deviation(planned, actual):
    """Per-actual-point perpendicular distance to the planned POLYLINE (point-to-segment cross-track
    error, not point-to-vertex). Returns (dev, mean, max)."""
    if len(planned) == 0 or len(actual) == 0:        # empty traverse -> no deviation (no crash)
        z = np.zeros(0)
        return z, 0.0, 0.0
    p = np.asarray(planned, dtype=float)[:, :2]
    a = np.asarray(actual, dtype=float)[:, :2]
    if len(p) >= 2:
        dev = np.array([min(_point_segment_dist(pt, p[j], p[j + 1]) for j in range(len(p) - 1)) for pt in a])
    elif len(p) == 1:
        dev = np.linalg.norm(a - p[0], axis=1)
    else:
        dev = np.zeros(len(a))
    return dev, (float(dev.mean()) if len(dev) else 0.0), (float(dev.max()) if len(dev) else 0.0)


def discover_hazards(pos, hazards_world, *, sensor_range_m: float = 18.0, known=()):
    """Classified D/E hazards within sensor range of the rover that aren't already known. Each hazard is
    (x, y, Rock); only obstacles (nav D/E) are returned -> the caller turns them into keep-outs + replans."""
    p = np.asarray(pos, dtype=float)
    kk = {(round(k["x"], 3), round(k["y"], 3)) for k in known}
    out = []
    for x, y, rk in hazards_world:
        if rk.nav_class in ("D", "E") and rk.is_obstacle \
                and np.hypot(x - p[0], y - p[1]) < sensor_range_m and (round(x, 3), round(y, 3)) not in kk:
            out.append((x, y, rk))
    return out


def needs_replan(pos, planned, hazards_world, *, sensor_range_m: float = 18.0,
                 deviation_max_m: float = 8.0, known=()):
    """Replan trigger: a newly discovered D/E hazard within sensor range, OR the actual position deviated
    past deviation_max_m from the planned route. Returns (replan: bool, new_hazards: list)."""
    new = discover_hazards(pos, hazards_world, sensor_range_m=sensor_range_m, known=known)
    _, _, mx = cross_track_deviation(planned, [pos]) if len(planned) else (None, 0.0, 0.0)
    return (bool(new) or mx > deviation_max_m), new
