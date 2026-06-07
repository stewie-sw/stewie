"""Bridge to dustgym across its frozen Seam-2 (sensor bridge) and the command seam.

solnav consumes dustgym read-only: it parses the Godot sidecar `sensors.json`
(cameras, intrinsics, extrinsics, stereo baselines, rover/lander pose, the Sun
block) and loads the per-camera PNGs, then writes `cmd_vel` and posture commands
back to a directory dustgym polls. No dustgym source is modified. The schema here
matches a real LAC-twin/dustgym sensors.json (schema fields: cameras[], stereo,
stereo_rear, sun, rover, lander, frame_index, frame_convention).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Optional

import numpy as np


@dataclass
class Camera:
    name: str
    image: str
    width: int
    height: int
    fx: float
    fy: float
    cx: float
    cy: float
    extrinsic_pos_m: np.ndarray            # in base_link
    extrinsic_quat_xyzw: np.ndarray
    frame_id: str = ""


@dataclass
class SensorFrame:
    """Estimator-facing sensor packet. Invariant I3 (spec line 326): rover/lander TRUTH poses are
    NOT fields here -- they live on a separate EvaluationTruthPacket read off an eval-only channel,
    so truth-ingress into the graph is a type error, not an accident (HIGH-08)."""
    frame_index: int
    cameras: list                          # list[Camera]
    stereo_baseline_m: Optional[float]
    stereo_pair: Optional[tuple]           # (left_name, right_name)
    sun_elevation_deg: Optional[float]     # ephemeris/scene parameter, not rover truth
    sun_azimuth_deg: Optional[float]
    raw: dict = field(default_factory=dict)

    def camera(self, name: str) -> Optional[Camera]:
        for c in self.cameras:
            if c.name == name:
                return c
        return None


@dataclass
class EvaluationTruthPacket:
    """Ground-truth poses for EVALUATION ONLY (ATE/RPE vs truth). Carries provenance so any code
    that lets this reach the estimator boundary can be rejected (the I3 leakage gate)."""
    frame_index: int
    rover_pos_m: np.ndarray
    rover_quat_xyzw: np.ndarray
    lander_pos_m: np.ndarray
    provenance: str = "GROUND_TRUTH_EVAL"


def read_sensors(sensors_json_path: str) -> SensorFrame:
    """Parse a real dustgym/LAC Seam-2 sensors.json into a typed (truth-free) SensorFrame."""
    with open(sensors_json_path) as f:
        d = json.load(f)
    cams = []
    for c in d.get("cameras", []):
        intr = c.get("intrinsics", {})
        ext = c.get("extrinsic_in_base_link", {})
        cams.append(Camera(
            name=c.get("name", c.get("frame_id", "")),
            image=c.get("image", ""),
            width=int(c.get("width", intr.get("cx", 0) * 2)),
            height=int(c.get("height", intr.get("cy", 0) * 2)),
            fx=float(intr.get("fx", 0.0)), fy=float(intr.get("fy", 0.0)),
            cx=float(intr.get("cx", 0.0)), cy=float(intr.get("cy", 0.0)),
            extrinsic_pos_m=np.array(ext.get("position_m", [0, 0, 0]), float),
            extrinsic_quat_xyzw=np.array(ext.get("quaternion_xyzw", [0, 0, 0, 1]), float),
            frame_id=c.get("frame_id", ""),
        ))
    st = d.get("stereo", {}) or {}
    sun = d.get("sun", {}) or {}
    return SensorFrame(
        frame_index=int(d.get("frame_index", 0)),
        cameras=cams,
        stereo_baseline_m=(float(st["baseline_m"]) if "baseline_m" in st else None),
        stereo_pair=((st.get("left"), st.get("right")) if st else None),
        sun_elevation_deg=(float(sun["elevation_deg"]) if "elevation_deg" in sun else None),
        sun_azimuth_deg=(float(sun["azimuth_deg"]) if "azimuth_deg" in sun else None),
        raw=d,
    )


def read_evaluation_truth(sensors_json_path: str) -> EvaluationTruthPacket:
    """Parse ONLY the ground-truth rover/lander poses, on the eval channel (never the estimator)."""
    with open(sensors_json_path) as f:
        d = json.load(f)
    rover = d.get("rover", {}) or {}
    lander = d.get("lander", {}) or {}
    return EvaluationTruthPacket(
        frame_index=int(d.get("frame_index", 0)),
        rover_pos_m=np.array(rover.get("position_m", [0, 0, 0]), float),
        rover_quat_xyzw=np.array(rover.get("quaternion_xyzw", [0, 0, 0, 1]), float),
        lander_pos_m=np.array(lander.get("position_m", [0, 0, 0]), float),
    )


def load_camera_image(sensors_json_path: str, camera_name: str) -> np.ndarray:
    """Load the grayscale PNG for a named camera, resolved next to sensors.json."""
    from imageio.v3 import imread
    frame = read_sensors(sensors_json_path)
    cam = frame.camera(camera_name)
    if cam is None or not cam.image:
        raise FileNotFoundError("camera %r not in %s" % (camera_name, sensors_json_path))
    img_path = os.path.join(os.path.dirname(sensors_json_path), cam.image)
    return np.asarray(imread(img_path))


def write_cmd_vel(out_dir: str, v_ms: float, omega_rads: float, frame_index: int) -> str:
    """Write a cmd_vel command (v, omega) for dustgym to poll. omega positive = CW."""
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "cmd_vel.json")
    with open(path, "w") as f:
        json.dump({"v_ms": float(v_ms), "omega_rads": float(omega_rads),
                   "frame_index": int(frame_index)}, f)
    return path


def write_posture_command(out_dir: str, arm_front_rad: float, arm_rear_rad: float,
                          posture: str = "", drum_front: float = 0.0,
                          drum_rear: float = 0.0) -> str:
    """Write an arm/posture command (arm angles in rad; drum speed signed,
    positive = excavating). posture is a label from the posture library."""
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "posture_cmd.json")
    with open(path, "w") as f:
        json.dump({"arm_front_rad": float(arm_front_rad),
                   "arm_rear_rad": float(arm_rear_rad),
                   "drum_front": float(drum_front), "drum_rear": float(drum_rear),
                   "posture": posture}, f)
    return path
