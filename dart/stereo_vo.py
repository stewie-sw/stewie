"""Calibrated stereo-triangulation + PnP visual odometry on the rendered lunar stereo traverse.

Pipeline (all on REAL rendered Godot frames; part of the VO/landmark backbone):

  1. detect + mutual-NN match keypoints in the stereo pair (reuses the ORB front end and the
     :func:`dart.features.to_gray_u8` converter from the feature module);
  2. keep row-aligned (rectified) correspondences, fix the consensus disparity sign, and
     triangulate to a metric point cloud in the reference (left) camera optical frame using the rig
     intrinsics -- fx from the camera HFOV, baseline from the calibrated stereo mount (0.07 m);
  3. across consecutive frames, match the 3D-bearing descriptors of frame k to the keypoints of
     frame k+1 and solve PnP (RANSAC) for the inter-frame rigid motion, accumulating a trajectory.

The depth scale is recovered numerically: depth = fx*B/disparity is the exact inverse of
disparity = fx*B/depth, so triangulated depths carry true metres, and the PnP step inherits that
metric scale, letting the recovered traverse length be compared against the ground-truth length.

Truth firewall (invariant I3): :func:`triangulate_stereo` and :func:`estimate_vo` accept rendered
images and a :class:`StereoVOConfig` only -- no pose, slip, or other ground-truth field is ever an
argument. Ground truth lives strictly in the eval/scoring path (tests + validation scoring), never in
the estimator input.
"""
# PROVENANCE: STEWIE DART subsystem (A. Storey)
from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np

from .features import to_gray_u8


