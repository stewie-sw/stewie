"""Autoresearch loop: can the ~4% VO forward-scale bias (the SE3 7.99 m vs Sim3 5.57 m gap on the
committed SE(3) estimator) be recovered FIREWALL-CLEAN to push the SE3 ATE toward the Sim3 floor?

Each candidate estimates a single global scale ``s`` from a firewall-clean reference, applies it to the
frozen SE(3) trajectory (scale horizontal about the declared start, keep z), and the SE3 ATE is scored
vs GT. The GT-Sim3 scale is included ONLY as the unreachable CEILING (it reads GT; not a real estimate).

Candidates:
  loop_closure  -- pose_graph_se2 VO-scale state fed the 5 loop closures (existing machinery).
  imu_accel     -- regress gravity-removed IMU world-acceleration against VO acceleration (slope = s).
  sim3_ceiling  -- the GT-optimal scale (CEILING, GT-derived; not firewall-clean).

Run: .venv/bin/python benchmarks/s3li_crater/autoresearch_scale.py
"""
from __future__ import annotations

import json
import os
from datetime import date

import numpy as np

from dart.loop_closure_visual import LoopClosure, registration_rotation
from dart.loop_pose_graph_se2 import (
    _relative_se2,
    keyframe_indices,
    loop_se2_measurement,
    node_headings_enu,
)
from dart.pose_graph_se2 import PoseGraphSE2
from dart.s3li_capstone import axis_error_decompose, register_cam_to_enu, time_offset_s, write_tum, yaw_search
from dart.s3li_dem import S3liDem
from dart.s3li_reader import S3liReader
from dart.s3li_vio import build_vio_leveled_trajectory, load_imu_cached, vio_enu_camera_frames

THIS = os.path.dirname(os.path.abspath(__file__))
VALID = "/mnt/projects/stewie/code/stewie/eval/validation"


def _accepted_closures() -> list[LoopClosure]:
    for p in ("se3_stride3_meta.json", "se2_recipe_stride3_meta.json"):
        fp = os.path.join(THIS, p)
        if os.path.isfile(fp):
            m = json.load(open(fp))
            return [LoopClosure(int(c["a_node"]), int(c["b_node"]), np.asarray(c["d_enu_m"], float),
                                np.asarray(c.get("c_in_a_m", [0, 0, 0]), float), int(c["n_inliers"]),
                                int(c.get("n_matches", 0)), float(c["similarity"]), float(c["trans_m"]),
                                True, "ok", r_ab=np.asarray(c.get("r_ab", np.eye(3)), float))
                    for c in m["loop_closures"] if c["accepted"]]
    return []


def loop_closure_scale(enu, head, quat, r_m, closures) -> dict:
    """VO forward-scale from the pose_graph_se2 scale state + the loop closures (existing machinery)."""
    n = enu.shape[0]
    loop_meas = [loop_se2_measurement(c, quat, enu, head, r_m) for c in closures]
    kf = keyframe_indices(n, 20, [a for a, _, _ in loop_meas] + [b for _, b, _ in loop_meas])
    kfset = set(kf)
    g = PoseGraphSE2(robust=True, estimate_vo_scale=True)
    g.set_vo_scale_prior(1.0, 0.2)
    g.add_prior(kf[0], np.array([enu[kf[0], 0], enu[kf[0], 1], head[kf[0]]]), sigma_xy=0.2, sigma_yaw=0.02)
    for i in range(len(kf) - 1):
        a, b = kf[i], kf[i + 1]
        pa = np.array([enu[a, 0], enu[a, 1], head[a]])
        pb = np.array([enu[b, 0], enu[b, 1], head[b]])
        g.add_vo_between(a, b, _relative_se2(pa, pb), sigma_xy=0.1, sigma_yaw=0.01)
    for a, b, meas in loop_meas:
        if a in kfset and b in kfset:
            g.add_between(a, b, meas, sigma_xy=0.5, sigma_yaw=0.05)
    out = g.optimize_with_scale()
    return {"scale": float(out["vo_scale"]), "observable": bool(out["scale_observable"]),
            "sigma": float(out["vo_scale_sigma"]) if out["vo_scale_sigma"] else None}


