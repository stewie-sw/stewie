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


def dem_fixed_traverse(dem, path_rc, *, ref_rc=(0, 0), patch_half=6, gyro_bias_rad=0.01,
                       fix_interval=2, base_sigma_m=2.0):
    """Fuse REAL register_to_dem absolute fixes over a real-terrain traverse, scored vs TRUE pose.

    The lunar est-vs-truth the modeled-Katwijk path could only approximate: scored against the render/
    DEM's OWN truth, with the DEM fix produced by the real estimator on real terrain (no modeled
    truth+sigma). The rover follows ``path_rc`` (a list of (row,col) cells) across the real DEM; dead
    reckoning integrates each TRUE step length along a GYRO heading carrying a constant
    ``gyro_bias_rad`` per step, so the odometry-only belief DRIFTS. At each DEM keyframe the rover
    senses the REAL terrain patch at its TRUE cell and ``dem_position_fix`` (register_to_dem) corrects
    the drifted guess -> a MEASURED absolute (x,y) fix. run_integrated_slam fuses odom+imu+the real DEM
    fixes; ATE is scored against the true world path. Non-circular: the fix matches terrain
    INDEPENDENTLY of the drift, so it genuinely pulls the drifted estimate back. Returns
    {ate_fused_m, ate_odom_m, abs_max_*_m, n_dem_fix, n_keyframes, measured}. No render needed (the DEM
    overlay senses the map directly); the shadow-yaw/parallax cues stay render-gated (header)."""
    from dart import localization as LOC
    from dart.integrated_slam import run_integrated_slam
    Z, cell = dem
    path = np.asarray(path_rc, float)
    n = len(path)
    true_xy = np.column_stack([(path[:, 1] - ref_rc[1]) * cell, (path[:, 0] - ref_rc[0]) * cell])
    d = np.diff(true_xy, axis=0)
    truth_yaw = np.zeros(n)
    if n > 1:
        truth_yaw[1:] = np.arctan2(d[:, 1], d[:, 0])
        truth_yaw[0] = truth_yaw[1]
    gyro_yaw = truth_yaw + gyro_bias_rad * np.arange(n)         # a constant gyro bias -> drift
    step_len = np.r_[0.0, np.linalg.norm(d, axis=1)]
    dr_xy = np.zeros((n, 2))
    dr_xy[0] = true_xy[0]
    for k in range(1, n):                                      # dead-reckon TRUE steps along GYRO heading
        dr_xy[k] = dr_xy[k - 1] + step_len[k] * np.array([math.cos(gyro_yaw[k]), math.sin(gyro_yaw[k])])
    measured = {}
    for k in range(2 * fix_interval, n, 2 * fix_interval):     # the integrated_slam DEM-fix schedule
        true_rc = (int(round(path[k, 0])), int(round(path[k, 1])))
        guess_rc = (int(round(dr_xy[k, 1] / cell + ref_rc[0])),  # the DRIFTED odometry belief
                    int(round(dr_xy[k, 0] / cell + ref_rc[1])))
        observed = LOC.patch_at(Z, true_rc, patch_half)        # rover senses the REAL terrain it is on
        fix = dem_position_fix(observed, dem, guess_rc, ref_rc=ref_rc, base_sigma_m=base_sigma_m)
        if fix is not None:                                    # ambiguous/flat -> no fabricated fix
            measured[k] = (fix["xy"], fix["sigma"])
    common = dict(n_keyframes=n, fix_interval=fix_interval)
    fused = run_integrated_slam(true_xy, dr_xy, truth_yaw, gyro_yaw,
                                factors=("odom", "imu", "dem"), measured_fixes={"dem": measured}, **common)
    odom = run_integrated_slam(true_xy, dr_xy, truth_yaw, gyro_yaw, factors=("odom", "imu"), **common)
    return {"ate_fused_m": fused["ate_aligned_m"], "ate_odom_m": odom["ate_aligned_m"],
            "abs_max_fused_m": fused["abs_max_err_m"], "abs_max_odom_m": odom["abs_max_err_m"],
            "n_dem_fix": len(measured), "n_keyframes": int(n), "measured": fused["measured"],
            # trajectories for the cockpit est-vs-truth plot (world x,y; truth = the DEM's own path)
            "true_xy": true_xy.tolist(), "fused_xy": fused["est_xy"].tolist(),
            "odom_xy": odom["est_xy"].tolist(),
            "fix_keyframes": sorted(int(k) for k in measured)}


def haworth_demo_traverse(dem, *, n: int = 16, patch_half: int = 6, gyro_bias_rad: float = 0.01,
                          fix_interval: int = 2):
    """A reproducible real-Haworth est-vs-truth demo for the cockpit: pick a textured, in-bounds start
    (max DEM gradient), drive a diagonal traverse, and score the REAL register_to_dem fusion vs
    odometry-only via dem_fixed_traverse. Deterministic (argmax gradient). Returns the dem_fixed_traverse
    result plus the start cell. Scored against the DEM's own truth -- no modeled cue, no synthetic data."""
    Z, _cell = dem
    H, W = Z.shape
    m = 20
    sub = np.abs(np.gradient(Z)[0])[m:H - m - 2 * n, m:W - m - n]   # bound the window so the path fits
    rr, cc = np.unravel_index(int(np.argmax(sub)), sub.shape)
    r0, c0 = int(rr + m), int(cc + m)
    path = [(r0 + 2 * k, c0 + k) for k in range(n)]
    out = dem_fixed_traverse(dem, path, patch_half=patch_half, gyro_bias_rad=gyro_bias_rad,
                             fix_interval=fix_interval)
    out["start_rc"] = [r0, c0]
    return out


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
