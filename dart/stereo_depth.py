"""Real stereo depth from a rectified pair (cv2 SGBM). Part of the VO/landmark backbone.

On real low-sun, low-texture lunar imagery the valid-disparity fraction is honestly
low: this is the texture-starvation the dissertation's solar/shadow/landmark cues
exist to compensate for. Operates on declared rendered-sensor pairs.
"""
# PROVENANCE: SolNav dissertation (A. Storey) -- moved from solnav/perception/stereo_depth.py, 2026-06-09 (M2)
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class StereoCalibration:
    calibration_id: str
    reference_camera: str
    match_camera: str
    fx_px: float
    baseline_m: float
    disparity_sigma_px: float
    covariance_calibrated: bool
    development_evidence: tuple[str, ...] = ()
    heldout_evidence: tuple[str, ...] = ()

    def __post_init__(self):
        values = np.asarray([self.fx_px, self.baseline_m, self.disparity_sigma_px], dtype=float)
        if not np.all(np.isfinite(values)) or np.any(values <= 0.0):
            raise ValueError("stereo calibration scale and sigma must be finite and positive")
        if not self.calibration_id or not self.reference_camera or not self.match_camera:
            raise ValueError("stereo calibration identifiers must be populated")
        if self.reference_camera == self.match_camera:
            raise ValueError("stereo reference and match cameras must be distinct")
        if self.covariance_calibrated and (
            not self.development_evidence or not self.heldout_evidence
        ):
            raise ValueError("calibrated covariance requires development and held-out evidence")


@dataclass(frozen=True)
class DepthFrame:
    disparity_px: np.ndarray
    depth_m: np.ndarray
    sigma_depth_m: np.ndarray
    valid_mask: np.ndarray
    reference_camera: str
    match_camera: str
    calibration_id: str
    covariance_calibrated: bool
    rejection_reason: str = ""
    provenance: str = "RUNTIME_DERIVED"


def to_gray(img: np.ndarray) -> np.ndarray:
    if img.ndim == 3:
        return cv2.cvtColor(img[..., :3], cv2.COLOR_RGB2GRAY)
    return img


def _sgbm(L, R, num_disparities, block_size, min_disparity=0):
    sgbm = cv2.StereoSGBM_create(  # type: ignore[attr-defined]  # cv2 stubs lack this dynamic attr
        minDisparity=min_disparity, numDisparities=num_disparities, blockSize=block_size,
        P1=8 * block_size * block_size, P2=32 * block_size * block_size,
        uniquenessRatio=10, speckleWindowSize=100, speckleRange=2, disp12MaxDiff=1)
    return sgbm.compute(L, R).astype(np.float32) / 16.0


def calibrate_stereo_order(left: np.ndarray, right: np.ndarray,
                           num_disparities: int = 128, block_size: int = 7) -> str:
    """ONE-TIME diagnostic: return the validated image order ('normal' or 'swapped') for this rig
    by comparing valid-disparity fraction. Run once at calibration, then PERSIST the result and pass
    a fixed order to compute_disparity (invariant I2: constant reference camera per run)."""
    L, R = to_gray(left), to_gray(right)
    d = _sgbm(L, R, num_disparities, block_size)
    d_sw = _sgbm(R, L, num_disparities, block_size)
    return "swapped" if valid_fraction(d_sw) > valid_fraction(d) else "normal"


def compute_disparity(left: np.ndarray, right: np.ndarray,
                      num_disparities: int = 128, block_size: int = 7,
                      auto_order: bool = False, return_order: bool = False):
    """SGBM disparity (px), float32; <=0 = invalid. SGBM requires positive disparity, i.e. `left`
    truly image-left. Pass the cameras in the CALIBRATED order (run calibrate_stereo_order once).

    auto_order DEFAULTS TO FALSE (HIGH-04 / invariant I2): the production path must use a constant
    reference camera fixed from calibration, NOT pick the order per frame by maximizing valid
    disparity (spec line 896 forbids it). auto_order=True is a single-frame diagnostic convenience
    only; if the swap wins the disparity is referenced to the OTHER camera, so pass return_order=True
    and do not feed it into a fixed-left back-projection without checking `order`."""
    L, R = to_gray(left), to_gray(right)
    d = _sgbm(L, R, num_disparities, block_size)
    order = "normal"
    if auto_order:
        d_swapped = _sgbm(R, L, num_disparities, block_size)
        if valid_fraction(d_swapped) > valid_fraction(d):
            d, order = d_swapped, "swapped"
    return (d, order) if return_order else d


def valid_fraction(disparity: np.ndarray) -> float:
    return float(np.mean(disparity > 0))


def disparity_to_depth(disparity: np.ndarray, fx_px: float, baseline_m: float) -> np.ndarray:
    """Depth map (m); invalid disparity -> NaN."""
    d = disparity
    with np.errstate(divide="ignore"):
        z = np.where(d > 0, fx_px * baseline_m / d, np.nan)
    return z


