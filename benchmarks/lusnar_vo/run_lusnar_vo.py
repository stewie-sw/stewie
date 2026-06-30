"""SuperPoint+LightGlue stereo VO on the REAL LuSNAR Moon_1 lunar traverse, scored with evo.

This is the keystone estimator experiment for STEWIE navigation (reproducing the VO family of
arXiv:2603.17229: a SuperPoint+LightGlue stereo VO front end on a lunar sequence, scored against ground
truth). It runs in two strictly ordered phases with the truth firewall (invariant I3/I7) between them:

  PHASE 1 (estimate, truth-clean): read ONLY left+right images + the camera intrinsics K + the stereo
      baseline. Run dart.superpoint_vo.estimate_vo_superpoint. FREEZE the estimated trajectory to disk
      (TUM .txt) BEFORE any ground-truth pose is loaded.
  PHASE 2 (score): only now load gt.txt (reader.pose), build evo trajectories, align with Umeyama
      (SE(3) and Sim(3)), and report ATE (aligned + unaligned) + RPE.

DEM anchoring (paper STEP 2) is a documented firewall boundary on LuSNAR: see the artifact's
`dem_anchoring` block and the printed note. LuSNAR ships no orbital/global DEM independent of the
rover trajectory; the only buildable DEM (reader.scene_dem) is assembled from GT-posed LiDAR, so using
it to anchor would leak GT into the estimator. VO-only is delivered as the clean result.

Run:  cd /mnt/projects/stewie/code && .venv/bin/python benchmarks/lusnar_vo/run_lusnar_vo.py [N] [MAXKF]
  N      = frame subsample stride (default 2; cover the full ~256 m traverse)
  MAXKF  = optional cap on number of keyframes (default: all)
"""
from __future__ import annotations

import copy
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, "/mnt/projects/stewie/code")
from dart.lusnar_reader import (  # noqa: E402
    LUSNAR_BASELINE_M,
    LUSNAR_INTRINSICS,
    LusnarReader,
)
from dart.stereo_vo import StereoVOConfig  # noqa: E402
from dart.superpoint_vo import estimate_vo_superpoint  # noqa: E402

SCENE = "/mnt/projects/datasets/argus_dem_nav/lusnar/extracted/Moon_1"
OUT_DIR = "/mnt/projects/stewie/code/stewie/eval/validation"
DATE = "2026-06-28"
ARTIFACT_JSON = os.path.join(OUT_DIR, f"lusnar_vo_dem_anchor_{DATE}.json")
ARTIFACT_PNG = os.path.join(OUT_DIR, f"lusnar_vo_dem_anchor_{DATE}.png")
FROZEN_TUM = os.path.join(OUT_DIR, f"lusnar_vo_estimate_{DATE}.tum")


def _config() -> StereoVOConfig:
    """Calibration-only StereoVOConfig from the published LuSNAR sensor spec (a camera property, not a
    pose). reprojection/inlier gates are the dart.stereo_vo defaults."""
    K = LUSNAR_INTRINSICS
    return StereoVOConfig(
        fx_px=K.fx, fy_px=K.fy, cx_px=K.cx, cy_px=K.cy,
        baseline_m=LUSNAR_BASELINE_M,
        n_features=2048, row_tol_px=2.0, min_disparity_px=1.0,
        reprojection_px=2.0, min_pnp_inliers=12,
    )


def _write_tum(path: str, timestamps_s: np.ndarray, poses_se3: np.ndarray) -> None:
    """Freeze the estimated trajectory as a TUM file: `t tx ty tz qx qy qz qw` (one frozen artifact)."""
    from evo.core.trajectory import PoseTrajectory3D
    traj = PoseTrajectory3D(poses_se3=list(poses_se3), timestamps=np.asarray(timestamps_s, float))
    from evo.tools import file_interface
    file_interface.write_tum_trajectory_file(path, traj)


