"""The IPEx 8-camera rig with EXACT extrinsics, inter-camera baselines/angles, and
horizontal-parallax triangulation (A4).

Each camera is positioned exactly where it sits on the rover (position + orientation in
base_link, loaded from a real sensors.json when available). From those exact extrinsics we
compute the baseline (distance) between any two cameras and the angle between their optical
axes -- the geometry that sets every multi-camera triangulation's parallax. Real geometry;
no fabricated values.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..geometry import fov

# Default IPEx layout: (name, yaw offset deg, role, position [x,y,z] m in base_link).
# Positions are [CONFIRM] approximations from the RASSOR/IPEx envelope; from_sensors() loads
# the exact ones. front stereo +/-0.035 m in z (the 0.07 m baseline), rear at -0.3 m x.
IPEX_LAYOUT = [
    ("front_left", 0.0, "stereo_front", (0.30, -0.10, 0.035)),
    ("front_right", 0.0, "stereo_front", (0.30, -0.10, -0.035)),
    ("rear_left", 180.0, "stereo_rear", (-0.30, -0.10, 0.035)),
    ("rear_right", 180.0, "stereo_rear", (-0.30, -0.10, -0.035)),
    ("left_mono", 90.0, "side", (0.0, 0.25, 0.05)),
    ("right_mono", -90.0, "side", (0.0, -0.25, 0.05)),
    ("drum_front_cam", 0.0, "drum", (0.35, 0.0, -0.10)),
    ("drum_back_cam", 180.0, "drum", (-0.35, 0.0, -0.10)),
]
MAX_LIVE = 4
STEREO_BASELINE_M = 0.07


def godot_to_ros(p) -> np.ndarray:
    """Godot world (X horiz, Y up, Z horiz; cam looks -Z) -> ROS/REP-103 (X fwd, Y left, Z up):
    (x, y, z) -> (x, -z, y). The ground plane is then (x, -z)."""
    p = np.asarray(p, float)
    return np.array([p[0], -p[2], p[1]])


def quat_to_R(q_xyzw) -> np.ndarray:
    x, y, z, w = q_xyzw
    n = (x*x + y*y + z*z + w*w) ** 0.5
    if n < 1e-12:
        return np.eye(3)
    x, y, z, w = x/n, y/n, z/n, w/n
    return np.array([
        [1 - 2*(y*y + z*z), 2*(x*y - z*w),     2*(x*z + y*w)],
        [2*(x*y + z*w),     1 - 2*(x*x + z*z), 2*(y*z - x*w)],
        [2*(x*z - y*w),     2*(y*z + x*w),     1 - 2*(x*x + y*y)],
    ])


@dataclass
class Cam:
    name: str
    yaw_offset_deg: float
    role: str
    pos_m: np.ndarray = field(default_factory=lambda: np.zeros(3))
    quat_xyzw: np.ndarray = field(default_factory=lambda: np.array([0., 0., 0., 1.]))
    fx: float = 679.57
    width: int = 1024

    def optical_axis(self) -> np.ndarray:
        """Camera viewing direction in base_link, from the exact orientation. Godot cameras
        look down local -Z (sensor-bridge contract), so the view axis is R @ [0,0,-1]."""
        return quat_to_R(self.quat_xyzw) @ np.array([0.0, 0.0, -1.0])


class CameraRig:
    def __init__(self, cams=None):
        self.cams = cams or [Cam(n, y, r, np.array(p)) for (n, y, r, p) in IPEX_LAYOUT]
        self._by = {c.name: c for c in self.cams}

    @classmethod
    def from_sensors(cls, sensors_json_path):
        """Build the rig with EXACT per-camera extrinsics from a real sensors.json."""
        from ..bridge import dustgym_io
        frame = dustgym_io.read_sensors(sensors_json_path)
        layout = {n: (y, r) for (n, y, r, _) in IPEX_LAYOUT}
        cams = []
        for c in frame.cameras:
            y, r = layout.get(c.name, (0.0, "aux"))
            cams.append(Cam(c.name, y, r, np.asarray(c.extrinsic_pos_m, float),
                            np.asarray(c.extrinsic_quat_xyzw, float), c.fx or 679.57, c.width or 1024))
        return cls(cams)

    def get(self, name) -> Cam:
        return self._by[name]

    def stereo_pairs(self):
        return [("front_left", "front_right"), ("rear_left", "rear_right")]

    def baseline_m(self, name_a, name_b) -> float:
        """Exact distance between two camera mounts (the parallax baseline they provide)."""
        return float(np.linalg.norm(self._by[name_a].pos_m - self._by[name_b].pos_m))

    def axis_angle_deg(self, name_a, name_b) -> float:
        """Angle between two cameras' optical axes (deg)."""
        a, b = self._by[name_a].optical_axis(), self._by[name_b].optical_axis()
        c = float(np.clip(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)), -1, 1))
        return float(np.degrees(np.arccos(c)))

    def camera_world_xy(self, name, rover_yaw_rad, rover_xy=(0.0, 0.0)):
        """Exact world xy of a camera given the rover pose. The mount offset is converted
        Godot->ROS first (ground plane = (x, -z)), NOT the raw Godot (x, y); otherwise both
        stereo cameras and both side cameras collapse to one planar point. Then rotated by
        rover yaw and translated."""
        off = godot_to_ros(self._by[name].pos_m)[:2]      # (x, -z) ground offset
        c, s = np.cos(rover_yaw_rad), np.sin(rover_yaw_rad)
        return np.asarray(rover_xy, float) + np.array([c*off[0] - s*off[1], s*off[0] + c*off[1]])

    def select_active(self):
        chosen = [c for c in self.cams if c.role == "stereo_front"][:2]
        side = [c for c in self.cams if c.role == "side"][:1]
        drum = [c for c in self.cams if c.role == "drum"][:1]
        return (chosen + side + drum)[:MAX_LIVE]

    def cameras_seeing(self, world_bearing_deg, rover_yaw_deg, distance_m, tag_size_m=0.15):
        det = fov.tag_detectable(tag_size_m, distance_m, self.cams[0].fx)
        out = []
        for c in self.select_active():
            hf = fov.hfov_deg_from_intrinsics(c.width, c.fx)
            if fov.in_fov(world_bearing_deg, rover_yaw_deg, c.yaw_offset_deg, hf) and det:
                out.append(c.name)
        return out


def horizontal_parallax_triangulate(pA_xy, bearingA_world_deg, pB_xy, bearingB_world_deg):
    """Intersect two world-bearing rays from horizontally-separated centers pA, pB."""
    pA = np.asarray(pA_xy, float); pB = np.asarray(pB_xy, float)
    a, b = np.radians(bearingA_world_deg), np.radians(bearingB_world_deg)
    dA = np.array([np.cos(a), np.sin(a)]); dB = np.array([np.cos(b), np.sin(b)])
    M = np.array([[dA[0], -dB[0]], [dA[1], -dB[1]]])
    if abs(np.linalg.det(M)) < 1e-9:
        raise ValueError("near-parallel bearings; no horizontal triangulation")
    t = np.linalg.solve(M, pB - pA)
    return pA + t[0] * dA


def horizontal_triangulation_sigma_m(baseline_m, range_m, sigma_deg):
    """Cross-range 1-sigma of horizontal parallax: sigma ~ range^2 * sigma_rad / baseline."""
    if baseline_m < 1e-9:
        return float("inf")
    return float(range_m ** 2 * np.radians(sigma_deg) / baseline_m)
