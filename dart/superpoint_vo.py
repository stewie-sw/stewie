"""SuperPoint + LightGlue stereo visual odometry on a rectified stereo traverse (truth-clean).

This is the learned-front-end sibling of :mod:`dart.stereo_vo` (which uses an ORB + mutual-NN front
end). The geometry is identical -- calibrated stereo triangulation for a metric per-frame point cloud,
then temporal 3D->2D PnP-RANSAC for the inter-frame rigid motion -- but the keypoints and matches come
from SuperPoint (detector + descriptor) and LightGlue (learned matcher) instead of ORB + Hamming
cross-check. This reproduces the VO front end of arXiv:2603.17229 (SuperPoint+LightGlue stereo VO for
lunar surface navigation).

Pipeline per pair (REAL rendered LuSNAR stereo frames):

  1. SuperPoint on left + right -> keypoints + descriptors; LightGlue matches left<->right.
  2. keep row-aligned (rectified) correspondences (|dy| < row_tol), positive disparity, and
     back-project with the rig intrinsics K + stereo baseline to a metric 3D cloud in the left-camera
     optical frame (x right, y down, z forward). Metric scale comes from fx * baseline / disparity --
     NEVER from ground truth.
  3. LightGlue matches left_t <-> left_{t+1}; for the prior keypoints that carry a triangulated 3D
     point, solve PnP-RANSAC (3D from t, 2D in t+1) for the relative camera motion. Chain into a world
     trajectory + per-frame SE(3) pose.

Truth firewall (invariant I3): :func:`estimate_vo_superpoint` and :func:`triangulate_stereo_superpoint`
accept stereo images + a :class:`~dart.stereo_vo.StereoVOConfig` only. No pose / GtPose / depth / LiDAR
/ slip or any other ground-truth field is ever an argument. Ground truth lives strictly in the
eval/scoring path (loaded AFTER the estimate is frozen). The covariance / invalid-step bookkeeping
(:class:`~dart.stereo_vo.VOResult`) is reused verbatim from :mod:`dart.stereo_vo`.
"""
# PROVENANCE: STEWIE DART subsystem (A. Storey)
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .features import to_gray_u8
from .stereo_vo import (
    _INVALID_STEP_COV,
    StereoVOConfig,
    VOResult,
    _solve_pnp,
    _valid_step_covariance,
    disparity_to_depth,
)

# Lazily-initialised SuperPoint extractor + LightGlue matcher (weights download on first use).
_SP = None
_LG = None
_DEVICE = None


def _load_frontend(max_num_keypoints: int = 2048):
    """Load (once) the SuperPoint extractor + LightGlue matcher onto CUDA if available, else CPU.

    Returns ``(superpoint, lightglue, torch_device)``. Both nets are in ``eval()`` mode (no dropout),
    so a forward pass is deterministic for a given input. Reused across every frame in a traverse.
    """
    global _SP, _LG, _DEVICE
    if _SP is None or _LG is None:
        import torch
        from lightglue import LightGlue, SuperPoint
        _DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        _SP = SuperPoint(max_num_keypoints=max_num_keypoints).eval().to(_DEVICE)
        _LG = LightGlue(features="superpoint").eval().to(_DEVICE)
    return _SP, _LG, _DEVICE


def _extract(gray_u8: np.ndarray):
    """SuperPoint on a single-channel uint8 image -> (batched_feats_dict, keypoints_px (N,2) numpy)."""
    import torch
    sp, _, dev = _load_frontend()
    t = torch.from_numpy(np.ascontiguousarray(gray_u8, dtype=np.float32) / 255.0)[None, None].to(dev)
    with torch.inference_mode():
        feats = sp.extract(t)
    kpts = feats["keypoints"][0].detach().cpu().numpy()
    return feats, kpts


def _match(feats0, feats1) -> np.ndarray:
    """LightGlue match between two batched SuperPoint feature dicts -> (M,2) int index pairs.

    Column 0 indexes ``feats0`` keypoints, column 1 indexes ``feats1`` keypoints. Empty (0,2) if no
    match survives. Images-derived features only -- no ground truth (invariant I3)."""
    import torch
    from lightglue.utils import rbd
    _, lg, _ = _load_frontend()
    with torch.inference_mode():
        out = lg({"image0": feats0, "image1": feats1})
    matches = rbd(out)["matches"].detach().cpu().numpy()
    if matches.size == 0:
        return np.empty((0, 2), dtype=int)
    return matches.astype(int).reshape(-1, 2)


@dataclass(frozen=True)
class SuperPointStereoCloud:
    """A SuperPoint+LightGlue triangulated stereo frame.

    ``points_3d`` (N,3) are metres in the left-camera optical frame; ``keypoints_px`` (N,2) are the
    left-image pixel coordinates of each point; ``left_feat_idx`` (N,) is the index of each point's
    left keypoint within the full left SuperPoint extraction (so the temporal matcher can re-identify
    a point by its left feature); ``disparity_px`` (N,) is the positive horizontal disparity used.
    ``n_left_keypoints``/``n_right_keypoints`` are the full SuperPoint counts for the pair. Images
    only -- no truth field (invariant I3)."""

    points_3d: np.ndarray
    keypoints_px: np.ndarray
    left_feat_idx: np.ndarray
    disparity_px: np.ndarray
    n_left_keypoints: int
    n_right_keypoints: int


