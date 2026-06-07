"""Camera field-of-view and lander/AprilTag visibility across rover yaw (A4).

Models the paper's tradeoff: a side camera tracks the distant lander, the front
stereo handles near hazards. For each rover heading we compute which cameras have
the lander tag inside their FOV and whether the tag is large enough (in pixels) to
detect. Real pinhole geometry; no fabricated detections.
"""
from __future__ import annotations

import numpy as np


def hfov_deg_from_intrinsics(width_px: float, fx_px: float) -> float:
    """Horizontal FOV from real intrinsics: 2*atan(W/2 / fx)."""
    return float(2.0 * np.degrees(np.arctan2(width_px / 2.0, fx_px)))


def hfov_deg_from_lens(focal_mm: float, sensor_width_mm: float) -> float:
    return float(2.0 * np.degrees(np.arctan2(sensor_width_mm / 2.0, focal_mm)))


def sensor_width_mm(n_pixels_w: float, pixel_um: float) -> float:
    return n_pixels_w * pixel_um / 1000.0


def tag_angular_size_px(tag_size_m: float, distance_m: float, fx_px: float) -> float:
    """Apparent tag edge length in pixels (pinhole): size/distance * fx."""
    return float(tag_size_m / max(distance_m, 1e-6) * fx_px)


def tag_detectable(tag_size_m: float, distance_m: float, fx_px: float,
                   min_edge_px: float = 10.0) -> bool:
    """tag36h11 detection needs roughly >= min_edge_px across the tag."""
    return tag_angular_size_px(tag_size_m, distance_m, fx_px) >= min_edge_px


def _wrap180(a):
    return (a + 180.0) % 360.0 - 180.0


def in_fov(lander_world_bearing_deg: float, rover_yaw_deg: float,
           cam_yaw_offset_deg: float, hfov_deg: float) -> bool:
    """Is the lander inside this camera's FOV at the given rover yaw?"""
    rel = _wrap180(lander_world_bearing_deg - (rover_yaw_deg + cam_yaw_offset_deg))
    return abs(rel) <= hfov_deg / 2.0


def yaw_sweep(lander_bearing_deg: float, lander_distance_m: float,
              cameras: dict, tag_size_m: float, fx_px: float,
              yaws_deg=None, min_edge_px: float = 10.0):
    """For each rover yaw, return the list of cameras that BOTH frame the lander tag
    and can detect it. cameras = {name: (yaw_offset_deg, hfov_deg)}."""
    if yaws_deg is None:
        yaws_deg = list(range(0, 360, 10))
    detect = tag_detectable(tag_size_m, lander_distance_m, fx_px, min_edge_px)
    out = {}
    for y in yaws_deg:
        vis = [name for name, (off, hf) in cameras.items()
               if in_fov(lander_bearing_deg, y, off, hf)]
        out[y] = {"cameras_framing": vis, "tag_detectable": detect,
                  "usable": vis if detect else []}
    return out
