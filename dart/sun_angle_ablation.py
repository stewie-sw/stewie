"""[REQ:AS-08] Sun-angle ShadowNav ablation (§25 Phase 6).

Parameterizes the add-one shadow-factor ablation by SUN ELEVATION, demonstrating the AS-08
acceptance: the gated shadow heading/position factor is ACCEPTED + helps (bounds absolute drift)
under SUPPORTED geometry (grazing sun -> long, sharp shadows) and is REJECTED under unsupported /
ambiguous geometry (high sun -> shadows too short to localize -> false/weak landmarks).

The accept/reject boundary is exact geometry, not a fabricated curve: a height-h obstacle casts a
shadow of length L = h / tan(elevation). Below the 45 deg crossover the shadow is longer than the
obstacle is tall (L >= h -> a usable landmark); above it the shadow collapses (L < h -> rejected).
The drift-reduction itself is the existing real ablation (dart.ablation.factor_ablation: real
Katwijk dead-reckoning + a modelled absolute fix at the calibrated sigma -- the standard add-one
method, NOT a real-rover shadow-nav claim, exactly as dart.ablation frames it).
"""
from __future__ import annotations

import math

from dart.ablation import factor_ablation
from stewie.specs import ipex_specs

# 45 deg crossover: at this elevation the cast shadow length equals the obstacle height. Below it
# (grazing) shadows are long + usable; above it they are too short to anchor a heading factor.
SUPPORTED_MAX_ELEV_DEG = 45.0


def shadow_length_m(sun_elev_deg: float, obstacle_h_m: float = ipex_specs.OBSTACLE_HEIGHT_M) -> float:
    """Cast-shadow length of a height-h obstacle at a given sun elevation: L = h / tan(elev) [m]."""
    e = math.radians(max(1e-6, min(89.999, float(sun_elev_deg))))
    return obstacle_h_m / math.tan(e)


def geometry_supported(sun_elev_deg: float, obstacle_h_m: float = ipex_specs.OBSTACLE_HEIGHT_M) -> bool:
    """Shadow long enough to anchor a factor: L >= obstacle height (elev <= 45 deg)."""
    return shadow_length_m(sun_elev_deg, obstacle_h_m) >= obstacle_h_m


def sun_angle_ablation(truth_xy, dr_xy, sun_elevations_deg, *,
                       obstacle_h_m: float = ipex_specs.OBSTACLE_HEIGHT_M,
                       shadow_fix_sigma_m: float = 2.0, **ablation_kwargs) -> dict:
    """Sun-angle-parameterized add-one ablation. Returns the DR baseline absolute drift and one row
    per sun elevation: shadow length, whether the geometry supports a factor (accepted), the
    resulting absolute drift (bounded when accepted, unchanged DR baseline when rejected), and
    whether the factor helped. The drift-reduction is dart.ablation.factor_ablation (real DR)."""
    abl = factor_ablation(truth_xy, dr_xy, fix_sigma_m=shadow_fix_sigma_m, **ablation_kwargs)
    baseline_abs = abl["baseline (odometry only)"]["abs_max_err_m"]
    with_shadow_abs = abl["+absolute fixes (DEM/shadow)"]["abs_max_err_m"]

    rows = []
    for e in sun_elevations_deg:
        L = shadow_length_m(e, obstacle_h_m)
        accepted = geometry_supported(e, obstacle_h_m)
        rows.append({
            "sun_elev_deg": float(e),
            "shadow_len_m": round(L, 4),
            "accepted": accepted,                       # gated: rejected under high-sun (false-shadow) geometry
            # accepted -> the shadow factor enters the graph + bounds drift; rejected -> no factor,
            # the estimate stays at the dead-reckoning baseline (correctly NOT helped by a bad shadow)
            "abs_max_err_m": round(with_shadow_abs if accepted else baseline_abs, 4),
            "helped": bool(accepted and with_shadow_abs < baseline_abs),
        })
    return {"baseline_abs_max_err_m": round(baseline_abs, 4),
            "with_shadow_abs_max_err_m": round(with_shadow_abs, 4),
            "supported_max_elev_deg": SUPPORTED_MAX_ELEV_DEG, "rows": rows}