@dataclass(frozen=True)
class _FrameState:
    """Per-frame cache carried across the temporal loop: the full left SuperPoint feats (for the next
    frame's temporal LightGlue match), the full left keypoints, the triangulated cloud, and a map from
    every full-left-keypoint index to its row in ``cloud.points_3d`` (or -1 if not triangulated)."""

    left_feats: object
    left_kpts: np.ndarray
    cloud: SuperPointStereoCloud
    feat_to_point: np.ndarray


@dataclass(frozen=True)
class SuperPointVOResult:
    """SuperPoint+LightGlue VO over a stereo sequence. Wraps the reused :class:`VOResult` and adds the
    per-frame world camera poses (4x4 SE(3), camera-to-world, first camera = world origin) needed to
    write a TUM trajectory + score with evo, plus the learned-front-end diagnostics.

    ``camera_poses`` (F,4,4) are the accumulated camera-to-world transforms; for an invalid/held step
    the pose HOLDS the last trusted pose (the missing motion cannot be invented). ``n_temporal_matches``
    is the LightGlue left_t<->left_{t+1} match count per step; ``n_pnp_correspondences`` the subset of
    those that carried a triangulated 3D point (the PnP input size)."""

    vo: VOResult
    camera_poses: np.ndarray
    n_temporal_matches: list[int] = field(default_factory=list)
    n_pnp_correspondences: list[int] = field(default_factory=list)

    @property
    def trajectory_xyz_m(self) -> np.ndarray:
        return self.vo.trajectory_xyz_m

    @property
    def trajectory_valid(self) -> list[bool]:
        return list(self.vo.trajectory_valid)


def triangulate_stereo_superpoint(
    image_left: np.ndarray,
    image_right: np.ndarray,
    config: StereoVOConfig,
) -> tuple[SuperPointStereoCloud, object, np.ndarray]:
    """Triangulate a rectified stereo pair into a metric cloud using a SuperPoint+LightGlue front end.

    Returns ``(cloud, left_feats, left_kpts)``: the triangulated cloud plus the full left SuperPoint
    feats + keypoints (so the caller can run the temporal LightGlue match without re-extracting).
    Detects SuperPoint on both images, LightGlue-matches left<->right, keeps row-aligned positive-
    disparity correspondences, and back-projects with K + baseline. Images only (invariant I3).
    """
    gl, gr = to_gray_u8(image_left), to_gray_u8(image_right)
    if gl.shape != gr.shape:
        raise ValueError("stereo images must have the same shape")
    fl, kl = _extract(gl)
    fr, kr = _extract(gr)
    n_l, n_r = int(kl.shape[0]), int(kr.shape[0])
    pairs = _match(fl, fr)
    if pairs.shape[0] == 0:
        empty = SuperPointStereoCloud(
            points_3d=np.empty((0, 3)), keypoints_px=np.empty((0, 2)),
            left_feat_idx=np.empty(0, dtype=int), disparity_px=np.empty(0),
            n_left_keypoints=n_l, n_right_keypoints=n_r,
        )
        return empty, fl, kl
    li, ri = pairs[:, 0], pairs[:, 1]
    pl, pr = kl[li], kr[ri]
    # rectified pair: keep row-aligned matches and fix the consensus disparity sign (left-x minus
    # right-x is positive for a standard left/right rig)
    row_ok = np.abs(pl[:, 1] - pr[:, 1]) < config.row_tol_px
    signed = pl[:, 0] - pr[:, 0]
    sign = 1.0 if (not np.any(row_ok) or np.median(signed[row_ok]) >= 0.0) else -1.0
    disparity = sign * signed
    keep = row_ok & (disparity > config.min_disparity_px)
    pl_k, disp_k, li_k = pl[keep], disparity[keep], li[keep]
    depth = disparity_to_depth(disp_k, fx_px=config.fx_px, baseline_m=config.baseline_m)
    x = (pl_k[:, 0] - config.cx_px) * depth / config.fx_px
    y = (pl_k[:, 1] - config.cy_px) * depth / config.fy_px
    points_3d = np.stack([x, y, depth], axis=1)
    cloud = SuperPointStereoCloud(
        points_3d=points_3d,
        keypoints_px=pl_k,
        left_feat_idx=li_k.astype(int),
        disparity_px=disp_k,
        n_left_keypoints=n_l,
        n_right_keypoints=n_r,
    )
    return cloud, fl, kl


def _frame_state(image_left: np.ndarray, image_right: np.ndarray, config: StereoVOConfig) -> _FrameState:
    cloud, fl, kl = triangulate_stereo_superpoint(image_left, image_right, config)
    feat_to_point = np.full(int(kl.shape[0]), -1, dtype=int)
    feat_to_point[cloud.left_feat_idx] = np.arange(cloud.left_feat_idx.shape[0])
    return _FrameState(left_feats=fl, left_kpts=kl, cloud=cloud, feat_to_point=feat_to_point)


