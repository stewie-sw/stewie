"""END-TO-END adapter: a rendered multi-station traverse -> the REAL per-station pixel estimators ->
run_integrated_slam fused SE(2) trajectory -> ATE vs the render's TRUE poses.

This is the glue the slam_seam header calls "the real bridge a rendered-sensor dataset plugs into":
``dem_fixed_traverse`` already does render-free DEM-overlay fixes; here the same fuse+score is driven
by the RENDERED-PIXEL cues that previously stopped at their own unit tests.

Legs and where each enters the SE(2) graph (dart.integrated_slam.run_integrated_slam):
  * VO        -- stereo_vo.estimate_vo -> slam_seam.vo_relative_factors: RELATIVE between-step motion,
                 integrated here into a world trajectory that becomes the odometry backbone (``dr_xy``)
                 the graph differences.
  * PARALLAX  -- stewie.godot.articulation_bridge.localize_on_render_pair: an ABSOLUTE (x,y) standstill
                 fix from a two-posture render-pair -> ``measured_fixes['parallax'] = {k: ((x,y), sigma)}``.
  * DEM       -- slam_seam.dem_position_fix: ABSOLUTE map-relative fix (already in dem_fixed_traverse).

HONESTY (invariant I3): real rendered pixels only; truth poses are read solely for scoring and for
landmark association, never to fabricate a fix. The SHADOW-height leg is NOT fused here -- shadow_height
could not be validated on these renders (dart/shadow_height.py header), so it stays a disclosed regime
cue, not a metric fix. No finished lunar-shadow SLAM is claimed (dart/slam_seam.py header).
"""
from __future__ import annotations

import math

import numpy as np


def _wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def vo_world_trajectory(stereo_pairs, config, *, start_xy=(0.0, 0.0), start_yaw=0.0):
    """Integrate REAL stereo-VO relative factors into a world (x, y, yaw) trajectory.

    ``estimate_vo`` -> ``vo_relative_factors`` (camera-frame dx=forward, dy=lateral, dyaw) -> rigid 2D
    integration from ``start_xy``/``start_yaw``. A step whose PnP failed (``valid=False``) carries the
    prior pose forward (no fabricated zero-motion). Returns ``{xy:(N,2), yaw:(N,), n_steps, n_valid,
    recovered_len_m}`` where N = len(stereo_pairs)."""
    from dart.slam_seam import vo_relative_factors
    from dart.stereo_vo import estimate_vo

    facs = vo_relative_factors(estimate_vo(list(stereo_pairs), config))
    x, y, yaw = float(start_xy[0]), float(start_xy[1]), float(start_yaw)
    xs, ys, yaws = [x], [y], [yaw]
    rec = 0.0
    n_valid = 0
    for f in facs:
        if f["valid"]:
            dx, dy = f["dxy"]
            wx = dx * math.cos(yaw) - dy * math.sin(yaw)         # rover-frame step rotated into the world
            wy = dx * math.sin(yaw) + dy * math.cos(yaw)
            x += wx
            y += wy
            yaw = _wrap(yaw + f["dyaw"])
            rec += math.hypot(wx, wy)
            n_valid += 1
        xs.append(x)
        ys.append(y)
        yaws.append(yaw)
    return {"xy": np.column_stack([xs, ys]), "yaw": np.asarray(yaws),
            "n_steps": len(facs), "n_valid": n_valid, "recovered_len_m": float(rec)}


def parallax_station_fixes(stations, *, camera="front_left"):
    """REAL absolute articulation-parallax fixes over a rendered traverse, packed for ``measured_fixes``.

    ``stations``: list of ``{k:int, render_dir, scene_dir, camera?}`` two-posture render-pairs. Runs
    ``articulation_bridge.localize_on_render_pair`` per station and returns ``{'fixes': {k: ((x,y),
    sigma)}, 'truth_xy': {k: (x,y)}}``. A station whose geometry is unsolvable (< 3 confident features
    -> ValueError) is SKIPPED, never fabricated. Lazy import: the bridge pulls PIL/Godot helpers."""
    from stewie.godot import articulation_bridge as AB

    fixes: dict[int, tuple] = {}
    truth: dict[int, tuple] = {}
    for st in stations:
        try:
            res = AB.localize_on_render_pair(st["render_dir"], st["scene_dir"],
                                             camera=st.get("camera", camera))
        except (ValueError, FileNotFoundError):
            continue                                             # unsolvable / missing -> no fabricated fix
        k = int(st["k"])
        fixes[k] = (tuple(float(v) for v in res["fix_xy"]), float(res["fix_sigma_m"]))
        truth[k] = tuple(float(v) for v in res["true_xy"])
    return {"fixes": fixes, "truth_xy": truth}


def fused_render_traverse(truth_xy, truth_yaw, *, measured_fixes=None, dr_xy=None,
                          gyro_bias_rad=0.01, fix_interval=2, factors=("odom", "imu", "parallax"),
                          n_keyframes=None):
    """Fuse the rendered-pixel cues over a traverse and score ATE vs TRUE pose -- the render analogue
    of ``slam_seam.dem_fixed_traverse``.

    ``measured_fixes`` is the ``run_integrated_slam`` dict ``{factor: {keyframe: (value, sigma)}}``
    produced by the real extractors (``parallax_station_fixes`` / ``dem_position_fix``). The odometry
    backbone is ``dr_xy`` when supplied (e.g. the VO trajectory from ``vo_world_trajectory``); otherwise
    it is dead-reckoned from the TRUE step lengths along a heading carrying a constant ``gyro_bias_rad``
    per step (the drifting odometry-only belief). Returns the cockpit-shaped est-vs-truth dict
    (``ate_fused_m``, ``ate_odom_m``, ``abs_max_*_m``, ``true_xy``/``fused_xy``/``odom_xy``)."""
    from dart.integrated_slam import run_integrated_slam

    T = np.asarray(truth_xy, float)
    n = len(T)
    Ty = np.asarray(truth_yaw, float)
    gyro_yaw = Ty + gyro_bias_rad * np.arange(n)                 # constant gyro bias -> heading drift
    if dr_xy is None:
        d = np.diff(T, axis=0)
        step = np.r_[0.0, np.linalg.norm(d, axis=1)]
        dr = np.zeros((n, 2))
        dr[0] = T[0]
        for k in range(1, n):                                   # dead-reckon TRUE steps along the GYRO heading
            dr[k] = dr[k - 1] + step[k] * np.array([math.cos(gyro_yaw[k]), math.sin(gyro_yaw[k])])
    else:
        dr = np.asarray(dr_xy, float)
    nkf = int(n_keyframes or n)
    common = dict(n_keyframes=nkf, fix_interval=fix_interval)
    fused = run_integrated_slam(T, dr, Ty, gyro_yaw, factors=factors,
                                measured_fixes=measured_fixes, **common)
    odom = run_integrated_slam(T, dr, Ty, gyro_yaw, factors=("odom", "imu"), **common)
    return {"ate_fused_m": fused["ate_aligned_m"], "ate_odom_m": odom["ate_aligned_m"],
            "abs_max_fused_m": fused["abs_max_err_m"], "abs_max_odom_m": odom["abs_max_err_m"],
            "n_measured": int(fused["measured"]), "n_keyframes": nkf,
            "true_xy": T.tolist(), "fused_xy": fused["est_xy"].tolist(),
            "odom_xy": odom["est_xy"].tolist()}
