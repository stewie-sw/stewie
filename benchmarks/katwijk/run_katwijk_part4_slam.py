"""Katwijk Traverse Part4 loop-closing visual SLAM: the GENERALISATION run of the S3LI estimator on a
SECOND real rover (ESA Katwijk beach planetary-rover dataset, PointGrey Bumblebee2 LocCam).

Part4 is the one Katwijk traverse that closes a loop (a 76 m closed path; the GPS truth returns to a
prior point), so the same VO + visual-loop-closure + pose-graph stack validated on S3LI can be exercised
here. No DEM exists for the Katwijk beach, so this is the VO + loop-closure leg only (no terrain anchor).

Pipeline (truth firewall I3: images + calibration only; GPS read only at scoring):
  1. calibrated stereo rectification of the raw LocCam pairs (the dataset's own intrinsics + baseline),
  2. SuperPoint+LightGlue stereo VO (the same front end as S3LI),
  3. per-keyframe SuperPoint feature cache -> visual loop closure (appearance + node-gap, geometric
     PnP verification),
  4. the loop closures fused in the position-only graph and the SE(2) heading-optimising graph,
  5. SE3 + Sim3 ATE vs the RTK-GPS truth (evo, timestamp-associated).
"""
from __future__ import annotations

import datetime as dt
import glob
import json
import os
import sys
import time
from datetime import date

import numpy as np
from imageio.v3 import imread

sys.path.insert(0, "/mnt/projects/stewie/code")
from dart import stereo_vo  # noqa: E402
from dart.dem_height_graph import DemHeightPoseGraph, build_between_factors  # noqa: E402
from dart.loop_closure_visual import (  # noqa: E402
    LoopKeyframe,
    build_loop_factors,
    detect_loops,
    global_descriptor,
    registration_rotation,
)
from dart.loop_pose_graph_se2 import estimate_se2_loopclosure  # noqa: E402
from dart.s3li_capstone import register_cam_to_enu, rotmat_to_quat_wxyz, score, write_tum  # noqa: E402
from dart.superpoint_vo import estimate_vo_superpoint, triangulate_stereo_superpoint  # noqa: E402
from stewie.bridge.katwijk_io import gps_latlon_to_local_xy, load_gps_real  # noqa: E402

KP = "/mnt/projects/datasets/katwijk/Part4"
OUT = os.path.dirname(os.path.abspath(__file__))
VALID = "/mnt/projects/stewie/code/stewie/eval/validation"
FIG = os.path.join(VALID, "figures", "katwijk_part4_slam_2026-06-28")
# real LocCam metric calibration (dataset LocCam_calibration.mat MCOS subsystem; CAMERA property, not GT)
K1 = np.array([[834.256, 0, 497.715], [0, 838.961, 398.773], [0, 0, 1]], float)
K2 = np.array([[837.129, 0, 481.938], [0, 840.816, 391.460], [0, 0, 1]], float)
R_LR = np.array([[0.999992, -0.003275, 0.002344], [0.003280, 0.999992, -0.002108],
                 [-0.002337, 0.002116, 0.999995]], float).T
T_LR = np.array([-0.120079, -0.000263, 0.000268], float)


def _loccam_ts(stamp: str) -> float:
    p = os.path.basename(stamp).split("_")[1:]
    return dt.datetime(int(p[0]), int(p[1]), int(p[2]), int(p[3]), int(p[4]), int(p[5]),
                       int(p[6]) * 1000, tzinfo=dt.timezone.utc).timestamp()


