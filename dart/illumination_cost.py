"""SN-05: illumination-aware route cost (separable, inspectable terms).

Turns the local lighting into a per-cell traverse cost the planner can add to its existing
rock/slope terms -- so routes prefer lit, well-observed corridors near the poles. Returns each term
SEPARATELY (PROPOSAL §6.2: visibility, saturation, shadow hazard, map uncertainty remain separate
inspectable terms, never a fused black box), so an operator can see WHY a cell is expensive. Real
illumination from horizon_clip; no fabricated cost.
"""
from __future__ import annotations

import numpy as np

from dart.shadow_predict import cast_shadow_mask
from dart.visibility import is_visible

#: term weights [CALIB] -- relative emphasis; each term is also returned raw for inspection.
W_SHADOW = 1.0          # unlit cell -> no AprilTag-lock -> navigation risk
W_SATURATION = 0.5      # near-grazing sun -> washout -> unreliable perception
W_MAP_UNCERTAINTY = 0.3 # placeholder map-uncertainty term (uniform until a coverage field is fed)
W_VISIBILITY = 0.8      # no line-of-sight to any localization anchor -> no fiducial pose-lock -> nav risk
GRAZING_EL_DEG = 5.0    # below this sun elevation, lit cells risk low-sun washout


def illumination_cost(heightmap, *, cell_m: float, sun_az_deg: float, sun_el_deg: float,
                      map_uncertainty=None, anchors=None, dem_origin=(0.0, 0.0)) -> dict:
    """Per-cell illumination cost as separable terms + a weighted total. Each term is a (H, W) array.

    ``anchors`` (optional [(x, y), ...] world positions of localization anchors -- the lander / fiducials)
    enables the VISIBILITY term: a cell with NO line-of-sight to any anchor cannot get an AprilTag pose-lock,
    a nav risk DISTINCT from shadow_hazard (the cell can be lit yet blind). Opt-in so the default path is
    byte-identical + fast; reuses the audited `dart.visibility.is_visible` LOS march. (For a large frame a
    ray-to-perimeter viewshed would replace the per-cell march; the exact per-cell LOS is kept here.)"""
    z = np.asarray(heightmap, float)
    shadowed = cast_shadow_mask((z, float(cell_m)), sun_az_deg=float(sun_az_deg), sun_el_deg=float(sun_el_deg))
    lit = ~shadowed                                              # consistent with the SN-02/calibration channel
    shadow_hazard = np.where(shadowed, 1.0, 0.0)                 # unlit cells carry the nav risk
    # saturation: lit cells under a grazing sun risk washout (worse the lower the sun)
    graze = max(0.0, (GRAZING_EL_DEG - float(sun_el_deg)) / GRAZING_EL_DEG)
    saturation = np.where(lit, graze, 0.0)
    if map_uncertainty is not None:
        mu = np.asarray(map_uncertainty, float)
    else:
        mu = np.full(z.shape, 0.0)                                # no coverage field -> 0 (honest)
    visibility = np.zeros(z.shape)
    if anchors:                                                   # opt-in: LOS to a localization anchor
        dem = (z, float(cell_m))
        ox0, oy0 = float(dem_origin[0]), float(dem_origin[1])
        for ri in range(z.shape[0]):
            for ci in range(z.shape[1]):
                wx, wy = ox0 + ci * float(cell_m), oy0 + ri * float(cell_m)
                if not any(is_visible(dem, dem_origin, (wx, wy), (float(ax), float(ay))) for ax, ay in anchors):
                    visibility[ri, ci] = 1.0                      # blind to every anchor -> localization risk
    total = (W_SHADOW * shadow_hazard + W_SATURATION * saturation
             + W_MAP_UNCERTAINTY * mu + W_VISIBILITY * visibility)
    return {"shadow_hazard": shadow_hazard, "saturation": saturation,
            "map_uncertainty": mu, "visibility": visibility, "total": total,
            "weights": {"shadow": W_SHADOW, "saturation": W_SATURATION,
                        "map_uncertainty": W_MAP_UNCERTAINTY, "visibility": W_VISIBILITY}}