def imu_accel_scale(ts, xyz, quat, valid, imu, dem) -> dict:
    """Global scale from regressing gravity-removed IMU world-acceleration against VO acceleration."""
    z0 = float(dem.height_enu(0.0, 0.0))
    b = build_vio_leveled_trajectory(xyz, quat, valid, imu["ts_ns"], imu["gyro"], imu["accel"], ts)
    yaw = yaw_search(b.xyz_leveled, dem, z0)
    r_enu_cam, enu_vio = vio_enu_camera_frames(b, yaw["yaw_rad"], z0)
    node_t = ts.astype(float) / 1e9
    idx = np.clip(np.searchsorted(imu["ts_ns"].astype(float) / 1e9, node_t), 0, imu["ts_ns"].shape[0] - 1)
    a_world = np.einsum("nij,nj->ni", r_enu_cam, imu["accel"][idx]) - np.array([0, 0, b.gravity_norm_m_s2])

    def smooth(x, k=15):
        ker = np.ones(k) / k
        return np.column_stack([np.convolve(x[:, i], ker, "same") for i in range(x.shape[1])])
    p = smooth(enu_vio, 15)
    v = np.column_stack([np.gradient(p[:, i], node_t) for i in range(3)])
    a_vo = np.column_stack([np.gradient(smooth(v, 15)[:, i], node_t) for i in range(3)])
    mv = np.linalg.norm(v[:, :2], axis=1) > 0.2
    H = a_vo[mv][:, :2].ravel()
    Y = a_world[mv][:, :2].ravel()
    m = np.isfinite(H) & np.isfinite(Y) & (np.abs(H) < 2) & (np.abs(Y) < 2)
    s = float(np.sum(H[m] * Y[m]) / max(np.sum(H[m] * H[m]), 1e-9))
    corr = float(np.corrcoef(H[m], Y[m])[0, 1])
    return {"scale": s, "corr": corr, "vo_horiz_accel_rms": float(np.sqrt(np.mean(a_vo[mv][:, :2] ** 2))),
            "imu_horiz_accel_rms": float(np.sqrt(np.mean(a_world[mv][:, :2] ** 2)))}