@dataclass(frozen=True)
class StereoVOConfig:
    """Pinhole intrinsics (px) + stereo baseline (m) for the rig that rendered the pair.

    ``fx_px``/``fy_px`` are the focal lengths, ``cx_px``/``cy_px`` the principal point, and
    ``baseline_m`` the (positive) inter-camera distance of the calibrated front stereo. All values
    must be finite and positive. ``n_features``, ``row_tol_px``, and ``min_disparity_px`` control the
    ORB budget and the rectified-stereo acceptance gate; ``reprojection_px``/``min_pnp_inliers`` gate
    the temporal PnP solve.
    """

    fx_px: float
    fy_px: float
    cx_px: float
    cy_px: float
    baseline_m: float
    n_features: int = 4000
    row_tol_px: float = 2.0
    min_disparity_px: float = 1.0
    reprojection_px: float = 2.0
    min_pnp_inliers: int = 12
    reference_camera: str = "front_left"   # the frozen reference (I2); was read via __dict__ and
    # silently defaulted because the field did not exist (audit L56)

    def __post_init__(self) -> None:
        if self.reprojection_px <= 0 or self.min_pnp_inliers < 3:
            raise ValueError("reprojection_px must be > 0 and min_pnp_inliers >= 3 (audit L54)")
        scale = np.asarray([self.fx_px, self.fy_px, self.baseline_m], dtype=float)
        if not np.all(np.isfinite(scale)) or np.any(scale <= 0.0):
            raise ValueError("fx, fy, and baseline must be finite and positive")
        if not (np.isfinite(self.cx_px) and np.isfinite(self.cy_px)):
            raise ValueError("principal point must be finite")
        if self.n_features <= 0 or self.row_tol_px <= 0.0 or self.min_disparity_px <= 0.0:
            raise ValueError("feature budget and pixel gates must be positive")

    def matrix(self) -> np.ndarray:
        """The 3x3 camera intrinsic matrix K."""
        return np.array(
            [[self.fx_px, 0.0, self.cx_px], [0.0, self.fy_px, self.cy_px], [0.0, 0.0, 1.0]],
            dtype=float,
        )

    @classmethod
    def from_fov(
        cls,
        *,
        width_px: int,
        height_px: int,
        hfov_deg: float,
        baseline_m: float,
        **kwargs: float,
    ) -> StereoVOConfig:
        """Build the config with fx derived from the rig horizontal FOV (square pixels, centred
        principal point). fx = (W/2)/tan(HFOV/2); fy = fx; cx,cy = image centre."""
        intr = intrinsics_from_fov(width_px=width_px, height_px=height_px, hfov_deg=hfov_deg)
        return cls(
            fx_px=intr.fx, fy_px=intr.fy, cx_px=intr.cx, cy_px=intr.cy,
            baseline_m=baseline_m, **kwargs,  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class Intrinsics:
    """Pinhole intrinsics derived from a field of view."""

    fx: float
    fy: float
    cx: float
    cy: float

    def matrix(self) -> np.ndarray:
        return np.array([[self.fx, 0.0, self.cx], [0.0, self.fy, self.cy], [0.0, 0.0, 1.0]], dtype=float)


def intrinsics_from_fov(*, width_px: int, height_px: int, hfov_deg: float) -> Intrinsics:
    """Pinhole intrinsics from the horizontal FOV and image size. fx = (W/2)/tan(HFOV/2); square
    pixels (fy = fx); principal point at the image centre. This is the rig-FOV focal length the
    rendered frames were produced with (HFOV 73.99 deg -> fx ~= 254.84 px at 384 px width)."""
    if width_px <= 0 or height_px <= 0:
        raise ValueError("image dimensions must be positive")
    if not 0.0 < hfov_deg < 180.0:
        raise ValueError("hfov_deg must be in (0, 180)")
    fx = (width_px * 0.5) / math.tan(math.radians(hfov_deg) * 0.5)
    return Intrinsics(fx=fx, fy=fx, cx=width_px * 0.5, cy=height_px * 0.5)


@dataclass(frozen=True)
class StereoCloud:
    """A triangulated stereo frame. ``points_3d`` (N,3) are metres in the reference (left) camera
    optical frame (x right, y down, z forward); ``keypoints_px`` (N,2) are the reference-image pixel
    coordinates of each point; ``descriptors`` (N,D) are the matched reference ORB descriptors, kept
    aligned 1:1 with the points so the temporal PnP step can re-identify them. ``disparity_px`` (N,)
    is the (positive) horizontal disparity used per point."""

    points_3d: np.ndarray
    keypoints_px: np.ndarray
    descriptors: np.ndarray
    disparity_px: np.ndarray
    reference_camera: str = "front_left"


@dataclass(frozen=True)
class VOResult:
    """Visual-odometry result over a frame sequence. ``relative_translations_m`` is a list of (3,)
    inter-frame camera translations (metres, in the previous camera frame (audit L55: doc previously said 'moving')); ``relative_rotations`` the
    matching (3,3) rotations; ``trajectory_xyz_m`` (F,3) the accumulated camera centres starting at
    the origin; ``pnp_inliers`` the RANSAC inlier count per solve; ``stereo_point_counts`` the
    triangulated-point count per frame."""

    relative_translations_m: np.ndarray = field(default_factory=lambda: np.empty((0, 3)))
    relative_rotations: list[np.ndarray] = field(default_factory=list)
    trajectory_xyz_m: np.ndarray = field(default_factory=lambda: np.zeros((1, 3)))
    pnp_inliers: list[int] = field(default_factory=list)
    stereo_point_counts: list[int] = field(default_factory=list)


def _orb(n_features: int):
    return cv2.ORB_create(nfeatures=n_features)  # type: ignore[attr-defined]


def _detect(gray: np.ndarray, n_features: int):
    """ORB keypoints + descriptors on a gray image; returns (Nx2 px, NxD descriptors)."""
    det = _orb(n_features)
    kps, des = det.detectAndCompute(gray, None)
    if des is None or not kps:
        return np.empty((0, 2)), np.empty((0, 32), dtype=np.uint8)
    pts = np.array([k.pt for k in kps], dtype=float)
    return pts, des


def _mutual_match(des1: np.ndarray, des2: np.ndarray):
    """Mutual nearest-neighbour (cross-checked) Hamming matches between two ORB descriptor sets.
    Returns (query_idx, train_idx) integer arrays. Mirrors the matcher in
    :mod:`dart.features` (BFMatcher, NORM_HAMMING, crossCheck)."""
    if len(des1) == 0 or len(des2) == 0:
        return np.empty(0, dtype=int), np.empty(0, dtype=int)
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    matches = bf.match(des1, des2)
    q = np.array([m.queryIdx for m in matches], dtype=int)
    t = np.array([m.trainIdx for m in matches], dtype=int)
    return q, t


def disparity_to_depth(disparity_px: np.ndarray, *, fx_px: float, baseline_m: float) -> np.ndarray:
    """Metric depth from horizontal disparity: depth = fx*B/disparity (exact inverse of
    disparity = fx*B/depth). Non-positive disparities map to +inf (no finite depth)."""
    d = np.asarray(disparity_px, dtype=float)
    with np.errstate(divide="ignore"):
        return np.where(d > 0.0, fx_px * baseline_m / d, np.inf)


def triangulate_stereo(
    image_left: np.ndarray,
    image_right: np.ndarray,
    config: StereoVOConfig,
) -> StereoCloud:
    """Triangulate matched keypoints of a rectified stereo pair into a metric point cloud.

    Detects + mutual-NN matches ORB keypoints, keeps row-aligned correspondences (|dy| < row_tol),
    fixes the consensus disparity sign (the rendered rig's reference camera is image-left only up to
    a sign), and back-projects each surviving match with the rig intrinsics to a positive-depth 3D
    point in the reference (left) optical frame. Images only -- no truth field (invariant I3).
    """
    gl, gr = to_gray_u8(image_left), to_gray_u8(image_right)
    if gl.shape != gr.shape:
        raise ValueError("stereo images must have the same shape")
    ptsL, desL = _detect(gl, config.n_features)
    ptsR, desR = _detect(gr, config.n_features)
    q, t = _mutual_match(desL, desR)
    if q.size == 0:
        empty = np.empty((0, 3))
        return StereoCloud(empty, np.empty((0, 2)), np.empty((0, desL.shape[1] if len(desL) else 32),
                           dtype=np.uint8), np.empty(0))
    pl, pr = ptsL[q], ptsR[t]
    row_ok = np.abs(pl[:, 1] - pr[:, 1]) < config.row_tol_px
    signed = pl[:, 0] - pr[:, 0]
    if not np.any(row_ok):
        sign = 1.0
    else:
        sign = 1.0 if np.median(signed[row_ok]) >= 0.0 else -1.0
    disparity = sign * signed
    keep = row_ok & (disparity > config.min_disparity_px)
    pl, disparity, qkeep = pl[keep], disparity[keep], q[keep]
    depth = disparity_to_depth(disparity, fx_px=config.fx_px, baseline_m=config.baseline_m)
    x = (pl[:, 0] - config.cx_px) * depth / config.fx_px
    y = (pl[:, 1] - config.cy_px) * depth / config.fy_px
    points_3d = np.stack([x, y, depth], axis=1)
    return StereoCloud(
        points_3d=points_3d,
        keypoints_px=pl,
        descriptors=desL[qkeep],
        disparity_px=disparity,
        reference_camera=config.reference_camera,
    )


def _solve_pnp(object_pts: np.ndarray, image_pts: np.ndarray, K: np.ndarray, config: StereoVOConfig):
    """PnP-RANSAC: pose of the reference (prior) cloud in the current camera. Returns
    (R_3x3, t_3, n_inliers) or (None, None, 0) if it cannot fit a reliable pose."""
    if len(object_pts) < 6:
        return None, None, 0
    ok, rvec, tvec, inliers = cv2.solvePnPRansac(
        object_pts.reshape(-1, 1, 3).astype(np.float64),
        image_pts.reshape(-1, 1, 2).astype(np.float64),
        K, None,
        reprojectionError=config.reprojection_px,
        iterationsCount=300, confidence=0.999,
    )
    n_inl = 0 if inliers is None else int(len(inliers))
    if not ok or n_inl < config.min_pnp_inliers:
        return None, None, n_inl
    R, _ = cv2.Rodrigues(rvec)
    return R, tvec.reshape(3), n_inl


def estimate_vo(
    stereo_pairs: list[tuple[np.ndarray, np.ndarray]],
    config: StereoVOConfig,
) -> VOResult:
    """Stereo-PnP visual odometry over a sequence of stereo pairs.

    For each pair the reference frame is triangulated; consecutive frames are linked by matching the
    prior frame's 3D-bearing descriptors to the current frame's left keypoints and solving PnP. The
    PnP pose (R, t) places the prior cloud in the current camera, so the camera moved by
    ``-R^T t`` in its own frame; that is accumulated into a world trajectory. Images + calibration
    only -- no ground-truth field (invariant I3).
    """
    if len(stereo_pairs) < 2:
        raise ValueError("need at least two stereo pairs for visual odometry")
    K = config.matrix()
    clouds = [triangulate_stereo(left, right, config) for left, right in stereo_pairs]
    point_counts = [int(c.points_3d.shape[0]) for c in clouds]

    rel_t: list[np.ndarray] = []
    rel_R: list[np.ndarray] = []
    inliers: list[int] = []
    # accumulated camera pose in the world (first camera = world origin, identity orientation)
    R_wc = np.eye(3)
    t_wc = np.zeros(3)
    traj = [t_wc.copy()]

    for k in range(1, len(stereo_pairs)):
        prev = clouds[k - 1]
        cur_left = to_gray_u8(stereo_pairs[k][0])
        cur_pts, cur_des = _detect(cur_left, config.n_features)
        if len(prev.descriptors) == 0 or len(cur_des) == 0:
            R_rel, t_rel, n_inl = None, None, 0
        else:
            q, t = _mutual_match(prev.descriptors, cur_des)
            R_rel, t_rel, n_inl = _solve_pnp(prev.points_3d[q], cur_pts[t], K, config)
        inliers.append(n_inl)
        if R_rel is None or t_rel is None:
            # no reliable solve: hold pose, record a zero step (caller sees the low inlier count)
            rel_R.append(np.eye(3))
            rel_t.append(np.zeros(3))
            traj.append(t_wc.copy())
            continue
        # camera motion in the previous camera frame: c = -R_rel^T t_rel
        motion_prev = -R_rel.T @ t_rel
        rel_R.append(R_rel)
        rel_t.append(motion_prev)
        # compose into the world: new orientation R_wc' = R_wc @ R_rel^T; centre advances by R_wc @ motion
        t_wc = t_wc + R_wc @ motion_prev
        R_wc = R_wc @ R_rel.T
        traj.append(t_wc.copy())

    return VOResult(
        relative_translations_m=np.array(rel_t) if rel_t else np.empty((0, 3)),
        relative_rotations=rel_R,
        trajectory_xyz_m=np.array(traj),
        pnp_inliers=inliers,
        stereo_point_counts=point_counts,
    )


def save_trajectory_plot(result: VOResult, out_path: str) -> str:
    """Save a 2-panel PNG of the recovered VO trajectory: the camera path in the ground plane (x-z)
    and the per-step translation magnitude. Agg backend (no display). Returns the written path."""
    import os

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    traj = result.trajectory_xyz_m
    steps = np.linalg.norm(result.relative_translations_m, axis=1) if len(
        result.relative_translations_m
    ) else np.empty(0)

    fig, (ax0, ax1) = plt.subplots(1, 2, figsize=(11, 4.5))

    # ground-plane path: x (right) vs z (forward), the dominant drive axis
    ax0.plot(traj[:, 0], traj[:, 2], "-o", color="tab:blue", linewidth=1.5, markersize=5)
    for i, (px, pz) in enumerate(zip(traj[:, 0], traj[:, 2])):
        ax0.annotate(str(i), (px, pz), textcoords="offset points", xytext=(4, 4), fontsize=8)
    ax0.set_xlabel("x (m, camera-right)")
    ax0.set_ylabel("z (m, camera-forward)")
    ax0.set_title("Stereo-PnP VO trajectory (left-camera frame)")
    ax0.axis("equal")
    ax0.grid(True, alpha=0.3)

    # per-step translation magnitude
    if steps.size:
        idx = np.arange(1, steps.size + 1)
        ax1.bar(idx, steps, color="tab:green", alpha=0.8)
        ax1.axhline(float(np.mean(steps)), color="k", linestyle="--", linewidth=1,
                    label=f"mean {np.mean(steps):.3f} m")
        total = float(steps.sum())
        ax1.set_title(f"Inter-frame |t| (total path {total:.3f} m)")
        ax1.legend(fontsize=8)
    ax1.set_xlabel("frame step")
    ax1.set_ylabel("|t| (m)")
    ax1.grid(True, alpha=0.3)

    fig.suptitle("Visual odometry on REAL rendered lunar stereo traverse (frames 000..003)",
                 fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out_path
