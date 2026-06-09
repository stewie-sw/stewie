"""Stereo depth and triangulation (part of A4/A5 and the VO backbone).

Pinhole stereo: depth Z = fx * B / d, where fx is focal length in pixels, B the
baseline in meters, d the disparity in pixels. Posture changes (A3) give an extra
vertical baseline between a low (driving) and a raised (meerkat) view, widening
parallax for landmark triangulation. Real geometry, no fabricated values.
"""
from __future__ import annotations

import numpy as np


def depth_from_disparity(disparity_px, fx_px: float, baseline_m: float):
    """Z = fx * B / d. Accepts scalar or array disparity; non-positive disparity
    maps to +inf (no depth)."""
    d = np.asarray(disparity_px, dtype=float)
    with np.errstate(divide="ignore"):
        z = np.where(d > 0, fx_px * baseline_m / d, np.inf)
    return float(z) if np.ndim(disparity_px) == 0 else z


def disparity_from_depth(depth_m, fx_px: float, baseline_m: float):
    """d = fx * B / Z (inverse of depth_from_disparity)."""
    z = np.asarray(depth_m, dtype=float)
    with np.errstate(divide="ignore"):
        d = np.where(z > 0, fx_px * baseline_m / z, np.inf)
    return float(d) if np.ndim(depth_m) == 0 else d


def backproject(u_px: float, v_px: float, depth_m: float,
                fx: float, fy: float, cx: float, cy: float) -> np.ndarray:
    """Back-project a pixel + depth to a 3D point in the camera optical frame."""
    x = (u_px - cx) * depth_m / fx
    y = (v_px - cy) * depth_m / fy
    return np.array([x, y, depth_m])


def depth_uncertainty_m(depth_m: float, fx_px: float, baseline_m: float,
                        sigma_d_px: float) -> float:
    """Depth error grows with the square of range: sigma_Z = Z^2 * sigma_d / (fx*B)."""
    return float(depth_m ** 2 * sigma_d_px / (fx_px * baseline_m))


def vertical_parallax_baseline_m(height_low_m: float, height_raised_m: float) -> float:
    """Effective vertical baseline gained by imaging from a low pose and a raised
    (meerkat) pose; this is the parallax lever A3 provides for triangulation."""
    return abs(height_raised_m - height_low_m)


def triangulate_bearings(p1: np.ndarray, d1: np.ndarray,
                         p2: np.ndarray, d2: np.ndarray) -> np.ndarray:
    """Midpoint triangulation of a landmark from two camera centers p1, p2 with
    unit viewing directions d1, d2 (all in a common world frame). Returns the
    closest-approach midpoint of the two rays."""
    d1 = d1 / np.linalg.norm(d1)
    d2 = d2 / np.linalg.norm(d2)
    w0 = p1 - p2
    a = float(d1 @ d1); b = float(d1 @ d2); c = float(d2 @ d2)
    d = float(d1 @ w0); e = float(d2 @ w0)
    denom = a * c - b * b
    if abs(denom) < 1e-12:
        raise ValueError("degenerate (parallel) bearings; no triangulation")
    t1 = (b * e - c * d) / denom
    t2 = (a * e - b * d) / denom
    q1 = p1 + t1 * d1
    q2 = p2 + t2 * d2
    return 0.5 * (q1 + q2)


def world_point_from_stereo(u_px, v_px, disparity_px, fx, fy, cx, cy, baseline_m,
                            R_wc: np.ndarray, t_wc: np.ndarray) -> np.ndarray:
    """Stereo pixel -> world 3D point: back-project with depth Z=fx*B/d, then apply the
    (posture-dependent) camera-to-world pose. R_wc (3x3), t_wc (3,)."""
    Z = depth_from_disparity(disparity_px, fx, baseline_m)
    p_cam = backproject(u_px, v_px, Z, fx, fy, cx, cy)
    return R_wc @ p_cam + np.asarray(t_wc, float)


def ground_height_from_stereo(u_px, v_px, disparity_px, fx, fy, cx, cy, baseline_m,
                              R_wc: np.ndarray, t_wc: np.ndarray) -> float:
    """World height (z) of a stereo-observed ground point = z-component of the world point."""
    return float(world_point_from_stereo(u_px, v_px, disparity_px, fx, fy, cx, cy,
                                         baseline_m, R_wc, t_wc)[2])


def height_uncertainty_from_disparity(u_px, v_px, disparity_px, fx, fy, cx, cy,
                                      baseline_m, R_wc: np.ndarray, sigma_d_px: float) -> float:
    """1-sigma height error propagated from disparity noise through the projection and the
    camera pose: dheight/dd = R_wc[2,:] . (d p_cam/dZ) . (dZ/dd). Real differential."""
    if disparity_px <= 0:
        raise ValueError(f"disparity must be > 0 (got {disparity_px}); zero would divide by zero "
                         "(audit L01)")
    dZ_dd = -fx * baseline_m / (disparity_px ** 2)             # dZ/dd
    dpcam_dZ = np.array([(u_px - cx) / fx, (v_px - cy) / fy, 1.0])
    dheight_dd = float(np.asarray(R_wc)[2, :] @ dpcam_dZ * dZ_dd)
    return abs(dheight_dd * sigma_d_px)