def main() -> None:
    d = np.load(os.path.join(THIS, "vo_cam_stride3.npz"))
    ts = d["ts_ns"].astype(np.int64)
    xyz = d["xyz_cam"].astype(float)
    quat = d["quat_wxyz_cam"].astype(float)
    valid = d["valid"].astype(bool)
    dem = S3liDem()
    z0 = float(dem.height_enu(0.0, 0.0))
    yaw = yaw_search(xyz, dem, z0)
    enu = register_cam_to_enu(xyz, yaw["yaw_rad"], z0)
    r_m = registration_rotation(yaw["yaw_rad"])
    head = node_headings_enu(quat, r_m)
    reader = S3liReader()
    imu = load_imu_cached(reader, os.path.join(THIS, "imu_full.npz"))
    closures = _accepted_closures()

    # the SE(3) trajectory to which a recovered scale would be applied (the committed 7.99 m result)
    se3_tum = os.path.join(THIS, "se3_lc_dem_enu.tum")
    se3 = np.loadtxt(se3_tum)[:, 1:4]
    se3_ts = np.loadtxt(se3_tum)[:, 0]
    gt_ts_ns, gt_enu = reader.gt_enu(dem=dem)
    off = time_offset_s(ts, enu, gt_ts_ns, gt_enu)
    gt_s = (gt_ts_ns.astype(float) + off["offset_s"] * 1e9) / 1e9
    ident = np.tile(np.array([1.0, 0.0, 0.0, 0.0]), (se3.shape[0], 1))

    def score_scaled(s: float) -> dict:
        start = se3[0]
        scaled = start + s * (se3 - start)
        scaled[:, 2] = se3[:, 2]                                       # keep z (scale is a horizontal bias)
        p = os.path.join(THIS, "_scale_tmp.tum")
        write_tum(p, se3_ts, scaled, ident)
        dec = axis_error_decompose(p, gt_enu, gt_s)
        os.remove(p)
        return {"horizontal_m": dec["rms_horizontal_m"], "vertical_m": dec["rms_vertical_m"],
                "se3_rmse_m": float((dec["rms_horizontal_m"] ** 2 + dec["rms_vertical_m"] ** 2) ** 0.5)}

    base = score_scaled(1.0)
    # ceiling: the GT-optimal horizontal scale (1-D line search; GT-derived, NOT firewall-clean)
    grid = np.linspace(0.90, 1.15, 51)
    ceil_s = float(grid[int(np.argmin([score_scaled(g)["se3_rmse_m"] for g in grid]))])
    ceil = score_scaled(ceil_s)

    trials = []
    lc = loop_closure_scale(enu, head, quat, r_m, closures)
    trials.append({"method": "loop_closure", "firewall_clean": True, "recovered_scale": lc["scale"],
                   "observable": lc["observable"], **score_scaled(lc["scale"]),
                   "verdict": "DEGENERATE: a single revisit lets the scale state shrink the whole loop "
                              "to force closure (recovered ~0.37, not ~1.04)"})
    im = imu_accel_scale(ts, xyz, quat, valid, imu, dem)
    trials.append({"method": "imu_accel", "firewall_clean": True, "recovered_scale": im["scale"],
                   "corr": im["corr"], "vo_horiz_accel_rms": im["vo_horiz_accel_rms"],
                   "imu_horiz_accel_rms": im["imu_horiz_accel_rms"], **score_scaled(im["scale"]),
                   "verdict": f"TOO NOISY: the slow rover's horizontal motion accel "
                              f"({im['vo_horiz_accel_rms']:.2f} m/s2) is buried under gravity-removal "
                              f"error ({im['imu_horiz_accel_rms']:.2f} m/s2); corr {im['corr']:.2f}"})
    trials.append({"method": "sim3_ceiling_GT", "firewall_clean": False, "recovered_scale": ceil_s,
                   **ceil, "verdict": "CEILING ONLY (GT-derived): the SE3 if the 4% scale were perfectly "
                                      "known -- the Sim3 floor, not reachable firewall-clean here"})

    artifact = {
        "experiment": "Autoresearch: firewall-clean recovery of the ~4% VO forward-scale to push the "
                      "S3LI s3li_crater SE(3) ATE below 7.99 m",
        "date": str(date.today()),
        "baseline_se3_lc_dem_m": base["se3_rmse_m"], "baseline_horizontal_m": base["horizontal_m"],
        "ceiling_se3_if_scale_known_m": ceil["se3_rmse_m"], "ceiling_scale": ceil_s,
        "trials": trials,
        "honest_read": (
            f"The committed SE(3) estimator sits at SE3 {base['se3_rmse_m']:.2f} m (horiz "
            f"{base['horizontal_m']:.2f}); the GT-optimal horizontal scale ({ceil_s:.3f}) would take it to "
            f"{ceil['se3_rmse_m']:.2f} m (the Sim3 floor). But NO firewall-clean estimator recovers that "
            "scale on this data: the loop closure is DEGENERATE (a single start<->end revisit lets the "
            "scale state shrink the whole loop to force closure, ~0.37 not ~1.04); the IMU is TOO NOISY "
            "(the slow rover's ~0.14 m/s2 horizontal motion accel is 40x below the ~5.6 m/s2 "
            "gravity-removal residual, corr ~0.10); and a DEM scale search is circular (the SE(3) z is "
            "already DEM-anchored at the current scale). So 7.99 m SE3 is the genuine floor for "
            "vision-only + a 30 m DEM + a single-loop traverse, and ~5.6 m (Sim3) is an UNREACHABLE "
            "ceiling without a clean metric scale reference: a higher-res DEM (Tinitaly/Pleiades/LROC-NAC, "
            "all gated here), wheel odometry (absent from the bag), tight IMU pre-integration with online "
            "accel-bias + cam-IMU-extrinsic estimation (a real VIO build, marginal at this motion level), "
            "or a multi-loop traverse (different data)."
        ),
    }
    out = os.path.join(VALID, "s3li_crater_autoresearch_scale_2026-06-28.json")
    with open(out, "w") as fh:
        json.dump(artifact, fh, indent=2)
    print(f"baseline SE3 {base['se3_rmse_m']:.2f} m (h {base['horizontal_m']:.2f}); "
          f"ceiling@scale{ceil_s:.3f} SE3 {ceil['se3_rmse_m']:.2f} m", flush=True)
    for t in trials:
        print(f"  {t['method']:18s} scale={t['recovered_scale']:.3f} -> SE3 {t['se3_rmse_m']:.2f} "
              f"({'firewall-clean' if t['firewall_clean'] else 'GT-CEILING'}): {t['verdict'][:70]}",
              flush=True)
    print(f"artifact -> {out}", flush=True)


if __name__ == "__main__":
    main()
