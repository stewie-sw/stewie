"""THE frame mapping: sim grid/world <-> REP-103 (B1.5). The only conversion site.

Sim conventions (terrain.gd:13 + the drive loop): grid pose (row, col, yaw) on a cell_m grid;
world gx = col*cell (REP-103 +x), gy = height (REP-103 +z), gz = row*cell. REP-103 y points LEFT,
and sim +row (world +gz) is the rover's right at yaw=0, so y = -row*cell. Yaw is CCW about +z in
both frames with yaw=0 facing +col; the identity holds by construction and is pinned by tests.

Every ROS-facing producer/consumer imports from here; no other module converts frames.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Rep103Pose:
    x: float
    y: float
    z: float
    quaternion_xyzw: tuple


def grid_pose_to_rep103(rc: tuple, yaw: float, *, cell_m: float,
                        height_m: float = 0.0) -> Rep103Pose:
    row, col = float(rc[0]), float(rc[1])
    qz, qw = math.sin(yaw / 2.0), math.cos(yaw / 2.0)
    return Rep103Pose(x=col * cell_m, y=-row * cell_m, z=float(height_m),
                      quaternion_xyzw=(0.0, 0.0, qz, qw))


def rep103_to_grid_pose(p: Rep103Pose, *, cell_m: float) -> tuple:
    yaw = 2.0 * math.atan2(p.quaternion_xyzw[2], p.quaternion_xyzw[3])
    return (-p.y / cell_m, p.x / cell_m), yaw


def twist_to_drive(*, linear_x: float, angular_z: float) -> tuple:
    """ROS geometry_msgs/Twist -> the drive loop's (v_ms, omega_rad_s). 1:1 by contract; finite-only."""
    if not (math.isfinite(linear_x) and math.isfinite(angular_z)):
        raise ValueError("twist must be finite")
    return float(linear_x), float(angular_z)
