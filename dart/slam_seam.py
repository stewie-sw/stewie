"""SLAM-seam: bridge the rendered-sensor estimators to the run_integrated_slam SE(2) pose graph.

Three real estimators become the MEASURED fixes the integrated estimator fuses, in place of the
modeled (truth + calibrated-sigma) fix at a keyframe:

  * register_to_dem (dart.localization)               -> an ABSOLUTE map-relative position fix
  * articulation_localize (dart.articulated_parallax)  -> an ABSOLUTE standstill-parallax position fix
  * estimate_vo (dart.stereo_vo)                       -> RELATIVE ground-plane between-factors (VO)

The producers are exercised on REAL data: the real Haworth DEM (dem_position_fix), real parallax
geometry (parallax_position_fix), and the real a6 rendered stereo traverse (vo_relative_factors).
run_integrated_slam(measured_fixes=...) consumes the absolute fixes; with measured_fixes=None the
modeled path is byte-identical (the honest default).

HONESTY / GATED: the end-to-end run that drives ALL three estimators off a real rendered lunar-shadow
sequence WITH co-registered pose truth is GATED on such a dataset (Katwijk carries no lunar shadow
channel). Until then the cue factors stay modeled at their calibrated sigma; these producers are the
real bridge that a rendered-sensor dataset plugs into. No finished lunar-shadow SLAM is claimed.
"""
from __future__ import annotations

import math

import numpy as np

from dart.articulated_parallax import articulation_localize
from dart.localization import register_to_dem


def dem_position_fix(observed_patch, dem, guess_rc, *, ref_rc=(0, 0),
                     base_sigma_m: float = 2.0, min_confidence: float = 0.05):
    """ABSOLUTE world (x,y) position fix from a DEM overlay (register_to_dem).

    Registers the observed elevation patch onto the prior DEM near a drifted ``guess_rc`` and converts
    the corrected cell to a metric world position relative to ``ref_rc`` (col -> x east, row -> y
    north, scaled by the DEM cell size). The fix sigma is ``base_sigma_m`` inflated as the match
    confidence drops. Returns ``None`` when the match is too ambiguous (confidence < min_confidence)
    to trust -- a flat/aliased region must NOT manufacture a fix; odometry carries instead.
    """
    _Z, cell = dem
    out = register_to_dem(observed_patch, dem, guess_rc)
    if out["confidence"] < min_confidence:
        return None
    r, c = out["corrected_rc"]
    x = (c - ref_rc[1]) * float(cell)
    y = (r - ref_rc[0]) * float(cell)
    sigma = base_sigma_m / max(min_confidence, out["confidence"])   # confident peak -> tight fix
    return {"xy": (float(x), float(y)), "sigma": float(sigma), "confidence": float(out["confidence"]),
            "residual_rmse_m": float(out["residual_rmse_m"]), "shift_cells": out["shift_cells"]}


def parallax_position_fix(guess_xy, landmarks_xy, pixel_shifts, *, dh_m: float, fx_px: float,
                          sigma_px: float = 0.3):
    """ABSOLUTE (x,y) fix from a standstill articulation-parallax maneuver (articulation_localize).

    Triangulates landmark ranges from the shadow-tip PIXEL shifts observed under the commanded lift
    ``dh_m`` and fixes the rover position, with the geometry-derived covariance. A weak prior at
    ``guess_xy`` seeds the solve. Returns {'xy','sigma','ambiguous','fused'}; an ambiguous fix
    (< 3 non-collinear landmarks -> a mirror pair) is reported with ``fused=False`` and must not be
    fused until a third non-collinear observation disambiguates (H-14/M-02 in articulation_localize).
    """
    from dart.pose_graph_se2 import PoseGraphSE2
    g = PoseGraphSE2()
    g.add_prior(0, (float(guess_xy[0]), float(guess_xy[1]), 0.0), sigma_xy=50.0, sigma_yaw=50.0)
    out = articulation_localize(g, 0, list(landmarks_xy), list(pixel_shifts),
                                dh_m=dh_m, fx_px=fx_px, sigma_px=sigma_px)
    return {"xy": tuple(float(v) for v in out["fix_xy"]), "sigma": float(out["fix_sigma_m"]),
            "ambiguous": bool(out["ambiguous"]), "fused": bool(out["fused"])}


def vo_relative_factors(vo_result):
    """Convert a stereo-VO result (estimate_vo) into ground-plane SE(2) relative between-factors.

    Camera frame convention (OpenCV/REP): x right, y down, z forward. The top-down motion of a step is
    (dx = forward = +t_z, dy = lateral = -t_x) and the heading change is the yaw about the camera's
    vertical (down) axis, atan2(R[0,2], R[2,2]). A step that FAILED PnP (M-03: invalid/missing motion,
    NaN translation + inflated covariance) is carried as ``valid=False`` with ``dxy=None`` so a caller
    never fuses a fabricated zero-motion factor. Returns a list of {'dxy','dyaw','valid'} of length F-1.
    """
    out = []
    T = np.asarray(vo_result.relative_translations_m, float)
    for k in range(len(vo_result.step_valid)):
        if not bool(vo_result.step_valid[k]):
            out.append({"dxy": None, "dyaw": None, "valid": False})
            continue
        t = T[k]
        R = np.asarray(vo_result.relative_rotations[k], float)
        dx, dy = float(t[2]), float(-t[0])
        dyaw = float(math.atan2(R[0, 2], R[2, 2]))
        out.append({"dxy": (dx, dy), "dyaw": dyaw, "valid": True})
    return out
