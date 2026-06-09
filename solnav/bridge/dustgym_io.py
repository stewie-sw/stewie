"""Strict Dustgym runtime/evaluation packet bridge.

The estimator reads ``runtime_sensors.json`` only. World truth is physically
separate in ``evaluation_truth.json`` and cannot appear in ``SensorFrame.raw``.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

import numpy as np

RUNTIME_SCHEMA = "sensor_bridge_runtime/1.0"
TRUTH_SCHEMA = "sensor_bridge_evaluation_truth/1.0"
_FORBIDDEN_RUNTIME_KEYS = {"rover", "lander", "camera_poses_in_world"}


class PacketValidationError(ValueError):
    """A packet violates the runtime/evaluation channel contract."""


@dataclass(frozen=True)
class Camera:
    name: str
    image: str
    width: int
    height: int
    fx: float
    fy: float
    cx: float
    cy: float
    extrinsic_pos_m: np.ndarray
    extrinsic_quat_xyzw: np.ndarray
    frame_id: str
    sample_id: str
    timestamp_s: float
    status: str


@dataclass(frozen=True)
class SensorFrame:
    """Estimator-facing, provenance-bearing, truth-free runtime packet."""

    frame_index: int
    timestamp_s: float
    profile_id: str
    profile_sha256: str
    calibration_id: str
    cameras: list[Camera]
    stereo_baseline_m: float
    stereo_pair: tuple[str, str]
    sun_elevation_deg: Optional[float]
    sun_azimuth_deg: Optional[float]
    availability: Mapping[str, Any]
    health: Mapping[str, Any]
    provenance: str = "RUNTIME_SENSOR"
    raw: dict[str, Any] = field(default_factory=dict)

    def camera(self, name: str) -> Optional[Camera]:
        return next((camera for camera in self.cameras if camera.name == name), None)


@dataclass(frozen=True)
class EvaluationTruthPacket:
    """Evaluation-only truth. This type is never accepted by runtime constructors."""

    frame_index: int
    timestamp_s: float
    rover_pos_m: np.ndarray
    rover_quat_xyzw: np.ndarray
    lander_pos_m: np.ndarray
    camera_poses_in_world: tuple[Mapping[str, Any], ...]
    provenance: str = "GROUND_TRUTH_EVAL"


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PacketValidationError(f"{label} must be an object")
    return value


def _required(data: Mapping[str, Any], key: str, label: str = "packet") -> Any:
    if key not in data:
        raise PacketValidationError(f"{label} missing required field {key!r}")
    return data[key]


def _finite(value: Any, label: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise PacketValidationError(f"{label} must be finite")
    return result


def _positive(value: Any, label: str) -> float:
    result = _finite(value, label)
    if result <= 0.0:
        raise PacketValidationError(f"{label} must be positive")
    return result


def _vector(value: Any, size: int, label: str) -> np.ndarray:
    result = np.asarray(value, dtype=float)
    if result.shape != (size,) or not np.all(np.isfinite(result)):
        raise PacketValidationError(f"{label} must be a finite {size}-vector")
    return result


def _read_json(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as stream:
        return _object(json.load(stream), os.path.basename(path))


def _validate_image(path: str, width: int, height: int) -> None:
    from imageio.v3 import improps

    if not os.path.isfile(path):
        raise PacketValidationError(f"camera image does not exist: {path}")
    shape = improps(path).shape
    if len(shape) < 2 or tuple(shape[:2]) != (height, width):
        raise PacketValidationError(
            f"camera image {path} shape {shape[:2]} does not match declared {(height, width)}"
        )


def read_sensors(sensors_json_path: str, *, validate_images: bool = True) -> SensorFrame:
    """Read and validate a canonical truth-free Dustgym runtime packet."""

    data = _read_json(sensors_json_path)
    if data.get("schema_version") != RUNTIME_SCHEMA:
        raise PacketValidationError(
            f"expected {RUNTIME_SCHEMA}; use runtime_sensors.json, not legacy sensors.json"
        )
    leaked = sorted(_FORBIDDEN_RUNTIME_KEYS.intersection(data))
    if leaked:
        raise PacketValidationError(f"runtime packet contains evaluation-only keys: {leaked}")

    def _scan(node, path=""):
        # NESTED exact-key truth scan (audit L70): the top-level-only check let a truth key ride in any
        # sub-dict. Exact key names (not substrings) so legitimate values are never false-rejected.
        if isinstance(node, dict):
            for k, v in node.items():
                if k in _FORBIDDEN_RUNTIME_KEYS:
                    raise PacketValidationError(f"evaluation-only key {k!r} nested at {path or '<root>'}")
                _scan(v, f"{path}.{k}" if path else k)
        elif isinstance(node, list):
            for j, v in enumerate(node):
                _scan(v, f"{path}[{j}]")
    _scan(data)
    if data.get("provenance") != "RUNTIME_SENSOR":
        raise PacketValidationError("runtime packet provenance must be RUNTIME_SENSOR")
    if data.get("frame_convention") != "godot":
        raise PacketValidationError("runtime frame_convention must be 'godot'")

    frame_index = int(_required(data, "frame_index"))
    timestamp_s = _finite(_required(data, "timestamp_s"), "timestamp_s")
    if frame_index < 0 or timestamp_s < 0.0:
        raise PacketValidationError("frame_index and timestamp_s must be nonnegative")

    profile_id = str(_required(data, "profile_id"))
    profile_sha256 = str(_required(data, "profile_sha256"))
    calibration_id = str(_required(data, "calibration_id"))
    if not profile_id or len(profile_sha256) != 64 or not calibration_id:
        raise PacketValidationError("profile ID/checksum and calibration ID must be populated")

    camera_docs = _required(data, "cameras")
    if not isinstance(camera_docs, list) or not camera_docs:
        raise PacketValidationError("cameras must be a non-empty array")
    cameras: list[Camera] = []
    names: set[str] = set()
    sample_ids: set[str] = set()
    directory = os.path.dirname(os.path.abspath(sensors_json_path))
    for index, value in enumerate(camera_docs):
        source = _object(value, f"cameras[{index}]")
        if "pose_in_world" in source:
            raise PacketValidationError(f"camera {index} leaks pose_in_world")
        intrinsics = _object(_required(source, "intrinsics", f"cameras[{index}]"), "intrinsics")
        extrinsic = _object(
            _required(source, "extrinsic_in_base_link", f"cameras[{index}]"), "extrinsic"
        )
        name = str(_required(source, "name", f"cameras[{index}]"))
        sample_id = str(_required(source, "sample_id", f"cameras[{index}]"))
        if not name or name in names:
            raise PacketValidationError(f"camera names must be non-empty and unique: {name!r}")
        if not sample_id or sample_id in sample_ids:
            raise PacketValidationError(f"camera sample IDs must be non-empty and unique: {sample_id!r}")
        names.add(name)
        sample_ids.add(sample_id)
        width = int(_required(source, "width", name))
        height = int(_required(source, "height", name))
        fx = _positive(_required(intrinsics, "fx", name), f"{name}.fx")
        fy = _positive(_required(intrinsics, "fy", name), f"{name}.fy")
        cx = _finite(_required(intrinsics, "cx", name), f"{name}.cx")
        cy = _finite(_required(intrinsics, "cy", name), f"{name}.cy")
        if width <= 0 or height <= 0 or not (0.0 <= cx < width) or not (0.0 <= cy < height):
            raise PacketValidationError(f"{name} has invalid image dimensions or principal point")
        camera_timestamp = _finite(_required(source, "timestamp_s", name), f"{name}.timestamp_s")
        if not math.isclose(camera_timestamp, timestamp_s, abs_tol=1e-9):
            raise PacketValidationError(f"{name} timestamp does not match packet timestamp")
        quaternion = _vector(
            _required(extrinsic, "quaternion_xyzw", name), 4, f"{name}.extrinsic quaternion"
        )
        if not math.isclose(float(np.linalg.norm(quaternion)), 1.0, rel_tol=1e-5, abs_tol=1e-5):
            raise PacketValidationError(f"{name} extrinsic quaternion is not normalized")
        image = str(_required(source, "image", name))
        if validate_images:
            _validate_image(os.path.join(directory, image), width, height)
        cameras.append(
            Camera(
                name=name,
                image=image,
                width=width,
                height=height,
                fx=fx,
                fy=fy,
                cx=cx,
                cy=cy,
                extrinsic_pos_m=_vector(
                    _required(extrinsic, "position_m", name), 3, f"{name}.extrinsic position"
                ),
                extrinsic_quat_xyzw=quaternion,
                frame_id=str(_required(source, "frame_id", name)),
                sample_id=sample_id,
                timestamp_s=camera_timestamp,
                status=str(_required(source, "status", name)),
            )
        )

    stereo = _object(_required(data, "stereo"), "stereo")
    left = str(_required(stereo, "left", "stereo"))
    right = str(_required(stereo, "right", "stereo"))
    if left == right or left not in names or right not in names:
        raise PacketValidationError("stereo reference/match cameras must be distinct emitted cameras")
    baseline = _positive(_required(stereo, "baseline_m", "stereo"), "stereo.baseline_m")
    sun = _object(data.get("sun", {}), "sun")
    availability = _object(_required(data, "availability"), "availability")
    for channel in ("imu", "wheel", "joints", "power"):
        state = _object(_required(availability, channel, "availability"), channel)
        if state.get("status") not in {"OK", "UNAVAILABLE", "STALE", "DROPPED"}:
            raise PacketValidationError(f"availability.{channel} has invalid status")
    health = _object(_required(data, "health"), "health")
    if health.get("status") not in {"OK", "DEGRADED", "FAILED"}:
        raise PacketValidationError("health.status is invalid")

    return SensorFrame(
        frame_index=frame_index,
        timestamp_s=timestamp_s,
        profile_id=profile_id,
        profile_sha256=profile_sha256,
        calibration_id=calibration_id,
        cameras=cameras,
        stereo_baseline_m=baseline,
        stereo_pair=(left, right),
        sun_elevation_deg=(
            _finite(sun["elevation_deg"], "sun.elevation_deg") if "elevation_deg" in sun else None
        ),
        sun_azimuth_deg=(
            _finite(sun["azimuth_deg"], "sun.azimuth_deg") if "azimuth_deg" in sun else None
        ),
        availability=availability,
        health=health,
        raw=data,
    )


def read_evaluation_truth(path: str) -> EvaluationTruthPacket:
    """Read the physically separate evaluation-only truth packet."""

    data = _read_json(path)
    if data.get("schema_version") != TRUTH_SCHEMA:
        raise PacketValidationError(f"expected {TRUTH_SCHEMA}")
    if data.get("provenance") != "GROUND_TRUTH_EVAL":
        raise PacketValidationError("truth packet provenance must be GROUND_TRUTH_EVAL")
    rover = _object(_required(data, "rover"), "rover")
    lander = _object(_required(data, "lander"), "lander")
    camera_poses = _required(data, "camera_poses_in_world")
    if not isinstance(camera_poses, list):
        raise PacketValidationError("camera_poses_in_world must be an array")
    return EvaluationTruthPacket(
        frame_index=int(_required(data, "frame_index")),
        timestamp_s=_finite(_required(data, "timestamp_s"), "timestamp_s"),
        rover_pos_m=_vector(_required(rover, "position_m", "rover"), 3, "rover.position_m"),
        rover_quat_xyzw=_vector(
            _required(rover, "quaternion_xyzw", "rover"), 4, "rover.quaternion_xyzw"
        ),
        lander_pos_m=_vector(_required(lander, "position_m", "lander"), 3, "lander.position_m"),
        camera_poses_in_world=tuple(_object(item, "camera pose") for item in camera_poses),
    )


def load_camera_image(sensors_json_path: str, camera_name: str) -> np.ndarray:
    """Load a named image after validating the runtime packet."""

    from imageio.v3 import imread

    frame = read_sensors(sensors_json_path)
    camera = frame.camera(camera_name)
    if camera is None:
        raise FileNotFoundError(f"camera {camera_name!r} not in {sensors_json_path}")
    return np.asarray(imread(os.path.join(os.path.dirname(sensors_json_path), camera.image)))


def _atomic_json_write(path: str, data: Mapping[str, Any]) -> str:
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".solnav-", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return path


def write_cmd_vel(out_dir: str, v_ms: float, omega_rads: float, frame_index: int) -> str:
    """Atomically write a Dustgym velocity command; angular velocity uses Dustgym's CW sign."""

    return _atomic_json_write(
        os.path.join(out_dir, "cmd_vel.json"),
        {"v_ms": float(v_ms), "omega_rads": float(omega_rads), "frame_index": int(frame_index)},
    )


def write_posture_command(
    out_dir: str,
    arm_front_rad: float,
    arm_rear_rad: float,
    posture: str = "",
    drum_front: float = 0.0,
    drum_rear: float = 0.0,
) -> str:
    """Atomically write a posture command after higher-level safety gating."""

    return _atomic_json_write(
        os.path.join(out_dir, "posture_cmd.json"),
        {
            "arm_front_rad": float(arm_front_rad),
            "arm_rear_rad": float(arm_rear_rad),
            "drum_front": float(drum_front),
            "drum_rear": float(drum_rear),
            "posture": posture,
        },
    )
