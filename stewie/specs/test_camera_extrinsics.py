"""VT-10: posture-dependent camera extrinsics derived from vehicle + arm state.

The rig, the mounts, and the arm-camera motion are all COMPOSED from sourced code (CAMERA_MOUNTS +
arm_state.drum_cam_offset_m), so these tests assert the DERIVATION and the load-bearing behavior --
an arm camera tracks the arm (moves + pitches under a Meerkat raise), a chassis camera is rigid to
the body -- and that the orientation is a valid normalized quaternion consistent with the look.
"""
import math

import pytest

from stewie.physics.posture_kinematics import CAMERA_MOUNTS
from stewie.specs import camera_extrinsics as CE
from stewie.specs.arm_joint import ArmJointState
from stewie.specs.arm_state import ARM_ORIGIN_FRONT, ArmState


def test_arm_mounted_camera_moves_with_the_arm():  # [REQ:VT-10]
    """The front arm camera's position is DERIVED from the arm angle: raising the arm (Meerkat) lifts
    it, and the position is exactly arm_state's composed pivot->drum offset (no re-derivation)."""
    stow = CE.camera_extrinsics("drum_front_cam", ArmState(front_deg=0.0, back_deg=0.0))
    meerkat = CE.camera_extrinsics("drum_front_cam", ArmState(front_deg=70.0, back_deg=70.0))
    assert stow.mount == "arm"
    assert meerkat.position_m[1] > stow.position_m[1] + 0.2          # rises with the raise (up = +Y)
    assert meerkat.position_m != stow.position_m
    # exactly the sourced arm_state math, mapped to (fwd, up, lat=0)
    dx, dz = ArmState(front_deg=70.0, back_deg=70.0).drum_cam_offset_m("front")
    assert meerkat.position_m == pytest.approx((dx, dz, 0.0), abs=1e-12)
    # rigid link: constant radius from the pivot regardless of angle
    r = math.hypot(meerkat.position_m[0] - ARM_ORIGIN_FRONT[0], meerkat.position_m[1])
    assert r == pytest.approx(0.28, abs=1e-9)


def test_chassis_mounted_camera_is_fixed_to_the_body():  # [REQ:VT-10]
    """A chassis camera's pose does NOT depend on the arm posture -- identical across a stow vs a
    full Meerkat raise -- and its position is the sourced CAMERA_MOUNTS entry."""
    stow = CE.camera_extrinsics("front_left", ArmState(front_deg=0.0, back_deg=0.0))
    raised = CE.camera_extrinsics("front_left", ArmState(front_deg=90.0, back_deg=90.0))
    assert stow.mount == "chassis"
    assert stow.position_m == raised.position_m == CAMERA_MOUNTS["front_left"]
    assert stow.quaternion_xyzw == raised.quaternion_xyzw
    assert stow.optical_forward == pytest.approx((1.0, 0.0, 0.0))    # front pair looks forward (+X)


def test_orientation_is_a_valid_normalized_quaternion():  # [REQ:VT-10]
    """Every camera's quaternion is unit-norm and consistent with the stored look direction: the
    quaternion applied to the camera -Z axis reproduces optical_forward (through the vertical raise)."""
    postures = [ArmState(front_deg=0.0, back_deg=0.0),
                ArmState(front_deg=70.0, back_deg=70.0),
                ArmState(front_deg=90.0, back_deg=90.0)]     # IRON_CROSS: arm look is vertical (+Y)
    for arm in postures:
        for name, ext in CE.all_camera_extrinsics(arm).items():
            x, y, z, w = ext.quaternion_xyzw
            assert math.sqrt(x * x + y * y + z * z + w * w) == pytest.approx(1.0, abs=1e-9), name
            looked = CE.rotate_vector(ext.quaternion_xyzw, (0.0, 0.0, -1.0))
            assert looked == pytest.approx(ext.optical_forward, abs=1e-9), name


def test_arm_camera_look_pitches_up_under_meerkat():  # [REQ:VT-10]
    """The arm camera's OPTICAL AXIS tracks the arm: horizontal outward at stow, pitched up under a
    Meerkat raise -- while the chassis camera's look is unchanged by the arm."""
    stow = CE.camera_extrinsics("drum_front_cam", ArmState(front_deg=0.0, back_deg=0.0))
    meerkat = CE.camera_extrinsics("drum_front_cam", ArmState(front_deg=70.0, back_deg=70.0))
    assert stow.optical_forward == pytest.approx((1.0, 0.0, 0.0), abs=1e-9)   # outward +X at stow
    assert meerkat.optical_forward[1] > 0.9                                   # look now points up
    chassis_stow = CE.camera_extrinsics("rear_left", ArmState(front_deg=0.0, back_deg=0.0))
    chassis_raised = CE.camera_extrinsics("rear_left", ArmState(front_deg=70.0, back_deg=70.0))
    assert chassis_stow.optical_forward == chassis_raised.optical_forward == (-1.0, 0.0, 0.0)


def test_all_eight_cameras_derived_and_classified():  # [REQ:VT-10]
    """`all_camera_extrinsics` returns the whole sourced rig, split into the two arm cameras and six
    chassis cameras."""
    rig = CE.all_camera_extrinsics(ArmState())
    assert set(rig) == set(CAMERA_MOUNTS) and len(rig) == 8
    arms = {n for n, e in rig.items() if e.mount == "arm"}
    chassis = {n for n, e in rig.items() if e.mount == "chassis"}
    assert arms == {"drum_front_cam", "drum_back_cam"}
    assert chassis == {"front_left", "front_right", "rear_left", "rear_right", "left_mono", "right_mono"}


def test_accepts_arm_state_or_vt03_joint_pair():  # [REQ:VT-10]
    """The arm input may be an ArmState OR a VT-03 (front, rear) ArmJointState pair (order-independent)
    -- both derive the identical pose."""
    from_state = CE.camera_extrinsics("drum_front_cam", ArmState(front_deg=45.0, back_deg=-20.0))
    joints = (ArmJointState(joint="rear", angle_deg=-20.0),          # reversed order on purpose
              ArmJointState(joint="front", angle_deg=45.0))
    from_joints = CE.camera_extrinsics("drum_front_cam", joints)
    assert from_joints.position_m == pytest.approx(from_state.position_m, abs=1e-12)
    assert from_joints.quaternion_xyzw == pytest.approx(from_state.quaternion_xyzw, abs=1e-12)


def test_unknown_camera_and_vehicle_rejected():  # [REQ:VT-10]
    """Boundary validation: an unknown camera name and an unknown vehicle both raise."""
    with pytest.raises(KeyError):
        CE.camera_extrinsics("nose_cam", ArmState())
    with pytest.raises(KeyError):
        CE.camera_extrinsics("front_left", ArmState(), vehicle="starship")
