"""Real stereo depth from a rectified pair (cv2 SGBM). Part of the VO/landmark backbone.

On real low-sun, low-texture lunar imagery the valid-disparity fraction is honestly
low: this is the texture-starvation the dissertation's solar/shadow/landmark cues
exist to compensate for. Operates on declared rendered-sensor pairs.
"""
from __future__ import annotations

import cv2
import numpy as np


def to_gray(img: np.ndarray) -> np.ndarray:
    if img.ndim == 3:
        return cv2.cvtColor(img[..., :3], cv2.COLOR_RGB2GRAY)
    return img


def _sgbm(L, R, num_disparities, block_size):
    sgbm = cv2.StereoSGBM_create(  # type: ignore[attr-defined]  # cv2 stubs lack this dynamic attr
        minDisparity=0, numDisparities=num_disparities, blockSize=block_size,
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
