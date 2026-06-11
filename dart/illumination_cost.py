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

#: term weights [CALIB] -- relative emphasis; each term is also returned raw for inspection.
W_SHADOW = 1.0          # unlit cell -> no AprilTag-lock -> navigation risk
W_SATURATION = 0.5      # near-grazing sun -> washout -> unreliable perception
W_MAP_UNCERTAINTY = 0.3 # placeholder map-uncertainty term (uniform until a coverage field is fed)
GRAZING_EL_DEG = 5.0    # below this sun elevation, lit cells risk low-sun washout


def illumination_cost(heightmap, *, cell_m: float, sun_az_deg: float, sun_el_deg: float,
                      map_uncertainty=None) -> dict:
    """Per-cell illumination cost as separable terms + a weighted total. Each term is a (H, W) array."""
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
    total = W_SHADOW * shadow_hazard + W_SATURATION * saturation + W_MAP_UNCERTAINTY * mu
    return {"shadow_hazard": shadow_hazard, "saturation": saturation,
            "map_uncertainty": mu, "total": total,
            "weights": {"shadow": W_SHADOW, "saturation": W_SATURATION, "map_uncertainty": W_MAP_UNCERTAINTY}}