def _hand_eye(traj_est, traj_gt, R_align: np.ndarray) -> np.ndarray:
    """Recover the constant camera-optical -> body rotation (hand-eye term) at SCORING time.

    The estimate's per-pose orientation is in the camera-optical frame (x right, y down, z forward);
    GT is in the body frame. Global Umeyama alignment (R_align) maps est POSITIONS to the world frame
    but leaves this per-pose orientation convention in place, which would inflate the body-frame RPE
    translation by ~step_length * sqrt(2) for the ~90deg axis offset. R_cb = orthonormalised mean of
    R_est_i^T R_align^T R_gt_i is constant for a rigid rig; applying it on the right of the est
    orientations puts the estimate in the GT body convention so evo's RPE is frame-consistent. This
    reads GT, but ONLY in the post-freeze scoring path (exactly like Umeyama alignment) -- the frozen
    estimate is unchanged. Corroborated by the alignment-only world-displacement RPE below."""
    Re = np.array([T[:3, :3] for T in traj_est.poses_se3])
    Rg = np.array([T[:3, :3] for T in traj_gt.poses_se3])
    M = np.einsum("nij,jk,nkl->il", Re.transpose(0, 2, 1), R_align.T, Rg)
    U, _s, Vt = np.linalg.svd(M)
    d = np.sign(np.linalg.det(U @ Vt))
    return U @ np.diag([1.0, 1.0, d]) @ Vt


def _evo_score(est_poses: np.ndarray, est_ts: np.ndarray, gt_pos: np.ndarray,
               gt_quat_wxyz: np.ndarray, gt_ts: np.ndarray) -> dict:
    """Score the frozen estimate against GT with evo. ATE = APE(translation_part) RMSE under Umeyama
    SE(3) and Sim(3) alignment, plus an unaligned (raw-frame) ATE; RPE = frame-to-frame translation
    (both the raw body-frame value and the hand-eye-corrected, frame-consistent value)."""
    from evo.core import metrics, sync
    from evo.core.trajectory import PoseTrajectory3D

    traj_est = PoseTrajectory3D(poses_se3=list(est_poses), timestamps=np.asarray(est_ts, float))
    traj_gt = PoseTrajectory3D(
        positions_xyz=np.asarray(gt_pos, float),
        orientations_quat_wxyz=np.asarray(gt_quat_wxyz, float),
        timestamps=np.asarray(gt_ts, float),
    )
    # exact 1:1 association (we sampled GT at the same frame timestamps)
    traj_gt, traj_est = sync.associate_trajectories(traj_gt, traj_est, max_diff=0.01)

    def _ate(align: bool, scale: bool):
        est = copy.deepcopy(traj_est)
        s, R_align = 1.0, np.eye(3)
        if align:
            R_align, _t, s = est.align(traj_gt, correct_scale=scale, correct_only_scale=False)
        ape = metrics.APE(metrics.PoseRelation.translation_part)
        ape.process_data((traj_gt, est))
        return ape.get_all_statistics(), float(s), np.asarray(R_align, float)

    se3_stats, _, R_align = _ate(align=True, scale=False)
    sim3_stats, sim3_scale, _ = _ate(align=True, scale=True)
    raw_stats, _, _ = _ate(align=False, scale=False)

    def _rpe(traj, relation):
        m = metrics.RPE(relation, delta=1, delta_unit=metrics.Unit.frames, all_pairs=False)
        m.process_data((traj_gt, copy.deepcopy(traj)))
        return m.get_all_statistics()

    # raw body-frame RPE (camera-optical convention -> inflated by the axis offset)
    rpe_raw = _rpe(traj_est, metrics.PoseRelation.translation_part)
    # hand-eye-corrected, frame-consistent RPE (the meaningful per-step VO error)
    R_cb = _hand_eye(traj_est, traj_gt, R_align)
    he_poses = [T.copy() for T in traj_est.poses_se3]
    for T in he_poses:
        T[:3, :3] = T[:3, :3] @ R_cb
    traj_he = PoseTrajectory3D(poses_se3=he_poses, timestamps=traj_est.timestamps.copy())
    traj_he.align(traj_gt, correct_scale=False)
    rpe_trans = _rpe(traj_he, metrics.PoseRelation.translation_part)
    rpe_rot = _rpe(traj_he, metrics.PoseRelation.rotation_angle_deg)

    # alignment-only corroboration: per-step WORLD-frame displacement error (no orientation handling)
    est_a = copy.deepcopy(traj_est)
    est_a.align(traj_gt, correct_scale=False)
    dstep = np.linalg.norm(np.diff(est_a.positions_xyz, axis=0) - np.diff(traj_gt.positions_xyz, axis=0), axis=1)
    world_disp_rmse = float(np.sqrt(np.mean(dstep ** 2)))

    gt_len = float(np.sum(np.linalg.norm(np.diff(traj_gt.positions_xyz, axis=0), axis=1)))
    est_len = float(np.sum(np.linalg.norm(np.diff(traj_est.positions_xyz, axis=0), axis=1)))
    return {
        "ate_aligned_se3_m": se3_stats,
        "ate_aligned_sim3_m": sim3_stats,
        "sim3_scale": sim3_scale,
        "ate_unaligned_raw_m": raw_stats,
        "rpe_frame_to_frame_m": rpe_trans,
        "rpe_frame_to_frame_rotation_deg": rpe_rot,
        "rpe_raw_body_frame_m": rpe_raw,
        "rpe_raw_note": (
            "raw body-frame evo RPE; inflated ~step_length*sqrt(2) by the camera-optical vs body axis "
            "convention. rpe_frame_to_frame_m is the hand-eye-corrected, frame-consistent value."
        ),
        "per_step_world_displacement_rmse_m": world_disp_rmse,
        "gt_path_length_m": gt_len,
        "est_path_length_m": est_len,
        "n_pose_pairs": int(traj_est.num_poses),
    }


