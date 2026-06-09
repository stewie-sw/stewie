"""Kinematic wireframe skeleton of the rover for explanatory animations.

Builds 3D polylines (chassis box, 4 wheels, 2 arms, 4 bucket drums, ground) driven
by the real forward kinematics (chassis lift + pitch from arm angles). This is a
KINEMATIC SCHEMATIC: limb dimensions are the [CONFIRM] estimates in kinematics.py
(GLB-envelope-derived); the angle->lift relation is the FK model. Used to render
posture GIFs for presentations.

Body frame: x fore, y left, z up. Lengths in meters.
"""
from __future__ import annotations

import numpy as np

from . import kinematics as kin

BODY_LEN = kin.WHEELBASE_M
BODY_W = kin.TRACK_M
BODY_H = 0.18


def _rot_y(deg: float) -> np.ndarray:
    t = np.radians(deg)
    c, s = np.cos(t), np.sin(t)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def _box_edges(center, lx, ly, lz):
    cx, cy, cz = center
    xs = [-lx / 2, lx / 2]; ys = [-ly / 2, ly / 2]; zs = [-lz / 2, lz / 2]
    corners = np.array([[x, y, z] for x in xs for y in ys for z in zs])
    idx = [(0, 1), (0, 2), (0, 4), (1, 3), (1, 5), (2, 3), (2, 6),
           (3, 7), (4, 5), (4, 6), (5, 7), (6, 7)]
    return [np.array([corners[a], corners[b]]) + np.array([cx, cy, cz]) for a, b in idx]


def _ring(center, r, plane="xz", n=16):
    a = np.linspace(0, 2 * np.pi, n)
    if plane == "xz":
        pts = np.stack([r * np.cos(a), np.zeros(n), r * np.sin(a)], 1)
    else:
        pts = np.stack([np.zeros(n), r * np.cos(a), r * np.sin(a)], 1)
    return pts + np.array(center)


def rover_skeleton(arm_front_deg: float, arm_rear_deg: float):
    """Return (polylines, meta). polylines = list of (N,3) arrays in world coords."""
    ps = kin.forward_kinematics(arm_front_deg, arm_rear_deg)
    chassis_z = kin.WHEEL_RADIUS_M + ps.chassis_lift_m
    # FK pitch is nose-UP positive (kinematics.py), but R_y(+theta) rotates +x toward -z (nose DOWN)
    # in this x-fore/y-left/z-up frame -> negate so the render matches the FK (audit 2026-06-09)
    R = _rot_y(-ps.pitch_deg)
    polys = []

    # ground
    polys.append(np.array([[-1.0, 0, 0], [1.0, 0, 0]]))

    # chassis box (pitched, raised)
    for e in _box_edges((0, 0, 0), BODY_LEN, BODY_W, BODY_H):
        polys.append((e @ R.T) + np.array([0, 0, chassis_z]))

    # wheels at corners (rigid with chassis)
    for sx in (-1, 1):
        for sy in (-1, 1):
            c = np.array([sx * BODY_LEN / 2, sy * BODY_W / 2, -BODY_H / 2])
            c = (c @ R.T) + np.array([0, 0, chassis_z])
            polys.append(_ring(c, kin.WHEEL_RADIUS_M, "xz"))

    # arms + drums (front/rear pivots on the chassis; drum drops by L*sin(theta))
    for sx, ang in ((1, arm_front_deg), (-1, arm_rear_deg)):
        pivot = np.array([sx * BODY_LEN / 2, 0, 0])
        pivot = (pivot @ R.T) + np.array([0, 0, chassis_z])
        drop = kin.ARM_LENGTH_M * np.sin(np.radians(ang))
        reach = kin.ARM_LENGTH_M * np.cos(np.radians(ang))
        for sy in (-1, 1):
            drum = pivot + np.array([sx * reach, sy * BODY_W / 2, -drop])
            polys.append(np.array([pivot, drum]))                 # arm
            polys.append(_ring(drum, 0.08, "xz"))                 # drum

    meta = {"name": ps.name, "lift_m": ps.chassis_lift_m, "pitch_deg": ps.pitch_deg,
            "arm_front": arm_front_deg, "arm_rear": arm_rear_deg}
    return polys, meta
