"""DEM-layer cross-analysis: cross-validate imagery obstacle detections against the PRIOR DEM's derived
geometric layers (height-residual, slope, roughness).

An obstacle confirmed by BOTH the imagery AND a DEM geometric anomaly at the same world location is
high-confidence (precision up); an imagery detection with no DEM support is a likely false positive
(cut). The geometry (slope/roughness/residual) is DOMAIN-AGNOSTIC -- this is the key that makes the
Mars->lunar transfer honest (a steep/rough/protruding cell is a hazard on any body). Dataset-agnostic:
takes ANY prior DEM (LOLA / MOLA / HiRISE / sim) + the perception's obstacle world positions; the
observed heights (from the rover's stereo) give the residual layer when supplied. Real DEM derivatives
only -- no synthetic terrain.
"""
from __future__ import annotations

import numpy as np
from scipy.ndimage import uniform_filter


def dem_layers(dem, dem_origin=(0.0, 0.0), *, rough_window: int = 5) -> dict:
    """Derive geometric layers from a prior DEM (Z [m], cell_m): per-cell slope (deg) and local roughness
    (windowed height std, high over blocky/rocky terrain). Real DEM derivatives."""
    z, cell = np.asarray(dem[0], dtype=float), float(dem[1])
    gy, gx = np.gradient(z, cell)
    slope_deg = np.degrees(np.arctan(np.hypot(gx, gy)))
    mean = uniform_filter(z, rough_window)
    mean_sq = uniform_filter(z * z, rough_window)
    roughness = np.sqrt(np.clip(mean_sq - mean * mean, 0.0, None))
    return {"slope_deg": slope_deg, "roughness_m": roughness, "height_m": z,
            "cell_m": cell, "origin": (float(dem_origin[0]), float(dem_origin[1]))}


def _at(layer, x: float, y: float, cell: float, origin) -> float | None:
    c = int(round((x - origin[0]) / cell))
    r = int(round((y - origin[1]) / cell))
    h, w = layer.shape
    return float(layer[r, c]) if (0 <= r < h and 0 <= c < w) else None


def cross_analyze(obstacles_xy, layers: dict, *, observed_heights=None, slope_hazard_deg: float = 20.0,
                  roughness_thresh_m: float = 0.05, residual_thresh_m: float = 0.075) -> list:
    """Per-obstacle DEM cross-check. Each obstacle world (x, y) is CONFIRMED if the prior DEM shows
    geometric support there -- steep slope, high roughness, OR (with observed_heights) a positive height
    residual (the rover's observed surface protrudes above the prior by > the IPEx clearance). Returns
    one record per obstacle. Cross-validation = imagery detection x DEM geometry -> cut FPs, keep TPs."""
    cell, origin = layers["cell_m"], layers["origin"]
    out = []
    for i, ob in enumerate(obstacles_xy):
        x, y = float(ob[0]), float(ob[1])
        sl = _at(layers["slope_deg"], x, y, cell, origin)
        ro = _at(layers["roughness_m"], x, y, cell, origin)
        hz = _at(layers["height_m"], x, y, cell, origin)
        res = (float(observed_heights[i]) - hz) if (observed_heights is not None and hz is not None) else None
        reasons = []
        if sl is not None and sl >= slope_hazard_deg:
            reasons.append("steep")
        if ro is not None and ro >= roughness_thresh_m:
            reasons.append("rough")
        if res is not None and res >= residual_thresh_m:
            reasons.append("protrudes")
        out.append({"x": x, "y": y, "confirmed": bool(reasons), "slope_deg": sl,
                    "roughness_m": ro, "residual_m": res, "reasons": reasons})
    return out


def confirm_detections(world_obstacles, layers: dict, *, observed_heights=None, **gates) -> list:
    """Keep only the obstacles the DEM layers CONFIRM (cross-analysis FP cut). world_obstacles is a list
    of (x, y[, r, ...]); returns the confirmed subset paired with its cross-analysis record."""
    xa = cross_analyze(world_obstacles, layers, observed_heights=observed_heights, **gates)
    return [(world_obstacles[i], xa[i]) for i in range(len(world_obstacles)) if xa[i]["confirmed"]]
