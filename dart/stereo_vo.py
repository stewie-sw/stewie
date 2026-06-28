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
    triangulated-point count per frame.

    M-03 (2026-06-14): a FAILED PnP step is represented honestly as INVALID/MISSING, not zero motion.
    ``step_valid[k]`` is False for a step whose solve could not be trusted; for such a step
    ``relative_translations_m[k]`` is all-NaN (missing, not a fabricated zero vector), the
    corresponding rotation is NaN, and ``relative_covariances[k]`` is a hugely inflated 6x6 so any
    downstream fusion/mapping must skip it rather than place a cloud at the held pose. For a valid step
    the covariance is finite and scaled by the PnP inlier count (more inliers -> tighter). The
    accumulated ``trajectory_xyz_m`` HOLDS the last trusted pose across a gap (it cannot invent the
    missing motion), and ``trajectory_valid[k]`` marks which centres are anchored by an unbroken chain
    of trusted steps."""

    relative_translations_m: np.ndarray = field(default_factory=lambda: np.empty((0, 3)))
    relative_rotations: list[np.ndarray] = field(default_factory=list)
    trajectory_xyz_m: np.ndarray = field(default_factory=lambda: np.zeros((1, 3)))
    pnp_inliers: list[int] = field(default_factory=list)
    stereo_point_counts: list[int] = field(default_factory=list)
    step_valid: list[bool] = field(default_factory=list)
    relative_covariances: list[np.ndarray] = field(default_factory=list)
    trajectory_valid: list[bool] = field(default_factory=lambda: [True])


# A failed step's covariance: a near-singular-information (hugely inflated) 6x6 so any consumer that
# weights by information gives it ~zero weight and must skip it. Translation in m^2, rotation in rad^2.
_INVALID_STEP_COV = np.diag([1e12, 1e12, 1e12, 1e12, 1e12, 1e12]).astype(float)


def _valid_step_covariance(n_inliers: int) -> np.ndarray:
    """A finite 6x6 covariance for a trusted PnP step, scaled by the inlier count (more inliers ->
    tighter). Not a calibrated value: a monotone, finite, positive proxy so the relative weighting of
    a strong vs marginal solve is honest and a valid step is clearly distinguishable (diag << 1e6)
    from a failed one (diag >> 1e6). Floor at the min-inlier gate to keep it positive-definite."""
    n = max(int(n_inliers), 3)
    trans_var = 1.0 / n            # m^2, shrinks with inliers (e.g. 30 inliers -> ~0.033)
    rot_var = 0.25 / n             # rad^2
    return np.diag([trans_var, trans_var, trans_var, rot_var, rot_var, rot_var]).astype(float)


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


@dataclass(frozen=True)
class Rectification:
    """A rectifying homography pair recovered from a rigid stereo rig's own imagery.

    ``H_left``/``H_right`` (3x3) map the raw left/right images onto a row-aligned (epipolar-horizontal)
    pair so the ``row_tol_px`` gate in :func:`triangulate_stereo` no longer rejects valid disparities.
    ``n_inliers`` is the fundamental-matrix RANSAC inlier count the homographies were fit from, and
    ``residual_voffset_px`` is the post-rectification median |dy| over those inliers (the
    rectification-quality readout). Truth firewall I3: recovered from IMAGES ONLY -- no pose/truth."""

    H_left: np.ndarray
    H_right: np.ndarray
    n_inliers: int
    residual_voffset_px: float


def compute_self_rectification(
    stereo_pairs: list[tuple[np.ndarray, np.ndarray]],
    *,
    n_accum: int = 12,
    n_features: int = 4000,
    ransac_px: float = 1.0,
    confidence: float = 0.999,
) -> Rectification:
    """Recover a rectifying homography pair from a rigid stereo rig's OWN left/right imagery.

    Real unrectified stereo (e.g. the Katwijk LocCam Bumblebee2 pairs) carries a several-pixel vertical
    L-R offset, so the row-alignment gate in :func:`triangulate_stereo` (|dy| < ``row_tol_px``) rejects
    almost every correspondence and triangulation starves. Because the rig is rigid, ONE rectification
    computed from the epipolar geometry of accumulated L-R ORB inliers applies to every pair: detect +
    mutual-NN match ORB over the first ``n_accum`` frames, fit the fundamental matrix by RANSAC, and call
    ``cv2.stereoRectifyUncalibrated`` on the inliers to get (H_left, H_right). The returned
    ``residual_voffset_px`` reports the post-rectification median |dy| as the honest quality check.

    Truth firewall (invariant I3): only the left/right IMAGES are read -- no pose, slip, or any
    ground-truth field is ever an argument. Calibrated-baseline scale is unaffected (rectification is a
    pixel-domain alignment); the metric scale still comes from the rig baseline at triangulation time.
    """
    if len(stereo_pairs) < 1:
        raise ValueError("need at least one stereo pair to recover a rectification")
    accL: list[np.ndarray] = []
    accR: list[np.ndarray] = []
    for left, right in stereo_pairs[:n_accum]:
        gl, gr = to_gray_u8(left), to_gray_u8(right)
        if gl.shape != gr.shape:
            raise ValueError("stereo images must have the same shape")
        ptsL, desL = _detect(gl, n_features)
        ptsR, desR = _detect(gr, n_features)
        q, t = _mutual_match(desL, desR)
        if q.size:
            accL.append(ptsL[q])
            accR.append(ptsR[t])
    if not accL:
        raise ValueError("no L-R correspondences found; cannot self-rectify")
    L_pts = np.concatenate(accL).astype(np.float64)
    R_pts = np.concatenate(accR).astype(np.float64)
    F, mask = cv2.findFundamentalMat(L_pts, R_pts, cv2.FM_RANSAC, ransac_px, confidence)
    if F is None or mask is None:
        raise ValueError("fundamental-matrix fit failed; cannot self-rectify")
    inl = mask.ravel().astype(bool)
    Li, Ri = L_pts[inl], R_pts[inl]
    if len(Li) < 8:
        raise ValueError(f"too few F-inliers ({len(Li)}) to rectify reliably")
    h, w = to_gray_u8(stereo_pairs[0][0]).shape[:2]
    ok, H1, H2 = cv2.stereoRectifyUncalibrated(
        Li.reshape(-1, 1, 2), Ri.reshape(-1, 1, 2), F, (int(w), int(h)),
    )
    if not ok:
        raise ValueError("stereoRectifyUncalibrated failed")
    Lr = cv2.perspectiveTransform(Li.reshape(-1, 1, 2), H1).reshape(-1, 2)
    Rr = cv2.perspectiveTransform(Ri.reshape(-1, 1, 2), H2).reshape(-1, 2)
    resid = float(np.median(np.abs(Lr[:, 1] - Rr[:, 1])))
    return Rectification(H_left=np.asarray(H1, float), H_right=np.asarray(H2, float),
                         n_inliers=int(inl.sum()), residual_voffset_px=resid)


def apply_rectification(
    stereo_pairs: list[tuple[np.ndarray, np.ndarray]],
    rect: Rectification,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Warp every (left, right) pair by the recovered (H_left, H_right) into row-aligned gray pairs.

    Returns grayscale ``uint8`` pairs ready for :func:`estimate_vo`/:func:`triangulate_stereo` (which
    grayscale internally). Truth-free: a pure pixel-domain warp of the imagery."""
    out: list[tuple[np.ndarray, np.ndarray]] = []
    for left, right in stereo_pairs:
        gl, gr = to_gray_u8(left), to_gray_u8(right)
        h, w = gl.shape[:2]
        Lr = cv2.warpPerspective(gl, rect.H_left, (w, h))
        Rr = cv2.warpPerspective(gr, rect.H_right, (w, h))
        out.append((Lr, Rr))
    return out


