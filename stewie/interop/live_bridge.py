"""#63 drive-in-Godot, increment 1a -- the persistent Godot render seam (the CONTROL half).

The realtime "drive-in-Godot" view (PRD RT-05) needs the render to run as a LONG-LIVED process, not
render.sh's one-shot spawn->render->quit. This module is the FastAPI (Python) side of the file-based
seam that the persistent Godot process polls, mirroring the established cmd_vel polled-dir pattern in
``stewie.physics.drive.poll_cmd_vel``::

    control seam (this file):   FastAPI  --control.json-->        persistent Godot   (pose/arms/sun/camera)
    frame  sink  (increment 2): Godot    --frames/*.png+latest-->  FastAPI MJPEG endpoint

Authority-driven, not Godot-physics: the conserved ``column_state`` stays the analysis tier; Godot
renders a VIEW of it. Nothing here fabricates a frame -- the frame sink is produced only by a real
Godot render, wired in a later increment.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path

# The 8 EZ-RASSOR/IPEx camera panes drive_controller.gd renders (its PANES const), plus "grid" = the
# 8-camera composite (the default drive view). The seam only accepts a camera the render can produce.
CAMERAS: tuple[str, ...] = (
    "grid",
    "front_left", "front_right", "left_mono", "drum_front_cam",
    "rear_left", "rear_right", "right_mono", "drum_back_cam",
)
CONTROL_FILENAME = "control.json"
LATEST_FILENAME = "latest.json"
FRAMES_SUBDIR = "frames"

_FINITE_FIELDS = (
    "pose_x", "pose_z", "pose_yaw",
    "arm_front_pitch", "arm_back_pitch",
    "sun_elev_deg", "sun_azim_deg",
)


@dataclass(frozen=True)
class ControlState:
    """One frame's render control: the driven rover pose + drum-arm posture + lighting + which camera.

    Grounded in drive_controller.gd's real state (``pose_x``/``pose_z``/``pose_yaw`` and the front/back
    arm pitch ``af``/``ab``). ``sun_elev_deg``/``sun_azim_deg`` drive the lighting the path-dependent
    perception failures depend on. ``seq`` is a monotonic frame counter so the Godot side names its frame
    sink to match and the consumer can tell when a new frame is ready.
    """

    seq: int
    pose_x: float
    pose_z: float
    pose_yaw: float
    arm_front_pitch: float
    arm_back_pitch: float
    sun_elev_deg: float
    sun_azim_deg: float
    camera: str = "grid"

    def __post_init__(self) -> None:
        for name in _FINITE_FIELDS:
            if not math.isfinite(float(getattr(self, name))):
                raise ValueError(f"{name} must be finite, got {getattr(self, name)!r}")
        if int(self.seq) < 0:
            raise ValueError(f"seq must be >= 0, got {self.seq!r}")
        if self.camera not in CAMERAS:
            raise ValueError(f"camera must be one of {CAMERAS}, got {self.camera!r}")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> ControlState:
        return cls(
            seq=int(d["seq"]),
            pose_x=float(d["pose_x"]),
            pose_z=float(d["pose_z"]),
            pose_yaw=float(d["pose_yaw"]),
            arm_front_pitch=float(d["arm_front_pitch"]),
            arm_back_pitch=float(d["arm_back_pitch"]),
            sun_elev_deg=float(d["sun_elev_deg"]),
            sun_azim_deg=float(d["sun_azim_deg"]),
            camera=str(d.get("camera", "grid")),
        )


def control_path(render_dir: str | os.PathLike) -> Path:
    return Path(render_dir) / CONTROL_FILENAME


def latest_pointer_path(render_dir: str | os.PathLike) -> Path:
    return Path(render_dir) / LATEST_FILENAME


def frame_sink_path(render_dir: str | os.PathLike, seq: int) -> Path:
    return Path(render_dir) / FRAMES_SUBDIR / f"frame_{int(seq):06d}.png"


def write_control(render_dir: str | os.PathLike, state: ControlState) -> Path:
    """Atomically write the control seam so the polling Godot process never reads a half-written file
    (write a sibling ``.tmp`` then ``os.replace`` -- atomic on POSIX). Returns the control.json path."""
    d = Path(render_dir)
    d.mkdir(parents=True, exist_ok=True)
    dst = control_path(d)
    tmp = dst.parent / (dst.name + ".tmp")
    tmp.write_text(json.dumps(state.to_dict(), sort_keys=True), encoding="utf-8")
    os.replace(tmp, dst)
    return dst


def read_control(render_dir: str | os.PathLike) -> ControlState | None:
    """Read the control seam. Missing / unreadable / malformed -> None (safe, like poll_cmd_vel's stop)."""
    try:
        d = json.loads(control_path(render_dir).read_text(encoding="utf-8"))
        return ControlState.from_dict(d)
    except (OSError, ValueError, KeyError, TypeError):
        return None
