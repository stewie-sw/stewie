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

from ..config import SystemProfile, load_profile, validate_sensor_frame
from ..geometry import fov

_DEFAULT_PROFILE = load_profile("DUSTGYM_IPEX_V1")
IPEX_LAYOUT = [
    (c["name"], c["yaw_offset_deg"], c["role"], tuple(c["position_m"]))
    for c in _DEFAULT_PROFILE.cameras["entries"]
]
MAX_LIVE = int(_DEFAULT_PROFILE.cameras["max_live"])
STEREO_BASELINE_M = float(_DEFAULT_PROFILE.data["stereo"]["front"]["baseline_m"])


def godot_to_ros(p) -> np.ndarray:
    """Godot world (X horiz, Y up, Z horiz; cam looks -Z) -> ROS/REP-103 (X fwd, Y left, Z up):
    (x, y, z) -> (x, -z, y). The ground plane is then (x, -z)."""
    p = np.asarray(p, float)
    return np.array([p[0], -p[2], p[1]])


def _quat_yaw(deg) -> np.ndarray:
    """Default-rig orientation for a camera with body yaw `deg`: a Godot-Y rotation by (deg - 90),
    so that AFTER the F0 basis change in optical_axis the body view axis is [cos(deg), sin(deg), 0]
    (forward -> +X, left -> +Y, right -> -Y, rear -> -X). Matches cameras_seeing's yaw offsets."""
    t = np.radians(deg - 90.0) / 2.0
    return np.array([0.0, np.sin(t), 0.0, np.cos(t)])


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
    position_frame: str = "godot"
    axis_body: np.ndarray | None = None

    def optical_axis(self) -> np.ndarray:
        """Camera viewing direction in BODY (REP-103) frame. Algorithm F0 (spec sec3 lines 95-109):
        the source quaternion is Godot-world (camera looks local -Z); the Godot->ROS basis change is
        applied to the ORIENTATION as well as the position, so the body axis is
        godot_to_ros(R_godot @ [0,0,-1]). A forward camera yields ~[1,0,0] (REP-103 +X). Earlier this
        returned the raw Godot axis (HIGH-01/02: positions converted, orientations not)."""
        if self.axis_body is not None:
            axis = np.asarray(self.axis_body, dtype=float)
            return axis / np.linalg.norm(axis)
        if self.position_frame == "body":
            return quat_to_R(self.quat_xyzw) @ np.array([0.0, 0.0, -1.0])
        return godot_to_ros(quat_to_R(self.quat_xyzw) @ np.array([0.0, 0.0, -1.0]))

    def body_position(self) -> np.ndarray:
        if self.position_frame == "body":
            return np.asarray(self.pos_m, dtype=float)
        return godot_to_ros(self.pos_m)


class CameraRig:
    def __init__(self, cams=None, profile: str | SystemProfile | None = None):
        self.profile = profile if isinstance(profile, SystemProfile) else load_profile(profile)
        if cams is None:
            optics = self.profile.cameras["optics"]
            cams = []
            for c in self.profile.cameras["entries"]:
                quat = np.asarray(c.get("quaternion_xyzw", _quat_yaw(c["yaw_offset_deg"])), float)
                cams.append(Cam(
                    c["name"], float(c["yaw_offset_deg"]), c["role"],
                    np.asarray(c["position_m"], float), quat,
                    float(optics["fx_px"]), int(optics["width_px"]),
                    c["position_frame"], np.asarray(c["optical_axis_body"], float),
                ))
        self.cams = cams
        self._by = {c.name: c for c in self.cams}

    @classmethod
    def from_sensors(
        cls,
        sensors_json_path,
        profile: str | SystemProfile | None = None,
        *,
        validate_profile: bool = True,
    ):
        """Build from runtime extrinsics after checking they belong to the selected profile."""
        from ..bridge import dustgym_io
        selected = profile if isinstance(profile, SystemProfile) else load_profile(profile)
        frame = dustgym_io.read_sensors(sensors_json_path)
        if validate_profile:
            validate_sensor_frame(selected, frame)
        layout = {
            c["name"]: (float(c["yaw_offset_deg"]), c["role"])
            for c in selected.cameras["entries"]
        }
        cams = []
        for c in frame.cameras:
            y, r = layout.get(c.name, (0.0, "aux"))
            cams.append(Cam(c.name, y, r, np.asarray(c.extrinsic_pos_m, float),
                            np.asarray(c.extrinsic_quat_xyzw, float), c.fx or 679.57,
                            c.width or 1024, "godot"))
        return cls(cams, selected)

    def get(self, name) -> Cam:
        return self._by[name]

    def stereo_pairs(self):
        return [
            (pair["left"], pair["right"])
            for pair in self.profile.data["stereo"].values()
        ]

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
        off = self._by[name].body_position()[:2]
        c, s = np.cos(rover_yaw_rad), np.sin(rover_yaw_rad)
        return np.asarray(rover_xy, float) + np.array([c*off[0] - s*off[1], s*off[0] + c*off[1]])

    def select_active(self):
        chosen = [c for c in self.cams if c.role == "stereo_front"][:2]
        side = [c for c in self.cams if c.role == "side"][:1]
        drum = [c for c in self.cams if c.role == "drum"][:1]
        return (chosen + side + drum)[:int(self.profile.cameras["max_live"])]

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
    if t[0] < 0.0 or t[1] < 0.0:
        # the LINES cross behind a camera: a bearing observes FORWARD along its ray, so a negative
        # parameter is a phantom, not a landmark (audit 2026-06-09)
        raise ValueError("bearings diverge; intersection is behind a camera (no forward triangulation)")
    return pA + t[0] * dA


def horizontal_triangulation_sigma_m(baseline_m, range_m, sigma_deg):
    """Cross-range 1-sigma of horizontal parallax: sigma ~ range^2 * sigma_rad / baseline."""
    if baseline_m < 1e-9:
        return float("inf")
    return float(range_m ** 2 * np.radians(sigma_deg) / baseline_m)