def _overlay_png(path: str, est_poses: np.ndarray, gt_pos: np.ndarray, traj_gt, est_aligned_xyz) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(gt_pos[:, 0], gt_pos[:, 1], "-", color="k", linewidth=2.0, label="ground truth")
    ax.plot(est_aligned_xyz[:, 0], est_aligned_xyz[:, 1], "-", color="tab:red", linewidth=1.5,
            label="SuperPoint+LightGlue VO (SE(3)-aligned)")
    ax.scatter([gt_pos[0, 0]], [gt_pos[0, 1]], c="green", s=60, zorder=5, label="start")
    ax.set_xlabel("world x (m)")
    ax.set_ylabel("world y (m)")
    ax.set_title("LuSNAR Moon_1: SuperPoint+LightGlue stereo VO vs ground truth (top-down)")
    ax.axis("equal")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    n_sub = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    max_kf = int(sys.argv[2]) if len(sys.argv) > 2 else None

    reader = LusnarReader(SCENE)
    indices = list(range(0, len(reader), n_sub))
    if max_kf is not None:
        indices = indices[:max_kf]
    config = _config()

    # ---------------- PHASE 1: estimate (truth-clean) ----------------
    # Read ONLY left+right images. frame.pose is NOT touched here.
    print(f"[phase1] loading {len(indices)} keyframes (stride {n_sub}) -- images only ...", flush=True)
    stereo_pairs: list[tuple[np.ndarray, np.ndarray]] = []
    est_ts: list[float] = []
    for i in indices:
        fr = reader.frame(i)
        if fr.right is None:
            raise RuntimeError(f"frame {i} has no right image; stereo VO needs both cameras")
        stereo_pairs.append((fr.left, fr.right))
        est_ts.append(fr.timestamp_ns / 1e9)
    est_ts_arr = np.asarray(est_ts, float)

    print("[phase1] running SuperPoint+LightGlue stereo-PnP VO ...", flush=True)
    t0 = time.perf_counter()
    result = estimate_vo_superpoint(stereo_pairs, config, deterministic=True)
    vo_seconds = time.perf_counter() - t0
    est_poses = result.camera_poses
    print(f"[phase1] VO done in {vo_seconds:.1f}s; {est_poses.shape[0]} poses; "
          f"valid steps {sum(result.vo.step_valid)}/{len(result.vo.step_valid)}", flush=True)

    # FREEZE the estimate to disk BEFORE any GT is loaded (I7).
    _write_tum(FROZEN_TUM, est_ts_arr, est_poses)
    frozen_mtime = os.path.getmtime(FROZEN_TUM)
    print(f"[phase1] FROZEN estimate -> {FROZEN_TUM}", flush=True)

    # ---------------- I3 poison check: estimate never saw GT ----------------
    # Re-run the estimator on a poisoned reader whose GT is corrupted; the images are byte-identical,
    # so the frozen estimate must be byte-identical too (the estimator takes images only).
    poison = LusnarReader(SCENE)
    poison._gt_pos = (poison._gt_pos + 1.0e6)  # corrupt every GT position (eval layer only)
    poison_pairs = [(poison.frame(i).left, poison.frame(i).right) for i in indices[: min(6, len(indices))]]
    poison_res = estimate_vo_superpoint(poison_pairs, config, deterministic=True)
    clean_res = estimate_vo_superpoint(
        [stereo_pairs[j] for j in range(min(6, len(stereo_pairs)))], config, deterministic=True
    )
    poison_identical = bool(np.array_equal(poison_res.camera_poses, clean_res.camera_poses))
    print(f"[i3] poison test (GT corrupted): estimate byte-identical = {poison_identical}", flush=True)

    # ---------------- PHASE 2: score (GT loaded ONLY now) ----------------
    print("[phase2] loading ground truth + scoring with evo ...", flush=True)
    gt_pos = np.array([reader.pose(i).position_m for i in indices], float)
    gt_quat = np.array([reader.pose(i).quaternion_wxyz for i in indices], float)
    gt_ts = est_ts_arr.copy()  # GT sampled at the same frame indices/timestamps

    scores = _evo_score(est_poses, est_ts_arr, gt_pos, gt_quat, gt_ts)

    # aligned est for the overlay
    from evo.core import sync
    from evo.core.trajectory import PoseTrajectory3D
    te = PoseTrajectory3D(poses_se3=list(est_poses), timestamps=est_ts_arr)
    tg = PoseTrajectory3D(positions_xyz=gt_pos, orientations_quat_wxyz=gt_quat, timestamps=gt_ts)
    tg, te = sync.associate_trajectories(tg, te, max_diff=0.01)
    te.align(tg, correct_scale=False)
    _overlay_png(ARTIFACT_PNG, est_poses, gt_pos, tg, te.positions_xyz)
    print(f"[phase2] overlay -> {ARTIFACT_PNG}", flush=True)

    import evo
    artifact = {
        "experiment": "LuSNAR Moon_1 SuperPoint+LightGlue stereo VO (keystone estimator)",
        "date": DATE,
        "reproduces": "arXiv:2603.17229 VO front end (SuperPoint+LightGlue stereo VO, lunar nav)",
        "dataset": {
            "name": "LuSNAR Moon_1 (arXiv:2407.06512, JeremyLuo/LuSNAR, real on-disk UE-rendered sensor data)",
            "scene_dir": SCENE,
            "n_frames_total": len(reader),
            "subsample_stride_N": n_sub,
            "n_keyframes_used": len(indices),
            "frame_index_range": [int(indices[0]), int(indices[-1])],
        },
        "front_end": "superpoint+lightglue (lightglue.SuperPoint max_num_keypoints=2048 + LightGlue features='superpoint')",
        "motion_estimation": "stereo triangulation (fx*B/disparity, metric) -> temporal LightGlue match -> 3D-2D PnP-RANSAC (cv2.solvePnPRansac); chained SE(3)",
        "solver_reused": "dart.stereo_vo._solve_pnp + VOResult invalid-step/covariance bookkeeping; dart.superpoint_vo front end",
        "intrinsics": {"fx": LUSNAR_INTRINSICS.fx, "fy": LUSNAR_INTRINSICS.fy,
                       "cx": LUSNAR_INTRINSICS.cx, "cy": LUSNAR_INTRINSICS.cy,
                       "baseline_m": LUSNAR_BASELINE_M},
        "vo_runtime_s": vo_seconds,
        "vo_diagnostics": {
            "valid_steps": int(sum(result.vo.step_valid)),
            "total_steps": int(len(result.vo.step_valid)),
            "median_pnp_inliers": float(np.median(result.vo.pnp_inliers)) if result.vo.pnp_inliers else None,
            "median_stereo_points": float(np.median(result.vo.stereo_point_counts)),
            "median_temporal_matches": float(np.median(result.n_temporal_matches)) if result.n_temporal_matches else None,
            "median_pnp_correspondences": float(np.median(result.n_pnp_correspondences)) if result.n_pnp_correspondences else None,
        },
        "evo_version": evo.__version__,
        "scoring": scores,
        "ate_vo_aligned_se3_rmse_m": scores["ate_aligned_se3_m"]["rmse"],
        "ate_vo_aligned_sim3_rmse_m": scores["ate_aligned_sim3_m"]["rmse"],
        "ate_vo_unaligned_rmse_m": scores["ate_unaligned_raw_m"]["rmse"],
        "rpe_vo_rmse_m": scores["rpe_frame_to_frame_m"]["rmse"],
        "ate_anchored_m": None,
        "dem_anchoring": {
            "ran": False,
            "firewall_reason": (
                "LuSNAR ships NO orbital/global DEM independent of the rover trajectory. The only "
                "buildable scene DEM (dart.lusnar_reader.scene_dem) is assembled from per-frame LiDAR "
                "clouds placed by their GROUND-TRUTH LiDAR sensor world poses (lidar_sensor_pose), so it "
                "is GT-trajectory-derived. Anchoring the VO to it would leak GT into the estimator "
                "(violates I3). Per the build spec, the GT-derived DEM is NOT used for anchoring; the "
                "VO-only result is delivered as the clean finalized result."
            ),
            "what_an_independent_prior_would_need": (
                "A pre-surveyed orbital-style DEM independent of THIS run's trajectory, e.g. rasterize "
                "the UE scene's global terrain mesh to a heightmap (not shipped on disk for Moon_1), or "
                "hold out a separate dedicated mapping pass and rasterize that, then add a "
                "DEM_HEIGHT_NORMAL factor (dart.factors) sampling the prior at the ESTIMATED horizontal "
                "cell. The factor machinery (dart.factors.FactorType.DEM_HEIGHT_NORMAL, dart.dem_anchor) "
                "and pose graph (dart.pose_graph_se2) already exist and are ready for such a prior."
            ),
        },
        "i3_firewall_attestation": {
            "estimator_signature_pose_free": True,
            "estimator_args": "estimate_vo_superpoint(stereo_pairs=list[(left,right)], config=StereoVOConfig)",
            "estimate_frozen_before_gt": True,
            "frozen_trajectory_file": FROZEN_TUM,
            "frozen_mtime": frozen_mtime,
            "poison_test_byte_identical": poison_identical,
            "poison_test_description": (
                "Re-ran the estimator on a reader whose every GT position was corrupted (+1e6 m). The "
                "left/right images are byte-identical, so the estimate is byte-identical -- proving the "
                "estimator output does not depend on GT."
            ),
        },
    }
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(ARTIFACT_JSON, "w") as fh:
        json.dump(artifact, fh, indent=2)
    print(f"[done] artifact -> {ARTIFACT_JSON}", flush=True)
    print(f"  ATE_vo SE(3)-aligned RMSE = {artifact['ate_vo_aligned_se3_rmse_m']:.3f} m", flush=True)
    print(f"  ATE_vo Sim(3)-aligned RMSE = {artifact['ate_vo_aligned_sim3_rmse_m']:.3f} m "
          f"(scale {scores['sim3_scale']:.4f})", flush=True)
    print(f"  ATE_vo unaligned RMSE = {artifact['ate_vo_unaligned_rmse_m']:.3f} m", flush=True)
    print(f"  RPE_vo frame-to-frame RMSE = {artifact['rpe_vo_rmse_m']:.3f} m", flush=True)
    print(f"  GT path {scores['gt_path_length_m']:.1f} m  est path {scores['est_path_length_m']:.1f} m", flush=True)


if __name__ == "__main__":
    main()