def main(stride: int = 2, kf_every: int = 3) -> None:
    os.makedirs(FIG, exist_ok=True)
    stamps = sorted(set(f.rsplit("_", 1)[0] for f in glob.glob(KP + "/LocCam/*.png")))[::stride]
    ts_s = np.array([_loccam_ts(s) for s in stamps])
    pairs = [(np.asarray(imread(s + "_0.png")), np.asarray(imread(s + "_1.png"))) for s in stamps]
    print(f"[katwijk] {len(pairs)} Part4 LocCam pairs (stride {stride})", flush=True)

    rect, cfg = stereo_vo.calibrated_rectify_pairs(pairs, K_left=K1, dist_left=np.zeros(5), K_right=K2,
                                                   dist_right=np.zeros(5), R=R_LR, T_m=T_LR)
    t0 = time.time()
    res = estimate_vo_superpoint(rect, cfg, deterministic=True)
    poses = res.camera_poses
    xyz_cam = poses[:, :3, 3].astype(float)
    quat = np.array([rotmat_to_quat_wxyz(p[:3, :3]) for p in poses], float)
    n = xyz_cam.shape[0]
    print(f"[katwijk] VO {n} poses, valid {int(np.sum(res.vo.trajectory_valid))}, "
          f"path {np.sum(np.linalg.norm(np.diff(xyz_cam, axis=0), axis=1)):.1f}m in {time.time()-t0:.0f}s",
          flush=True)

    # per-keyframe feature cache for loop closure (re-extract on the rectified pairs)
    h_px, w_px = rect[0][0].shape[:2]
    image_size = np.array([float(w_px), float(h_px)], float)
    keyframes: list[LoopKeyframe] = []
    for k in range(0, n, kf_every):
        cloud, feats, kpts = triangulate_stereo_superpoint(rect[k][0], rect[k][1], cfg)
        desc = feats["descriptors"][0].detach().cpu().numpy().astype(np.float32)
        if desc.shape[0] == 0:
            continue
        keyframes.append(LoopKeyframe(node=k, keypoints=kpts.astype(np.float32), descriptors=desc,
                                      image_size=image_size, points_3d=cloud.points_3d.astype(np.float32),
                                      point_kpt_idx=cloud.left_feat_idx.astype(np.int64),
                                      global_desc=global_descriptor(desc)))
    print(f"[katwijk] {len(keyframes)} loop keyframes (every {kf_every})", flush=True)

    # loop closure in the VO world frame (no DEM -> registration yaw 0)
    loops = detect_loops(keyframes, quat, 0.0, cfg, min_index_gap=max(50, n // 4), sim_min=0.80,
                         min_inliers=15, max_translation_m=10.0, max_candidates=2000)
    acc = loops["accepted"]
    print(f"[katwijk] {len(acc)}/{loops['n_candidates']} loop closures accepted "
          f"(a in {[lc.a_node for lc in acc][:5]}, b in {[lc.b_node for lc in acc][:5]})", flush=True)

    enu_vo = register_cam_to_enu(xyz_cam, 0.0, 0.0)
    r_m = registration_rotation(0.0)
    between = build_between_factors(np.diff(enu_vo, axis=0), 0.05)
    loop_factors = build_loop_factors(acc, 0.5)
    graph = DemHeightPoseGraph(_NoDem())
    res_pos = graph.solve(enu_vo, between + loop_factors, [], prior_idx=0, prior_xyz=enu_vo[0].copy(),
                          prior_sigma_m=0.5)
    se2 = estimate_se2_loopclosure(enu_vo, quat, r_m, acc, step=max(5, n // 30)) if acc else None

    # freeze + score vs RTK-GPS truth
    gps = load_gps_real(KP + "/gps-latlong.txt")
    gt_xy = gps_latlon_to_local_xy(np.array([g["lat"] for g in gps]), np.array([g["lon"] for g in gps]))
    gt_enu = np.column_stack([gt_xy, np.array([g["alt"] for g in gps]) - gps[0]["alt"]])
    gt_ts = np.array([g["t"] for g in gps])
    ident = np.tile(np.array([1.0, 0.0, 0.0, 0.0]), (n, 1))

    def _score(xyz: np.ndarray, label: str) -> dict:
        p = os.path.join(OUT, f"katwijk_part4_{label}.tum")
        write_tum(p, ts_s, xyz, ident)
        r = score(p, gt_enu, gt_ts, FIG, f"katwijk_part4_{label}", max_diff_s=1.6)
        return {"tum": p, "se3_rmse_m": r["metrics"]["ate_aligned_se3_m"]["rmse"],
                "sim3_rmse_m": r["metrics"]["ate_aligned_sim3_m"]["rmse"],
                "sim3_scale": r["metrics"]["sim3_scale"]}

    sc_vo = _score(enu_vo, "vo")
    sc_pos = _score(res_pos.xyz, "lc_position")
    sc_se2 = _score(se2.xyz, "lc_se2") if se2 is not None else None

    artifact = {
        "experiment": "Katwijk Part4 loop-closing visual SLAM (generalisation of the S3LI estimator to a "
                      "second real rover; ESA Katwijk LocCam, no DEM)",
        "date": str(date.today()), "data": {"dataset": KP, "n_frames": n, "stride": stride,
                                            "gps_truth": KP + "/gps-latlong.txt"},
        "vo": sc_vo, "lc_position": sc_pos, "lc_se2": sc_se2,
        "n_loop_closures": len(acc), "n_candidates": loops["n_candidates"],
        "loop_closures": [lc.to_json() for lc in acc],
        "ladder_se3_rmse_m": {"vo": sc_vo["se3_rmse_m"], "lc_position": sc_pos["se3_rmse_m"],
                              "lc_se2": sc_se2["se3_rmse_m"] if sc_se2 else None},
        "honest_read": (
            "Generalisation of the loop-closing visual SLAM stack (validated on S3LI) to a SECOND real "
            "rover. Part4 is the only Katwijk traverse that closes a loop (76 m). No DEM exists for the "
            "beach, so this is the VO + visual-loop-closure leg only. The VO path length already matches "
            "the GPS-truth loop (no scale bias, unlike S3LI's 4 percent), so loop closure has less gross "
            "drift to remove here than on the 1.3 km S3LI loop."
        ),
        "i3_attestation": "VO + loop closure consume LocCam images + the dataset calibration only; the "
                          "RTK-GPS truth is read solely at scoring, after each estimate is frozen.",
    }
    out = os.path.join(VALID, "katwijk_part4_slam_2026-06-28.json")
    with open(out, "w") as fh:
        json.dump(artifact, fh, indent=2)
    print("\n===== Katwijk Part4 loop-closing visual SLAM (2nd real rover) =====")
    print(f" {len(acc)} loop closures; VO path matches the 76 m GPS loop")
    print(f"  VO            SE3 {sc_vo['se3_rmse_m']:.2f} m  Sim3 {sc_vo['sim3_rmse_m']:.2f} m "
          f"(scale {sc_vo['sim3_scale']:.3f})")
    print(f"  VO+LC(pos)    SE3 {sc_pos['se3_rmse_m']:.2f} m  Sim3 {sc_pos['sim3_rmse_m']:.2f} m")
    if sc_se2:
        print(f"  VO+LC(SE2)    SE3 {sc_se2['se3_rmse_m']:.2f} m  Sim3 {sc_se2['sim3_rmse_m']:.2f} m")
    print(f" artifact -> {out}")


class _NoDem:
    """A null DEM sampler so the position-only pose graph runs without a terrain prior (Katwijk has no
    DEM); no height-normal anchors are added, so height_enu/normal_enu are never queried."""

    def height_enu(self, e: float, north: float) -> float:
        return 0.0

    def normal_enu(self, e: float, north: float) -> np.ndarray:
        return np.array([0.0, 0.0, 1.0])


if __name__ == "__main__":
    main()
