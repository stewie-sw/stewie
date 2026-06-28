"""Reusable, dataset-agnostic figure generator for ARGUS estimator runs.

Given a frozen estimate trajectory (TUM file) and a ground-truth trajectory, this module aligns the
estimate to ground truth with Umeyama (SE(3) and Sim(3)), computes ATE/RPE with evo (the SAME
loading/alignment the run-time scorer uses, so the numbers reproduce the committed scoring artifact),
and emits the paper-style figure set:

  1. ``*_trajectory_overlay.png``  -- top-down X-Y overlay, SE(3)-aligned estimate vs ground truth.
  2. ``*_ate_error_map.png``       -- the aligned estimate path coloured by per-pose ATE (metres).
  3. ``*_drift_vs_distance.png``   -- per-pose ATE vs cumulative ground-truth path length (metres).
  4. ``*_rpe_curve.png``           -- per-step relative pose error vs keyframe index (trans + rot).

plus ``*_metrics.json`` (ATE SE(3)/Sim(3) stats, Sim(3) scale, RPE stats, path lengths). When a
reference scoring artifact is supplied, the recomputed ATE is asserted to match it within a tight
tolerance -- this proves the figure generator reproduces the committed scoring rather than inventing
new numbers; a mismatch raises (the discrepancy is surfaced, never hidden).

GENERALITY: the ground truth is taken as a generic ``evo`` ``PoseTrajectory3D`` OR a :class:`GtSamples`
(positions + timestamps, orientations optional). A thin LuSNAR adapter (:func:`lusnar_gt_trajectory`)
builds the trajectory from :class:`dart.lusnar_reader.LusnarReader`. Nothing here is hardcoded to
LuSNAR, so S3LI / Katwijk / future runs reuse the same code path with their own adapter or a GT TUM.

Firewall note (invariant I3): this is the SCORING / plotting layer, downstream of the frozen estimate.
Plotting ground truth against the estimate is allowed; the firewall is that the ESTIMATOR never reads
ground truth (already enforced upstream where the estimate was produced and frozen).
"""
# PROVENANCE: STEWIE DART subsystem (A. Storey)
from __future__ import annotations

import argparse
import copy
import json
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:  # type-only import; the runtime import is lazy (keeps evo off the import path)
    from evo.core.trajectory import PoseTrajectory3D

# evo's get_all_statistics() keys, in a stable order, used for both the evo path and the hand-built
# world-displacement fallback so the metrics JSON has a uniform schema regardless of GT inputs.
_STAT_KEYS = ("rmse", "mean", "median", "std", "min", "max", "sse")


@dataclass
class GtSamples:
    """Generic ground-truth trajectory samples (dataset-agnostic input to the figure generator).

    ``positions_xyz`` is (N, 3) metres, ``timestamps_s`` is (N,) seconds. ``orientations_quat_wxyz``
    is the optional (N, 4) Hamilton quaternion per pose; when absent, identity orientations are
    synthesised (ATE is position-based, so it is unaffected; the orientation-aware RPE falls back to
    the per-step world-displacement error, which needs no orientation)."""

    positions_xyz: np.ndarray
    timestamps_s: np.ndarray
    orientations_quat_wxyz: np.ndarray | None = None


@dataclass
class FigureBundle:
    """Everything the four figures + metrics JSON need, computed once from a single alignment pass.

    ``metrics`` is the JSON-serialisable summary; the arrays are the per-pose / per-step series the
    figures draw. ``rpe_kind`` records which RPE was computed: ``"hand_eye_frame_to_frame"`` (both
    trajectories carry real orientations) or ``"world_displacement"`` (the position-only fallback)."""

    metrics: dict[str, Any]
    gt_xyz: np.ndarray              # (N, 3) ground-truth positions (associated order)
    est_aligned_xyz: np.ndarray     # (N, 3) SE(3)-Umeyama-aligned estimate positions
    ate_per_pose_m: np.ndarray      # (N,)   per-pose ATE (translation error, SE(3)-aligned)
    cum_gt_dist_m: np.ndarray       # (N,)   cumulative ground-truth path length
    rpe_trans_per_step_m: np.ndarray   # (N-1,) per-step RPE translation
    rpe_rot_per_step_deg: np.ndarray | None  # (N-1,) per-step RPE rotation (None in the fallback)
    rpe_kind: str


