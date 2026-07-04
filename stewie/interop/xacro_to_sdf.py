"""[REQ:BA-06] xacro -> SDF interop (part of the BA-06 converter set; container-gated).

A xacro robot description expands to URDF (`xacro`) and converts to Gazebo SDF (`gz sdf -p`). The faithful
round-trip invariant is NOT raw link count -- URDF->SDF correctly LUMPS fixed-joint links into their parent --
but the ARTICULATED degrees of freedom: the count of non-fixed joints is preserved (URDF non-fixed == SDF
joints) and the model name survives. Requires the ROS `xacro` + `gz` tools, so this runs in the on-host
ros2/gazebo container (stewie-ros2 / stewie-gazebo), not in the CPU-only CI -- its test skips cleanly there.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET

_NONFIXED = frozenset({"revolute", "continuous", "prismatic", "planar", "floating"})


class ToolMissingError(RuntimeError):
    """A required ROS tool (xacro / gz) is not on PATH -- run in the ros2/gazebo container."""


def _run(cmd: list[str]) -> str:
    if not shutil.which(cmd[0]):
        raise ToolMissingError(f"{cmd[0]!r} not found; run in the ros2/gazebo container")
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout


def xacro_to_urdf(xacro_path: str, mappings: dict[str, str] | None = None) -> str:
    """Expand a .urdf.xacro to a plain URDF string via the ROS `xacro` CLI."""
    args = ["xacro", xacro_path] + [f"{k}:={v}" for k, v in (mappings or {}).items()]
    return _run(args)


def urdf_string_to_sdf(urdf_xml: str) -> str:
    """Convert a URDF string to SDF via `gz sdf -p` (writes the URDF to a temp file gz can read)."""
    fd, path = tempfile.mkstemp(suffix=".urdf")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(urdf_xml)
        return _run(["gz", "sdf", "-p", path])
    finally:
        os.unlink(path)


def xacro_to_sdf(xacro_path: str, mappings: dict[str, str] | None = None) -> str:
    """xacro -> URDF -> SDF (the full container-gated conversion)."""
    return urdf_string_to_sdf(xacro_to_urdf(xacro_path, mappings))


def articulated_joint_count(robot_xml: str) -> int:
    """Count the non-fixed (articulated) joints in a URDF or SDF string -- the DOF preserved across the
    URDF->SDF fixed-joint lumping."""
    root = ET.fromstring(robot_xml)
    return sum(1 for j in root.iter("joint") if j.get("type") in _NONFIXED)