def self_rectify_pairs(
    stereo_pairs: list[tuple[np.ndarray, np.ndarray]],
    **kwargs,
) -> tuple[list[tuple[np.ndarray, np.ndarray]], Rectification]:
    """Convenience: recover the rig rectification from the imagery and apply it to every pair.

    Returns ``(rectified_pairs, rectification)``. Truth firewall I3: images only. This is the front-end
    stage that makes :func:`estimate_vo` viable on REAL unrectified stereo (e.g. Katwijk LocCam)."""
    rect = compute_self_rectification(stereo_pairs, **kwargs)
    return apply_rectification(stereo_pairs, rect), rect


def calibrated_rectify_pairs(
    stereo_pairs: list[tuple[np.ndarray, np.ndarray]],
    *,
    K_left: np.ndarray,
    dist_left: np.ndarray,
    K_right: np.ndarray,
    dist_right: np.ndarray,
    R: np.ndarray,
    T_m: np.ndarray,
    alpha: float = 0.0,
) -> tuple[list[tuple[np.ndarray, np.ndarray]], "StereoVOConfig"]:
    """Rectify stereo pairs from the rig's MEASURED metric calibration (intrinsics + extrinsics).

    Unlike :func:`self_rectify_pairs` (which recovers a rectification from the imagery's epipolar
    geometry but leaves the rectified focal length arbitrary, so triangulating with a nominal fx is off
    by an unknown scale), this uses ``cv2.stereoRectify`` with the real per-camera matrices
    ``K_left``/``K_right``, distortion ``dist_left``/``dist_right``, and the inter-camera rotation ``R``
    + translation ``T_m`` (metres). The rectified projection matrices fix a COMMON, KNOWN focal length
    and baseline, so the returned :class:`StereoVOConfig` makes :func:`triangulate_stereo` METRIC.

    Truth firewall (invariant I3): the calibration is a CAMERA PROPERTY (intrinsics + the rigid stereo
    geometry), NOT a ground-truth pose -- no rover/world truth enters. Returns ``(rectified_gray_pairs,
    config)``; the config's fx/cx/cy/baseline are read off the rectified P matrices.
    """
    h, w = to_gray_u8(stereo_pairs[0][0]).shape[:2]
    Kl = np.asarray(K_left, float); Kr = np.asarray(K_right, float)
    dl = np.asarray(dist_left, float); dr = np.asarray(dist_right, float)
    Rm = np.asarray(R, float); Tm = np.asarray(T_m, float).reshape(3)
    R1, R2, P1, P2, _Q, _roi1, _roi2 = cv2.stereoRectify(
        Kl, dl, Kr, dr, (int(w), int(h)), Rm, Tm,
        flags=cv2.CALIB_ZERO_DISPARITY, alpha=float(alpha),
    )
    m1x, m1y = cv2.initUndistortRectifyMap(Kl, dl, R1, P1, (int(w), int(h)), cv2.CV_32FC1)
    m2x, m2y = cv2.initUndistortRectifyMap(Kr, dr, R2, P2, (int(w), int(h)), cv2.CV_32FC1)
    fx = float(P1[0, 0]); fy = float(P1[1, 1])
    cx = float(P1[0, 2]); cy = float(P1[1, 2])
    baseline = abs(float(-P2[0, 3] / P2[0, 0]))            # P2[0,3] = -fx * baseline
    config = StereoVOConfig(fx_px=fx, fy_px=fy, cx_px=cx, cy_px=cy, baseline_m=baseline)
    out: list[tuple[np.ndarray, np.ndarray]] = []
    for left, right in stereo_pairs:
        gl, gr = to_gray_u8(left), to_gray_u8(right)
        out.append((cv2.remap(gl, m1x, m1y, cv2.INTER_LINEAR),
                    cv2.remap(gr, m2x, m2y, cv2.INTER_LINEAR)))
    return out, config


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
    step_valid: list[bool] = []
    rel_cov: list[np.ndarray] = []
    # accumulated camera pose in the world (first camera = world origin, identity orientation)
    R_wc = np.eye(3)
    t_wc = np.zeros(3)
    traj = [t_wc.copy()]
    traj_valid = [True]          # frame 0 is the trusted anchor
    chain_trusted = True         # becomes False once a step fails (downstream centres are not anchored)

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
            # M-03: NO reliable solve. The relative transform is INVALID/MISSING -- NOT identity +
            # zero translation (a false 'stationary' measurement). Record NaN motion + NaN rotation +
            # an inflated covariance; the world pose HOLDS the last trusted centre (the missing motion
            # cannot be invented) and every centre from here on is flagged un-anchored.
            step_valid.append(False)
            rel_R.append(np.full((3, 3), np.nan))
            rel_t.append(np.full(3, np.nan))
            rel_cov.append(_INVALID_STEP_COV.copy())
            chain_trusted = False
            traj.append(t_wc.copy())          # hold the last trusted pose across the gap
            traj_valid.append(False)
            continue
        # camera motion in the previous camera frame: c = -R_rel^T t_rel
        motion_prev = -R_rel.T @ t_rel
        step_valid.append(True)
        rel_R.append(R_rel)
        rel_t.append(motion_prev)
        rel_cov.append(_valid_step_covariance(n_inl))
        # compose into the world: new orientation R_wc' = R_wc @ R_rel^T; centre advances by R_wc @ motion
        t_wc = t_wc + R_wc @ motion_prev
        R_wc = R_wc @ R_rel.T
        traj.append(t_wc.copy())
        traj_valid.append(chain_trusted)      # anchored only if no earlier step in the chain failed

    return VOResult(
        relative_translations_m=np.array(rel_t) if rel_t else np.empty((0, 3)),
        relative_rotations=rel_R,
        trajectory_xyz_m=np.array(traj),
        pnp_inliers=inliers,
        stereo_point_counts=point_counts,
        step_valid=step_valid,
        relative_covariances=rel_cov,
        trajectory_valid=traj_valid,
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