# --------------------------------------------------------------------------------------------------
# loading / GT resolution
# --------------------------------------------------------------------------------------------------
def load_estimate(tum_path: str) -> PoseTrajectory3D:
    """Read a frozen estimate trajectory from a TUM file (``t tx ty tz qx qy qz qw``) via evo."""
    from evo.tools import file_interface
    return file_interface.read_tum_trajectory_file(str(tum_path))


def _as_trajectory(gt: PoseTrajectory3D | GtSamples) -> tuple[PoseTrajectory3D, bool]:
    """Resolve a ground-truth input to an evo ``PoseTrajectory3D``.

    Returns ``(trajectory, has_real_orientations)``. A bare :class:`GtSamples` without orientations
    gets identity quaternions and ``has_real_orientations=False`` so the caller can pick the
    orientation-free RPE fallback."""
    from evo.core.trajectory import PoseTrajectory3D
    if isinstance(gt, GtSamples):
        pos = np.asarray(gt.positions_xyz, float)
        ts = np.asarray(gt.timestamps_s, float)
        if gt.orientations_quat_wxyz is None:
            quat = np.tile(np.array([1.0, 0.0, 0.0, 0.0]), (pos.shape[0], 1))
            has_orient = False
        else:
            quat = np.asarray(gt.orientations_quat_wxyz, float)
            has_orient = True
        traj = PoseTrajectory3D(positions_xyz=pos, orientations_quat_wxyz=quat, timestamps=ts)
        return traj, has_orient
    # already a PoseTrajectory3D (carries real orientations)
    return gt, True


def lusnar_gt_trajectory(
    scene_dir: str, *, stride: int = 2, indices: list[int] | None = None
) -> PoseTrajectory3D:
    """LuSNAR adapter: build the ground-truth ``PoseTrajectory3D`` from a LuSNAR scene.

    Mirrors the keystone runner: ground-truth positions/quaternions come from ``reader.pose(i)`` and
    the per-pose timestamps are the frame stems (``reader.timestamps``) in seconds, at the SAME
    keyframe subsample (``stride``) used to produce the frozen estimate, so the two trajectories
    associate 1:1. ``indices`` overrides ``stride`` when given. SCORING/plotting use only (I3)."""
    from evo.core.trajectory import PoseTrajectory3D

    from dart.lusnar_reader import LusnarReader

    reader = LusnarReader(scene_dir)
    if indices is None:
        indices = list(range(0, len(reader), stride))
    poses = [reader.pose(i) for i in indices]
    pos = np.array([p.position_m for p in poses], dtype=np.float64)  # type: ignore[union-attr]
    quat = np.array([p.quaternion_wxyz for p in poses], dtype=np.float64)  # type: ignore[union-attr]
    ts = np.array([reader.timestamps[i] for i in indices], dtype=np.float64) / 1e9
    return PoseTrajectory3D(positions_xyz=pos, orientations_quat_wxyz=quat, timestamps=ts)


# --------------------------------------------------------------------------------------------------
# scoring
# --------------------------------------------------------------------------------------------------
def _stats_dict(stats: dict[str, Any]) -> dict[str, float]:
    """Cast an evo statistics dict to plain floats (JSON-safe), keeping a stable key order."""
    return {k: float(stats[k]) for k in _STAT_KEYS if k in stats}


def _array_stats(err: np.ndarray) -> dict[str, float]:
    """Hand-built statistics (same keys as evo) for the orientation-free per-step fallback."""
    err = np.asarray(err, float)
    return {
        "rmse": float(np.sqrt(np.mean(err ** 2))),
        "mean": float(np.mean(err)),
        "median": float(np.median(err)),
        "std": float(np.std(err)),
        "min": float(np.min(err)),
        "max": float(np.max(err)),
        "sse": float(np.sum(err ** 2)),
    }


