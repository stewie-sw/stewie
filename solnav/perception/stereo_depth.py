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


def compute_disparity(left: np.ndarray, right: np.ndarray,
                      num_disparities: int = 128, block_size: int = 7,
                      auto_order: bool = True, return_order: bool = False):
    """SGBM disparity (px), float32; <=0 = invalid. SGBM requires positive disparity, i.e.
    `left` truly image-left. The dustgym Godot rig is left-handed in Z, so the committed
    (front_left, front_right) naming is image-REVERSED; passing it raw collapses validity to
    ~7%. With auto_order=True we try both orderings and keep the denser one.

    REFERENCE-FRAME CAVEAT (audit R4): if the swap wins, the disparity is referenced to the
    OTHER camera. So depth/back-projection must use the matching reference. Pass
    return_order=True to get (disparity, order) where order is 'normal' or 'swapped'; do not
    feed an auto-ordered disparity into a fixed-left back-projection without checking `order`.
    Production: rectify from the exact extrinsics and verify the disparity sign on a known
    3-D point, then fix the order from calibration (auto_order=False)."""
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