def left_right_consistency(
    disparity_lr: np.ndarray,
    disparity_rl: np.ndarray,
    max_diff_px: float = 1.0,
) -> np.ndarray:
    """Return pixels satisfying d_lr(u) + d_rl(u-d_lr(u)) ~= 0.

    ``disparity_lr`` is referenced to the frozen left/reference camera. The
    reverse matcher is configured for negative disparities and is used only as
    a consistency check; it never changes the output reference frame.
    """

    if disparity_lr.shape != disparity_rl.shape or disparity_lr.ndim != 2:
        raise ValueError("left/right disparity arrays must have the same 2-D shape")
    if not np.isfinite(max_diff_px) or max_diff_px < 0.0:
        raise ValueError("max_diff_px must be finite and nonnegative")
    height, width = disparity_lr.shape
    rows, cols = np.indices((height, width))
    match_cols = np.rint(cols - disparity_lr).astype(int)
    in_bounds = (disparity_lr > 0.0) & (match_cols >= 0) & (match_cols < width)
    sampled = np.full_like(disparity_lr, np.nan, dtype=np.float32)
    sampled[in_bounds] = disparity_rl[rows[in_bounds], match_cols[in_bounds]]
    return in_bounds & (sampled < 0.0) & (np.abs(disparity_lr + sampled) <= max_diff_px)


def compute_depth_frame(
    reference_image: np.ndarray,
    match_image: np.ndarray,
    calibration: StereoCalibration,
    *,
    num_disparities: int = 128,
    block_size: int = 7,
    saturation_invalid: bool = False,
    lr_max_diff_px: float = 1.0,
    exclusion_mask: np.ndarray | None = None,
    require_calibrated_covariance: bool = False,
) -> DepthFrame:
    """Compute a fixed-reference disparity/depth frame with validity and sigma.

    The caller must pass images in the persisted calibration order. This
    function never swaps them. Covariance can be carried for development, but
    production factor construction may set ``require_calibrated_covariance`` to
    reject a calibration that lacks both development and held-out evidence.
    """

    if require_calibrated_covariance and not calibration.covariance_calibrated:
        raise ValueError("stereo covariance is not calibrated on development and held-out evidence")
    left = to_gray(reference_image)
    right = to_gray(match_image)
    if left.shape != right.shape or left.ndim != 2:
        raise ValueError("stereo images must have the same 2-D shape")
    disparity_lr = _sgbm(left, right, num_disparities, block_size, min_disparity=0)
    disparity_rl = _sgbm(
        right, left, num_disparities, block_size, min_disparity=-num_disparities
    )
    # OpenCV marks INVALID as (minDisparity-1) = -(num_disparities+1): NEGATIVE, so it slipped the
    # (sampled < 0) consistency gate whenever |d_lr + sentinel| <= max_diff (audit 2026-06-09).
    # Mask the sentinel to NaN -> NaN comparisons are False -> reverse-INVALID pixels are rejected.
    disparity_rl[disparity_rl < -float(num_disparities)] = np.nan
    valid = left_right_consistency(disparity_lr, disparity_rl, lr_max_diff_px)
    if saturation_invalid:
        # a disparity pinned at the search cap is NOT a measurement: deep-shadow/over-near pixels
        # saturate SYMMETRICALLY in both directions, so LR-consistency alone passes them (found by
        # the G2 geometric truth, 2026-06-10: a shadow blob "measured" at exactly fx*b/(N-1)).
        # OPT-IN to preserve the frozen 2026-06-07 gate behavior; the next gate revision should
        # enable it.
        valid &= (disparity_lr < 0.95 * float(num_disparities)) & (disparity_lr > 1.0)
        # the lower bound: d <= 0 is not a measurement either (negative depth); d in (0,1] px is
        # beyond-range ambiguity at >fx*b metres
    if exclusion_mask is not None:
        mask = np.asarray(exclusion_mask, dtype=bool)
        if mask.shape != valid.shape:
            raise ValueError("exclusion_mask shape must match the stereo images")
        valid &= ~mask
    depth = disparity_to_depth(disparity_lr, calibration.fx_px, calibration.baseline_m)
    sigma = np.full_like(depth, np.nan, dtype=np.float32)
    sigma[valid] = (
        calibration.fx_px
        * calibration.baseline_m
        * calibration.disparity_sigma_px
        / np.square(disparity_lr[valid])
    )
    depth = np.where(valid, depth, np.nan)
    reason = "" if np.any(valid) else "NO_LR_CONSISTENT_DISPARITY"
    return DepthFrame(
        disparity_px=disparity_lr,
        depth_m=depth,
        sigma_depth_m=sigma,
        valid_mask=valid,
        reference_camera=calibration.reference_camera,
        match_camera=calibration.match_camera,
        calibration_id=calibration.calibration_id,
        covariance_calibrated=calibration.covariance_calibrated,
        rejection_reason=reason,
    )


def depth_pointcloud(depth_m: np.ndarray, fx: float, fy: float, cx: float, cy: float,
                     stride: int = 4) -> np.ndarray:
    """Back-project a depth map to an (N,3) point cloud in the camera optical frame."""
    H, W = depth_m.shape
    vs, us = np.mgrid[0:H:stride, 0:W:stride]
    z = depth_m[::stride, ::stride]
    m = np.isfinite(z)
    x = (us[m] - cx) * z[m] / fx
    y = (vs[m] - cy) * z[m] / fy
    return np.stack([x, y, z[m]], axis=1)