def _hand_eye_rotation(traj_est: Any, traj_gt: Any, r_align: np.ndarray) -> np.ndarray:
    """Constant camera/body -> world-body rotation (hand-eye term) recovered at scoring time.

    A VO estimate's per-pose orientation is in its own (e.g. camera-optical) frame; ground truth is in
    the body frame. Umeyama alignment maps POSITIONS to the world frame but leaves this per-pose
    orientation convention, which inflates the body-frame RPE translation. ``R_cb`` is the
    orthonormalised mean of ``R_est_i^T R_align^T R_gt_i`` (constant for a rigid rig); applying it on
    the right of the estimate orientations puts the estimate in the GT body convention so evo's RPE is
    frame-consistent. Reads GT only in the post-freeze scoring path, exactly like Umeyama alignment."""
    r_est = np.array([t[:3, :3] for t in traj_est.poses_se3])
    r_gt = np.array([t[:3, :3] for t in traj_gt.poses_se3])
    m = np.einsum("nij,jk,nkl->il", r_est.transpose(0, 2, 1), r_align.T, r_gt)
    u, _s, vt = np.linalg.svd(m)
    d = np.sign(np.linalg.det(u @ vt))
    return u @ np.diag([1.0, 1.0, d]) @ vt


def compute_figure_bundle(
    traj_est: PoseTrajectory3D, gt: PoseTrajectory3D | GtSamples, *, max_diff_s: float = 0.01
) -> FigureBundle:
    """Associate, Umeyama-align (SE(3) and Sim(3)), and score the estimate against ground truth.

    Returns a :class:`FigureBundle` with the JSON metrics and the per-pose / per-step series the
    figures need. The association + alignment + APE/RPE definitions match the keystone runner, so the
    metrics reproduce the committed scoring artifact."""
    from evo.core import metrics, sync
    from evo.core.trajectory import PoseTrajectory3D

    traj_gt, has_gt_orient = _as_trajectory(gt)
    # 1:1 association by timestamp (estimate + GT were sampled at the same frame timestamps)
    traj_gt, traj_est = sync.associate_trajectories(traj_gt, traj_est, max_diff=max_diff_s)
    est_has_orient = traj_est.poses_se3 is not None

    # --- ATE: APE(translation_part) RMSE under SE(3) and Sim(3) Umeyama alignment ---
    est_se3 = copy.deepcopy(traj_est)
    r_align, _t, _s = est_se3.align(traj_gt, correct_scale=False, correct_only_scale=False)
    ape_se3 = metrics.APE(metrics.PoseRelation.translation_part)
    ape_se3.process_data((traj_gt, est_se3))
    ate_se3 = _stats_dict(ape_se3.get_all_statistics())
    ate_per_pose = np.asarray(ape_se3.error, float)
    est_aligned_xyz = np.asarray(est_se3.positions_xyz, float)

    est_sim3 = copy.deepcopy(traj_est)
    _r, _t2, sim3_scale = est_sim3.align(traj_gt, correct_scale=True, correct_only_scale=False)
    ape_sim3 = metrics.APE(metrics.PoseRelation.translation_part)
    ape_sim3.process_data((traj_gt, est_sim3))
    ate_sim3 = _stats_dict(ape_sim3.get_all_statistics())

    gt_xyz = np.asarray(traj_gt.positions_xyz, float)
    seg = np.linalg.norm(np.diff(gt_xyz, axis=0), axis=1)
    cum_gt_dist = np.concatenate([[0.0], np.cumsum(seg)])
    gt_len = float(seg.sum())
    est_len = float(np.sum(np.linalg.norm(np.diff(np.asarray(traj_est.positions_xyz, float), axis=0), axis=1)))

    # --- RPE: hand-eye-corrected frame-to-frame when orientations exist, else world-displacement ---
    rpe_rot_err: np.ndarray | None
    if has_gt_orient and est_has_orient:
        he = [t.copy() for t in traj_est.poses_se3]
        r_cb = _hand_eye_rotation(traj_est, traj_gt, r_align)
        for t in he:
            t[:3, :3] = t[:3, :3] @ r_cb
        traj_he = PoseTrajectory3D(poses_se3=he, timestamps=traj_est.timestamps.copy())
        traj_he.align(traj_gt, correct_scale=False, correct_only_scale=False)

        m_t = metrics.RPE(metrics.PoseRelation.translation_part, delta=1,
                          delta_unit=metrics.Unit.frames, all_pairs=False)
        m_t.process_data((traj_gt, copy.deepcopy(traj_he)))
        m_r = metrics.RPE(metrics.PoseRelation.rotation_angle_deg, delta=1,
                          delta_unit=metrics.Unit.frames, all_pairs=False)
        m_r.process_data((traj_gt, copy.deepcopy(traj_he)))
        rpe_trans_err = np.asarray(m_t.error, float)
        rpe_rot_err = np.asarray(m_r.error, float)
        rpe_trans_stats = _stats_dict(m_t.get_all_statistics())
        rpe_rot_stats: dict[str, float] | None = _stats_dict(m_r.get_all_statistics())
        rpe_kind = "hand_eye_frame_to_frame"
    else:
        est_a = copy.deepcopy(traj_est)
        est_a.align(traj_gt, correct_scale=False, correct_only_scale=False)
        rpe_trans_err = np.linalg.norm(
            np.diff(np.asarray(est_a.positions_xyz, float), axis=0) - np.diff(gt_xyz, axis=0), axis=1
        )
        rpe_rot_err = None
        rpe_trans_stats = _array_stats(rpe_trans_err)
        rpe_rot_stats = None
        rpe_kind = "world_displacement"

    metrics_out: dict[str, Any] = {
        "n_pose_pairs": int(traj_est.num_poses),
        "ate_aligned_se3_m": ate_se3,
        "ate_aligned_sim3_m": ate_sim3,
        "sim3_scale": float(sim3_scale),
        "rpe_kind": rpe_kind,
        "rpe_trans_m": rpe_trans_stats,
        "rpe_rotation_deg": rpe_rot_stats,
        "gt_path_length_m": gt_len,
        "est_path_length_m": est_len,
        "ate_se3_rmse_m": ate_se3["rmse"],
        "ate_sim3_rmse_m": ate_sim3["rmse"],
        "rpe_rmse_m": rpe_trans_stats["rmse"],
    }
    return FigureBundle(
        metrics=metrics_out,
        gt_xyz=gt_xyz,
        est_aligned_xyz=est_aligned_xyz,
        ate_per_pose_m=ate_per_pose,
        cum_gt_dist_m=cum_gt_dist,
        rpe_trans_per_step_m=rpe_trans_err,
        rpe_rot_per_step_deg=rpe_rot_err,
        rpe_kind=rpe_kind,
    )