def estimate_vo_superpoint(
    stereo_pairs: list[tuple[np.ndarray, np.ndarray]],
    config: StereoVOConfig,
    *,
    deterministic: bool = True,
) -> SuperPointVOResult:
    """SuperPoint+LightGlue stereo-PnP visual odometry over a sequence of rectified stereo pairs.

    For each pair the left cloud is triangulated; consecutive frames are linked by a LightGlue match of
    the prior frame's left keypoints to the current frame's left keypoints, restricted to prior
    keypoints that carry a triangulated 3D point, and the relative motion is solved by PnP-RANSAC (the
    same solver + invalid-step/covariance bookkeeping as :func:`dart.stereo_vo.estimate_vo`). The
    accumulated world trajectory + per-frame SE(3) poses start at the origin (first camera = world).

    ``deterministic`` seeds the OpenCV RANSAC RNG (and torch) so a re-run on identical images is
    reproducible -- which is what lets the I3 poison test assert a byte-identical estimate when GT is
    withheld/corrupted. Images + calibration only; no ground-truth field (invariant I3).
    """
    if len(stereo_pairs) < 2:
        raise ValueError("need at least two stereo pairs for visual odometry")
    if deterministic:
        import cv2
        cv2.setRNGSeed(0)
        try:
            import torch
            torch.manual_seed(0)
        except Exception:
            pass
    K = config.matrix()

    rel_t: list[np.ndarray] = []
    rel_R: list[np.ndarray] = []
    inliers: list[int] = []
    step_valid: list[bool] = []
    rel_cov: list[np.ndarray] = []
    point_counts: list[int] = []
    n_temporal: list[int] = []
    n_corr: list[int] = []

    R_wc = np.eye(3)
    t_wc = np.zeros(3)
    traj = [t_wc.copy()]
    traj_valid = [True]
    poses = [np.eye(4)]
    chain_trusted = True

    prev = _frame_state(stereo_pairs[0][0], stereo_pairs[0][1], config)
    point_counts.append(int(prev.cloud.points_3d.shape[0]))

    for k in range(1, len(stereo_pairs)):
        cur = _frame_state(stereo_pairs[k][0], stereo_pairs[k][1], config)
        point_counts.append(int(cur.cloud.points_3d.shape[0]))

        # temporal LightGlue match: prior left keypoints -> current left keypoints
        tmatch = _match(prev.left_feats, cur.left_feats)
        n_temporal.append(int(tmatch.shape[0]))
        if tmatch.shape[0] == 0:
            R_rel, t_rel, n_inl, n_used = None, None, 0, 0
        else:
            prev_pt_row = prev.feat_to_point[tmatch[:, 0]]
            has_pt = prev_pt_row >= 0
            obj = prev.cloud.points_3d[prev_pt_row[has_pt]]
            img = cur.left_kpts[tmatch[has_pt, 1]]
            n_used = int(obj.shape[0])
            if n_used >= 6:
                R_rel, t_rel, n_inl = _solve_pnp(obj, img, K, config)
            else:
                R_rel, t_rel, n_inl = None, None, 0
        inliers.append(n_inl)
        n_corr.append(n_used)

        if R_rel is None or t_rel is None:
            # M-03: failed solve is INVALID/MISSING, not a fabricated zero motion. NaN motion +
            # inflated covariance; the world pose HOLDS the last trusted pose across the gap.
            step_valid.append(False)
            rel_R.append(np.full((3, 3), np.nan))
            rel_t.append(np.full(3, np.nan))
            rel_cov.append(_INVALID_STEP_COV.copy())
            chain_trusted = False
            traj.append(t_wc.copy())
            traj_valid.append(False)
            poses.append(_se3(R_wc, t_wc))
            prev = cur
            continue

        motion_prev = -R_rel.T @ t_rel
        step_valid.append(True)
        rel_R.append(R_rel)
        rel_t.append(motion_prev)
        rel_cov.append(_valid_step_covariance(n_inl))
        t_wc = t_wc + R_wc @ motion_prev
        R_wc = R_wc @ R_rel.T
        traj.append(t_wc.copy())
        traj_valid.append(chain_trusted)
        poses.append(_se3(R_wc, t_wc))
        prev = cur

    vo = VOResult(
        relative_translations_m=np.array(rel_t) if rel_t else np.empty((0, 3)),
        relative_rotations=rel_R,
        trajectory_xyz_m=np.array(traj),
        pnp_inliers=inliers,
        stereo_point_counts=point_counts,
        step_valid=step_valid,
        relative_covariances=rel_cov,
        trajectory_valid=traj_valid,
    )
    return SuperPointVOResult(
        vo=vo,
        camera_poses=np.array(poses),
        n_temporal_matches=n_temporal,
        n_pnp_correspondences=n_corr,
    )


def _se3(R: np.ndarray, t: np.ndarray) -> np.ndarray:
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = t
    return T
