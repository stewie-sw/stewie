"""VT-10: posture-dependent camera extrinsics DERIVED from vehicle geometry + arm state.

The runtime render side (Godot ``camera_rig.gd``) WRITES each frame's extrinsics into
``runtime_sensors.json``; this module DERIVES the same per-camera pose (position + orientation, in
the ``base_link`` body frame) on the twin/estimator side directly from the vehicle's camera rig and
the current arm posture -- so the twin can predict, and the estimator can recover, a camera's viewpoint
from proprioception alone (measured joint angles), for every image, with NO render in the loop.

The load-bearing VT-10 behavior: an ARM-mounted camera (the LAC "one camera per front/back arm") moves
with the arm -- command a Meerkat raise and its position AND look pitch up -- while a CHASSIS-mounted
camera (front/rear stereo pairs, side monoculars) is rigid to the body and does NOT move with the arm.

Nothing here is re-derived. The eight mounts are the sourced IPEx/LAC-twin rig
(``posture_kinematics.CAMERA_MOUNTS``, itself transcribed from ``godot_sidecar/camera_rig.gd`` +
the EZ-RASSOR URDF ``camera_front_joint``); the arm-camera motion COMPOSES
``arm_state.ArmState.drum_cam_offset_m`` (the rigid pivot->drum link -- "command the arm, the camera
viewpoint moves"); the chassis look directions are the render contract's own ``look`` vectors. The
ONLY new modeling choice is the arm-camera OPTICAL AXIS: the camera is taken rigidly fixed to the arm
link, so its optical forward is the arm's outward (pivot->drum) direction -- horizontal outward at
stow, pitched up by the arm angle under Meerkat. The exact flight mounting angle on the arm is the
gated Q tier (``[ASSUMPTION]``, like the rest of ``arm_state``'s posture geometry); the RELATIVE
behavior (the arm camera's pose tracks the arm) is the truth VT-10 asks for.

Frame convention (matches ``posture_kinematics.CAMERA_MOUNTS`` and ``camera_rig.gd`` §3): ``base_link``
right-handed, forward ``+X``, up ``+Y``, lateral ``+Z``; a camera looks along its own ``-Z`` (the Godot
optical convention), up ``+Y``, right ``+X``, so ``quaternion_xyzw`` rotates a camera-frame vector into
``base_link`` and ``rotate_vector(quaternion_xyzw, (0, 0, -1)) == optical_forward`` by construction.
"""
# PROVENANCE: STEWIE DART subsystem (A. Storey)
from __future__ import annotations

import math
from dataclasses import dataclass

from stewie.physics.posture_kinematics import CAMERA_MOUNTS
from stewie.specs.arm_joint import ArmJointState
from stewie.specs.arm_state import ARM_ORIGIN_BACK, ARM_ORIGIN_FRONT, ArmState
from stewie.specs.vehicles import DEFAULT_VEHICLE, get_vehicle

Vec3 = tuple[float, float, float]
Quat = tuple[float, float, float, float]

_EPS = 1e-12

#: the two arm-mounted cameras -> which `arm_state` arm each rides on ("front"/"back" per
#: `drum_cam_offset_m`). Every other camera in the rig is rigid to the chassis.
ARM_OF_CAMERA: dict[str, str] = {"drum_front_cam": "front", "drum_back_cam": "back"}

#: chassis-camera optical-forward directions in base_link -- transcribed verbatim from the render
#: contract's `look` table (`camera_rig.gd` CAMERAS): the front stereo pair looks forward (+X), the
#: rear pair backward (-X), the side monoculars straight out their side (+Z left / -Z right).
CHASSIS_LOOK: dict[str, Vec3] = {
    "front_left": (1.0, 0.0, 0.0),
    "front_right": (1.0, 0.0, 0.0),
    "rear_left": (-1.0, 0.0, 0.0),
    "rear_right": (-1.0, 0.0, 0.0),
    "left_mono": (0.0, 0.0, 1.0),
    "right_mono": (0.0, 0.0, -1.0),
}