# --------------------------------------------------------------------------------------------------
# figures
# --------------------------------------------------------------------------------------------------
def _pyplot() -> Any:
    """Return the headless (Agg) pyplot module."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


def plot_trajectory_overlay(bundle: FigureBundle, label: str, path: str) -> None:
    """Figure 1: top-down X-Y overlay of the SE(3)-aligned estimate vs ground truth."""
    plt = _pyplot()
    gt, est = bundle.gt_xyz, bundle.est_aligned_xyz
    rmse = bundle.metrics["ate_aligned_se3_m"]["rmse"]
    fig, ax = plt.subplots(figsize=(9, 7))
    ax.plot(gt[:, 0], gt[:, 1], "-", color="black", linewidth=2.0, label="ground truth")
    ax.plot(est[:, 0], est[:, 1], "-", color="tab:red", linewidth=1.4, label="estimate (Umeyama SE(3)-aligned)")
    ax.scatter([gt[0, 0]], [gt[0, 1]], c="tab:green", s=70, zorder=5, marker="o", label="start")
    ax.scatter([gt[-1, 0]], [gt[-1, 1]], c="black", s=70, zorder=5, marker="s", label="ground-truth end")
    ax.scatter([est[-1, 0]], [est[-1, 1]], c="tab:red", s=70, zorder=5, marker="X", label="estimate end")
    ax.set_xlabel("world x (m)")
    ax.set_ylabel("world y (m)")
    ax.set_title(f"{label}: trajectory overlay (top-down)  --  ATE RMSE = {rmse:.3f} m")
    ax.set_aspect("equal", adjustable="datalim")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best", fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_ate_error_map(bundle: FigureBundle, label: str, path: str) -> None:
    """Figure 2: the aligned estimate path coloured by per-pose ATE (metres)."""
    plt = _pyplot()
    est = bundle.est_aligned_xyz
    err = bundle.ate_per_pose_m
    gt = bundle.gt_xyz
    fig, ax = plt.subplots(figsize=(9, 7))
    ax.plot(gt[:, 0], gt[:, 1], "-", color="0.7", linewidth=1.5, label="ground truth", zorder=1)
    sc = ax.scatter(est[:, 0], est[:, 1], c=err, cmap="viridis", s=14, zorder=2)
    cbar = fig.colorbar(sc, ax=ax)
    cbar.set_label("per-pose ATE position error (m)")
    ax.set_xlabel("world x (m)")
    ax.set_ylabel("world y (m)")
    ax.set_title(f"{label}: ATE-mapped estimate path  --  max {float(err.max()):.3f} m, "
                 f"mean {float(err.mean()):.3f} m")
    ax.set_aspect("equal", adjustable="datalim")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best", fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_drift_vs_distance(bundle: FigureBundle, label: str, path: str) -> None:
    """Figure 3: per-pose ATE vs cumulative ground-truth path length (metres)."""
    plt = _pyplot()
    dist = bundle.cum_gt_dist_m
    err = bundle.ate_per_pose_m
    rmse = bundle.metrics["ate_aligned_se3_m"]["rmse"]
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(dist, err, "-", color="tab:blue", linewidth=1.2)
    ax.axhline(rmse, color="tab:red", linestyle="--", linewidth=1.0, label=f"ATE RMSE = {rmse:.3f} m")
    ax.set_xlabel("cumulative ground-truth path length (m)")
    ax.set_ylabel("per-pose ATE position error (m)")
    ax.set_title(f"{label}: drift vs distance travelled  --  {float(dist[-1]):.1f} m total")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best", fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_rpe_curve(bundle: FigureBundle, label: str, path: str) -> None:
    """Figure 4: per-step relative pose error vs keyframe index (translation; rotation on a twin axis)."""
    plt = _pyplot()
    trans = bundle.rpe_trans_per_step_m
    kf = np.arange(1, trans.shape[0] + 1)
    rmse = bundle.metrics["rpe_trans_m"]["rmse"]
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(kf, trans, "-", color="tab:purple", linewidth=1.0, label="RPE translation (m)")
    ax.set_xlabel("keyframe index")
    ax.set_ylabel("per-step RPE translation (m)", color="tab:purple")
    ax.tick_params(axis="y", labelcolor="tab:purple")
    ax.grid(True, alpha=0.3)
    title = f"{label}: relative pose error per step  --  trans RMSE = {rmse:.4f} m ({bundle.rpe_kind})"
    if bundle.rpe_rot_per_step_deg is not None:
        ax2 = ax.twinx()
        ax2.plot(kf, bundle.rpe_rot_per_step_deg, "-", color="tab:orange", linewidth=0.8, alpha=0.7,
                 label="RPE rotation (deg)")
        ax2.set_ylabel("per-step RPE rotation (deg)", color="tab:orange")
        ax2.tick_params(axis="y", labelcolor="tab:orange")
        rot_rmse = bundle.metrics["rpe_rotation_deg"]["rmse"]
        title = (f"{label}: relative pose error per step  --  trans RMSE = {rmse:.4f} m, "
                 f"rot RMSE = {rot_rmse:.4f} deg")
        lines = ax.get_lines() + ax2.get_lines()
        ax.legend(lines, [ln.get_label() for ln in lines], loc="best", fontsize=9)
    else:
        ax.legend(loc="best", fontsize=9)
    ax.set_title(title)
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


# --------------------------------------------------------------------------------------------------
# orchestration
# --------------------------------------------------------------------------------------------------
def _compare_to_reference(metrics_out: dict[str, Any], reference_artifact: str,
                          ate_tol_m: float) -> dict[str, Any]:
    """Diff the recomputed ATE/RPE against a committed scoring artifact and assert ATE within tol.

    Returns a comparison block (recorded in the metrics JSON). Raises ``AssertionError`` -- surfacing
    the discrepancy, never hiding it -- if the recomputed ATE drifts past ``ate_tol_m`` from the
    committed value."""
    with open(reference_artifact) as fh:
        ref = json.load(fh)
    rscore = ref.get("scoring", ref)
    ref_se3 = float(rscore["ate_aligned_se3_m"]["rmse"])
    ref_sim3 = float(rscore["ate_aligned_sim3_m"]["rmse"])
    d_se3 = abs(metrics_out["ate_aligned_se3_m"]["rmse"] - ref_se3)
    d_sim3 = abs(metrics_out["ate_aligned_sim3_m"]["rmse"] - ref_sim3)
    comparison: dict[str, Any] = {
        "reference_artifact": os.path.abspath(reference_artifact),
        "ate_tol_m": ate_tol_m,
        "ate_se3_rmse_reference_m": ref_se3,
        "ate_se3_rmse_delta_m": d_se3,
        "ate_sim3_rmse_reference_m": ref_sim3,
        "ate_sim3_rmse_delta_m": d_sim3,
    }
    # RPE is reported too when the reference carries the matching frame-to-frame value.
    ref_rpe = rscore.get("rpe_frame_to_frame_m", {}).get("rmse")
    if ref_rpe is not None:
        comparison["rpe_rmse_reference_m"] = float(ref_rpe)
        comparison["rpe_rmse_delta_m"] = abs(metrics_out["rpe_trans_m"]["rmse"] - float(ref_rpe))
    comparison["ate_matches_reference"] = bool(d_se3 <= ate_tol_m and d_sim3 <= ate_tol_m)
    assert d_se3 <= ate_tol_m, (
        f"recomputed SE(3) ATE RMSE {metrics_out['ate_aligned_se3_m']['rmse']:.6f} m differs from the "
        f"committed {ref_se3:.6f} m by {d_se3:.2e} m (> tol {ate_tol_m:.0e} m)"
    )
    assert d_sim3 <= ate_tol_m, (
        f"recomputed Sim(3) ATE RMSE {metrics_out['ate_aligned_sim3_m']['rmse']:.6f} m differs from the "
        f"committed {ref_sim3:.6f} m by {d_sim3:.2e} m (> tol {ate_tol_m:.0e} m)"
    )
    return comparison


def generate_figures(
    est_tum_path: str,
    gt: PoseTrajectory3D | GtSamples,
    out_dir: str,
    label: str,
    *,
    reference_artifact: str | None = None,
    ate_tol_m: float = 1e-3,
    max_diff_s: float = 0.01,
) -> dict[str, Any]:
    """Emit the 4 figures + metrics JSON for one estimator run and return the result manifest.

    ``est_tum_path``  -- frozen estimate trajectory (TUM).
    ``gt``            -- ground truth: an evo ``PoseTrajectory3D`` or a :class:`GtSamples`.
    ``out_dir``       -- output directory (created if absent).
    ``label``         -- run label; used in titles and as the output-filename stem.
    ``reference_artifact`` -- optional committed scoring JSON; when given, the recomputed ATE is
                              asserted to match it within ``ate_tol_m`` (proves reproduction).

    Returns a dict with ``metrics``, ``figures`` (key -> path), ``metrics_path`` and (if compared)
    ``comparison``."""
    os.makedirs(out_dir, exist_ok=True)
    traj_est = load_estimate(est_tum_path)
    bundle = compute_figure_bundle(traj_est, gt, max_diff_s=max_diff_s)

    figures = {
        "trajectory_overlay": os.path.join(out_dir, f"{label}_trajectory_overlay.png"),
        "ate_error_map": os.path.join(out_dir, f"{label}_ate_error_map.png"),
        "drift_vs_distance": os.path.join(out_dir, f"{label}_drift_vs_distance.png"),
        "rpe_curve": os.path.join(out_dir, f"{label}_rpe_curve.png"),
    }
    plot_trajectory_overlay(bundle, label, figures["trajectory_overlay"])
    plot_ate_error_map(bundle, label, figures["ate_error_map"])
    plot_drift_vs_distance(bundle, label, figures["drift_vs_distance"])
    plot_rpe_curve(bundle, label, figures["rpe_curve"])

    metrics_out = dict(bundle.metrics)
    metrics_out["label"] = label
    metrics_out["estimate_tum"] = os.path.abspath(est_tum_path)
    comparison: dict[str, Any] | None = None
    if reference_artifact is not None:
        comparison = _compare_to_reference(metrics_out, reference_artifact, ate_tol_m)
        metrics_out["comparison"] = comparison

    metrics_path = os.path.join(out_dir, f"{label}_metrics.json")
    with open(metrics_path, "w") as fh:
        json.dump(metrics_out, fh, indent=2)

    result: dict[str, Any] = {
        "metrics": metrics_out,
        "figures": figures,
        "metrics_path": metrics_path,
    }
    if comparison is not None:
        result["comparison"] = comparison
    return result


def main(argv: list[str] | None = None) -> None:
    """CLI: generate the ARGUS figure set for one estimator run.

    GT comes from a LuSNAR scene (``--lusnar-scene`` [+ ``--stride``]) or a ground-truth TUM
    (``--gt-tum``). With ``--reference`` the recomputed ATE is checked against a committed artifact."""
    p = argparse.ArgumentParser(description="ARGUS estimator figure generator (trajectory/ATE/RPE).")
    p.add_argument("--est", required=True, help="frozen estimate trajectory (TUM file)")
    p.add_argument("--out", required=True, help="output directory for the figures + metrics JSON")
    p.add_argument("--label", required=True, help="run label (titles + output filename stem)")
    p.add_argument("--lusnar-scene", help="LuSNAR scene dir; builds GT via the LuSNAR adapter")
    p.add_argument("--stride", type=int, default=2, help="LuSNAR keyframe subsample stride (default 2)")
    p.add_argument("--gt-tum", help="ground-truth trajectory TUM (alternative to --lusnar-scene)")
    p.add_argument("--reference", help="committed scoring JSON to assert the recomputed ATE against")
    p.add_argument("--ate-tol-m", type=float, default=1e-3, help="ATE match tolerance (default 1e-3 m)")
    args = p.parse_args(argv)

    gt: PoseTrajectory3D | GtSamples
    if args.lusnar_scene:
        gt = lusnar_gt_trajectory(args.lusnar_scene, stride=args.stride)
    elif args.gt_tum:
        gt = load_estimate(args.gt_tum)
    else:
        p.error("one of --lusnar-scene or --gt-tum is required for the ground truth")

    result = generate_figures(args.est, gt, args.out, args.label, reference_artifact=args.reference,
                              ate_tol_m=args.ate_tol_m)
    m = result["metrics"]
    print(f"[figures] {args.label} -> {args.out}")
    for key, path in result["figures"].items():
        print(f"  {key:18s} {path}")
    print(f"  metrics            {result['metrics_path']}")
    print(f"  ATE SE(3) RMSE  = {m['ate_aligned_se3_m']['rmse']:.4f} m")
    print(f"  ATE Sim(3) RMSE = {m['ate_aligned_sim3_m']['rmse']:.4f} m (scale {m['sim3_scale']:.5f})")
    print(f"  RPE RMSE        = {m['rpe_trans_m']['rmse']:.4f} m ({m['rpe_kind']})")
    if "comparison" in result:
        c = result["comparison"]
        print(f"  vs reference: ATE SE(3) delta {c['ate_se3_rmse_delta_m']:.2e} m, "
              f"Sim(3) delta {c['ate_sim3_rmse_delta_m']:.2e} m, matches={c['ate_matches_reference']}")


if __name__ == "__main__":
    main()
