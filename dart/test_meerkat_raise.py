"""AM-03: MEERKAT raises the camera vantage by lowering the arms under the chassis; motion is
speed-limited and rejected when the stability margin is inadequate. Composes stewie.specs.posture_machine
(MEERKAT + gate) + stewie.specs.camera_extrinsics (VT-10 per-camera pose) + stewie.specs.arm_joint (VT-03
rate-limited slew) + stewie.physics.posture_kinematics (sourced chassis lift) + dart.posture_select
(canonical MEERKAT pitch + load-aware margin). No fabricated heights: the height gain is the sourced
chassis lift; the reject is a real load-aware margin under the guard."""
import math

import pytest

from dart import meerkat_raise as MR
from dart import posture_select as ps
from stewie.physics import posture_kinematics as pk
from stewie.specs import posture_machine as pm
from stewie.specs.arm_joint import ARM_RATE_DEG_S
from stewie.specs.arm_state import ArmState
from stewie.specs.camera_extrinsics import all_camera_extrinsics


def test_meerkat_raises_the_chassis_camera_vantage_above_nominal():
    """[REQ:AM-03] From TRANSIT the raise is feasible and every CHASSIS (perception) camera sits HIGHER in
    MEERKAT than in the nominal drive posture -- that height gain IS the acceptance. The gain equals the
    sourced chassis lift (posture_kinematics), not a fabricated number."""
    r = MR.meerkat_raise()
    assert r.feasible and r.reason == "ok"
    assert r.from_state == pm.TRANSIT and r.to_state == pm.MEERKAT
    assert r.raises_vantage                                          # the AM-03 acceptance predicate
    lift = pk.chassis_lift_m(math.radians(MR.MEERKAT_ARM_DEG), math.radians(MR.MEERKAT_ARM_DEG))
    assert lift > 0.0                                               # MEERKAT plants below the wheels -> real lift
    assert r.chassis_vantage_gain_m == pytest.approx(lift, abs=1e-9)
    for v in r.chassis_vantages:
        assert v.meerkat_height_m > v.nominal_height_m              # strictly raised
        assert v.gain_m == pytest.approx(lift, abs=1e-9)            # by the chassis lift exactly


def test_world_vantage_composes_the_vt10_extrinsic_and_the_sourced_lift():
    """[REQ:AM-03] Each reported vantage is base_link height above ground (posture_kinematics) + the VT-10
    extrinsic's base_link up offset -- the module COMPOSES camera_extrinsics, it does not re-derive mounts."""
    r = MR.meerkat_raise()
    base_meerkat = pk.base_link_height_m(math.radians(MR.MEERKAT_ARM_DEG), math.radians(MR.MEERKAT_ARM_DEG))
    ext = all_camera_extrinsics(ArmState(front_deg=MR.MEERKAT_ARM_DEG, back_deg=MR.MEERKAT_ARM_DEG))
    for v in r.vantages:
        assert v.meerkat_height_m == pytest.approx(base_meerkat + ext[v.name].position_m[1], abs=1e-9)


def test_arm_cameras_descend_while_chassis_cameras_rise():
    """[REQ:AM-03] MEERKAT plants the ARMS under the chassis, so the arm-mounted (drum) cameras DESCEND
    even as the chassis cameras rise -- reported honestly, and the rig's HIGHEST camera still rises."""
    r = MR.meerkat_raise()
    assert r.arm_vantages                                           # the two drum-arm cameras exist
    for v in r.arm_vantages:
        assert v.gain_m < 0.0                                       # the planting arms carry these down
    assert r.max_vantage_gain_m > 0.0                              # the rig's top camera still gains height


def test_motion_is_speed_limited_by_the_vt03_slew_cap():
    """[REQ:AM-03] The raise motion is SPEED-LIMITED: the VT-03 rate-limited joint slew never exceeds
    ARM_RATE_DEG_S, and the realized slew time cannot beat the rate-limited minimum |dtheta|/rate."""
    r = MR.meerkat_raise()
    assert r.speed_limited
    assert r.max_arm_speed_deg_s <= ARM_RATE_DEG_S + 1e-9
    min_time = abs(MR.MEERKAT_ARM_DEG - MR.NOMINAL_ARM_DEG) / ARM_RATE_DEG_S
    assert r.raise_time_s >= min_time - 1e-9                        # cannot be faster than the slew cap allows


def test_rejected_when_stability_margin_inadequate_under_unbalanced_load():
    """[REQ:AM-03] A heavy unbalanced drum load drops the load-aware MEERKAT margin below the guard, so
    the raise is REJECTED (feasible=False, no vantages) with the machine's margin reason -- the guard is
    real, not decorative. front=25 kg / rear=0 gives a MEERKAT margin ~0.042 m < the 0.05 m threshold."""
    margin = ps._stability_margin_m(ps.MEERKAT_PITCH_RAD, 25.0, 0.0)
    assert margin < 0.05                                           # premise from real posture_select geometry
    r = MR.meerkat_raise(fill_front_kg=25.0, fill_rear_kg=0.0)
    assert not r.feasible and not r.raises_vantage
    assert r.vantages == ()
    assert "stability margin" in r.reason
    assert r.chassis_vantage_gain_m == 0.0 and r.max_vantage_gain_m == 0.0
    assert r.stability_margin_m == pytest.approx(margin, abs=1e-9)


def test_a_balanced_load_that_clears_the_guard_still_raises():
    """[REQ:AM-03] A balanced load whose MEERKAT margin clears the guard stays feasible -- the refusal is
    margin-driven, not a blanket 'any load refuses'. Balanced 10 kg per drum keeps the margin > 0.05 m."""
    assert ps._stability_margin_m(ps.MEERKAT_PITCH_RAD, 10.0, 10.0) > 0.05
    r = MR.meerkat_raise(fill_front_kg=10.0, fill_rear_kg=10.0)
    assert r.feasible and r.raises_vantage


def test_illegal_from_state_refuses_without_fabricating_a_vantage():
    """[REQ:AM-03] MEERKAT is not directly reachable from DIG (posture_machine legality); the raise is
    refused with the machine's reason and yields NO vantage -- it never forces an illegal maneuver."""
    assert pm.MEERKAT not in pm.legal_transitions(pm.DIG)          # premise: DIG->MEERKAT is illegal
    r = MR.meerkat_raise(from_state=pm.DIG)
    assert not r.feasible and r.vantages == ()
    assert "illegal" in r.reason.lower()


def test_arms_up_angle_is_rejected():
    """[REQ:AM-03] MEERKAT is an arms-DOWN raise: a non-negative arm angle is rejected outright."""
    with pytest.raises(ValueError):
        MR.meerkat_raise(meerkat_arm_deg=5.0)