#: the full IPEx/LAC-twin rig: the eight sourced mounts (`CAMERA_MOUNTS`), split into the six
#: chassis-rigid cameras and the two arm-mounted cameras.
CAMERAS: tuple[str, ...] = tuple(sorted(CAMERA_MOUNTS))
ARM_CAMERAS: tuple[str, ...] = tuple(sorted(ARM_OF_CAMERA))
CHASSIS_CAMERAS: tuple[str, ...] = tuple(sorted(CHASSIS_LOOK))


@dataclass(frozen=True)
class CameraExtrinsic:
    """A camera's DERIVED extrinsic pose in the ``base_link`` body frame.

    ``position_m`` is the camera origin (forward, up, lateral) [m]; ``quaternion_xyzw`` is the
    normalized orientation of the camera optical frame in ``base_link`` (same representation the
    runtime bridge ``sensor_io.Camera`` carries); ``optical_forward`` is the unit direction the
    camera looks (``quaternion_xyzw`` applied to ``(0, 0, -1)``), stored for legibility. ``mount`` is
    ``"arm"`` (pose tracks the arm) or ``"chassis"`` (pose rigid to the body)."""
    name: str
    mount: str
    position_m: Vec3
    quaternion_xyzw: Quat
    optical_forward: Vec3


# ---- small vector / quaternion helpers (pure, no numpy -- matches arm_state/vehicles house style) --
def _normalize3(v: Vec3) -> Vec3:
    n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if n < _EPS:
        raise ValueError(f"cannot normalize a near-zero vector {v}")
    return (v[0] / n, v[1] / n, v[2] / n)


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _dot3(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _look_columns(forward: Vec3) -> tuple[Vec3, Vec3, Vec3]:
    """Camera-frame basis columns (right, up, back) in base_link for a camera looking along
    ``forward`` with up ``~+Y`` (the gluLookAt construction; camera +Z is the backward axis). The up
    hint swaps to +X when the look is (near) vertical so the cross product stays well-conditioned --
    this is what keeps an arm camera valid through the vertical MEERKAT/IRON_CROSS raise."""
    f = _normalize3(forward)
    up_hint: Vec3 = (0.0, 1.0, 0.0)
    if abs(_dot3(f, up_hint)) > 0.999:
        up_hint = (1.0, 0.0, 0.0)
    back = (-f[0], -f[1], -f[2])                 # camera +Z points away from the look direction
    right = _normalize3(_cross(up_hint, back))
    up = _cross(back, right)                     # already unit (back, right orthonormal)
    return right, up, back


def _quat_from_columns(right: Vec3, up: Vec3, back: Vec3) -> Quat:
    """Unit ``(x, y, z, w)`` for the rotation whose columns are (right, up, back) -- Shepperd's
    numerically-stable branch selection over the matrix trace."""
    m00, m10, m20 = right
    m01, m11, m21 = up
    m02, m12, m22 = back
    trace = m00 + m11 + m22
    if trace > 0.0:
        s = math.sqrt(trace + 1.0) * 2.0
        w, x, y, z = 0.25 * s, (m21 - m12) / s, (m02 - m20) / s, (m10 - m01) / s
    elif m00 > m11 and m00 > m22:
        s = math.sqrt(1.0 + m00 - m11 - m22) * 2.0
        w, x, y, z = (m21 - m12) / s, 0.25 * s, (m01 + m10) / s, (m02 + m20) / s
    elif m11 > m22:
        s = math.sqrt(1.0 + m11 - m00 - m22) * 2.0
        w, x, y, z = (m02 - m20) / s, (m01 + m10) / s, 0.25 * s, (m12 + m21) / s
    else:
        s = math.sqrt(1.0 + m22 - m00 - m11) * 2.0
        w, x, y, z = (m10 - m01) / s, (m02 + m20) / s, (m12 + m21) / s, 0.25 * s
    n = math.sqrt(x * x + y * y + z * z + w * w)
    return (x / n, y / n, z / n, w / n)


def rotate_vector(quaternion_xyzw: Quat, v: Vec3) -> Vec3:
    """Rotate ``v`` by the unit quaternion ``(x, y, z, w)`` (active rotation, same sense the extrinsic
    encodes): ``v' = v + 2w(q x v) + 2 q x (q x v)``."""
    x, y, z, w = quaternion_xyzw
    q: Vec3 = (x, y, z)
    t = _cross(q, v)
    t = (2.0 * t[0], 2.0 * t[1], 2.0 * t[2])
    qt = _cross(q, t)
    return (v[0] + w * t[0] + qt[0], v[1] + w * t[1] + qt[1], v[2] + w * t[2] + qt[2])


def _arm_angles(arm: ArmState | tuple[ArmJointState, ArmJointState]) -> tuple[float, float]:
    """(front_deg, rear_deg) from either an ``ArmState`` (front_deg/back_deg) or a VT-03
    ``(front, rear)`` ``ArmJointState`` pair (matched by joint id, order-independent)."""
    if isinstance(arm, ArmState):
        return arm.front_deg, arm.back_deg
    by_joint = {j.joint: j for j in arm}
    if set(by_joint) != {"front", "rear"}:
        raise ValueError(f"an ArmJointState pair must be one 'front' and one 'rear' joint; got {sorted(by_joint)}")
    return by_joint["front"].angle_deg, by_joint["rear"].angle_deg


def camera_extrinsics(camera: str,
                      arm: ArmState | tuple[ArmJointState, ArmJointState],
                      vehicle: object = DEFAULT_VEHICLE) -> CameraExtrinsic:
    """Derive one camera's extrinsic pose (position + orientation, in ``base_link``) from the vehicle
    rig geometry + the current arm posture.

    ``camera`` is one of the eight rig cameras (``CAMERAS``). ``arm`` is an ``arm_state.ArmState`` or a
    VT-03 ``(front, rear)`` ``ArmJointState`` pair. ``vehicle`` selects the platform (validated against
    the registry); the sourced rig is the IPEx/LAC-twin ``base_link`` set (its render-body sibling
    ``ez_rassor`` shares the same EZ-RASSOR-URDF mount frame).

    Chassis cameras get their fixed ``CAMERA_MOUNTS`` position and their contract ``look`` orientation,
    both independent of the arm. Arm cameras get their position from ``ArmState.drum_cam_offset_m``
    (the rigid pivot->drum link) and an optical axis along the arm's outward direction -- so raising
    the arm moves both."""
    get_vehicle(vehicle)                                  # boundary validation (rejects unknown vehicles)
    if camera not in CAMERA_MOUNTS:
        raise KeyError(f"unknown camera {camera!r}; rig cameras: {CAMERAS}")

    if camera in ARM_OF_CAMERA:
        which = ARM_OF_CAMERA[camera]
        front_deg, rear_deg = _arm_angles(arm)
        # COMPOSE arm_state's existing pivot->drum math (no re-derivation): the drum-end (x_fore, z_up)
        # in base_link at the CURRENT arm angle. Lateral is 0 (the arm cams sit on the centerline).
        state = ArmState(front_deg=front_deg, back_deg=rear_deg)
        drum_x, drum_z = state.drum_cam_offset_m(which)
        position: Vec3 = (drum_x, drum_z, 0.0)
        # optical forward = the arm's outward (pivot->drum) direction: horizontal outward at stow,
        # pitched up by the arm angle under a Meerkat raise. The exact flight aim is [ASSUMPTION].
        pivot_x = (ARM_ORIGIN_FRONT if which == "front" else ARM_ORIGIN_BACK)[0]
        forward: Vec3 = _normalize3((drum_x - pivot_x, drum_z, 0.0))
        mount = "arm"
    else:
        position = CAMERA_MOUNTS[camera]                  # fixed chassis mount (SOURCED)
        forward = _normalize3(CHASSIS_LOOK[camera])       # fixed contract look direction
        mount = "chassis"

    right, up, back = _look_columns(forward)
    quaternion = _quat_from_columns(right, up, back)
    return CameraExtrinsic(name=camera, mount=mount, position_m=position,
                           quaternion_xyzw=quaternion, optical_forward=forward)


def all_camera_extrinsics(arm: ArmState | tuple[ArmJointState, ArmJointState],
                          vehicle: object = DEFAULT_VEHICLE) -> dict[str, CameraExtrinsic]:
    """Derive the whole eight-camera rig at one posture -- the "for every image" set VT-10 asks for."""
    return {name: camera_extrinsics(name, arm, vehicle) for name in CAMERAS}
