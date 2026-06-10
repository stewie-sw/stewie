"""B1.5: the ONE frame mapping — sim grid/world <-> REP-103 (x fwd, y left, z up).

The sim world is Godot-style Y-up with gx = col*cell, gy = height, gz = row*cell (terrain.gd:13);
the drive loop's planar pose is (row, col, yaw) on the grid. REP-103 wants x forward / y left /
z up in metres. This module is the ONLY conversion site (grep-enforced by review); every ROS-facing
producer/consumer goes through it. Round-trip property tests pin both directions.
"""
import math

import numpy as np
import pytest

from stewie.bridge import frames as fr


def test_grid_pose_to_rep103_and_back_roundtrip():
    rng = np.random.default_rng(0)
    for _ in range(50):
        rc = (float(rng.uniform(0, 256)), float(rng.uniform(0, 256)))
        yaw = float(rng.uniform(-math.pi, math.pi))
        cell = 0.02
        p = fr.grid_pose_to_rep103(rc, yaw, cell_m=cell, height_m=0.1234)
        rc2, yaw2 = fr.rep103_to_grid_pose(p, cell_m=cell)
        assert abs(rc2[0] - rc[0]) < 1e-9 and abs(rc2[1] - rc[1]) < 1e-9
        assert abs((yaw2 - yaw + math.pi) % (2 * math.pi) - math.pi) < 1e-9
        assert p.z == pytest.approx(0.1234)


def test_axes_meaning_is_pinned():
    # grid +col is sim world +x (east in the site frame): REP-103 x must grow with col
    p0 = fr.grid_pose_to_rep103((10.0, 10.0), 0.0, cell_m=1.0)
    p1 = fr.grid_pose_to_rep103((10.0, 11.0), 0.0, cell_m=1.0)
    assert p1.x - p0.x == pytest.approx(1.0) and p1.y == pytest.approx(p0.y)
    # grid +row is sim world +z; REP-103 y is LEFT, so +row must be -y
    p2 = fr.grid_pose_to_rep103((11.0, 10.0), 0.0, cell_m=1.0)
    assert p2.y - p0.y == pytest.approx(-1.0)


def test_yaw_zero_faces_plus_col_and_quaternion_matches():
    p = fr.grid_pose_to_rep103((0.0, 0.0), 0.0, cell_m=1.0)
    qx, qy, qz, qw = p.quaternion_xyzw
    assert (qx, qy) == (0.0, 0.0)
    yaw = 2.0 * math.atan2(qz, qw)
    assert yaw == pytest.approx(0.0)
    p90 = fr.grid_pose_to_rep103((0.0, 0.0), math.pi / 2, cell_m=1.0)
    yaw90 = 2.0 * math.atan2(p90.quaternion_xyzw[2], p90.quaternion_xyzw[3])
    assert yaw90 == pytest.approx(math.pi / 2)


def test_twist_mapping():
    # ROS Twist (linear.x forward, angular.z ccw) -> the drive loop's (v, omega), 1:1 by contract
    v, om = fr.twist_to_drive(linear_x=0.25, angular_z=-0.3)
    assert (v, om) == (0.25, -0.3)
    with pytest.raises(ValueError):
        fr.twist_to_drive(linear_x=float("nan"), angular_z=0.0)
