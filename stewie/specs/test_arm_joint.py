"""VT-03: the front/rear arm JOINT-STATE record -- joint id, limits, velocity, and brake, with the
two invariants (angle within limits; a braked joint holds). The travel/slew limits are asserted to
come from `arm_state`'s one source, not a re-fabricated number.
"""
import pytest

from stewie.specs import arm_joint as J
from stewie.specs import arm_state as A


def test_arm_joint_angle_must_be_within_limits():  # [REQ:VT-03]
    """VT-03: the joint record validates angle within [min,max] on construction and rejects an
    unknown joint id. Limits default from arm_state (the one source), not a new fabricated value."""
    j = J.ArmJointState(joint="front", angle_deg=30.0)
    assert j.min_deg == A.ARM_TRAVEL_DEG[0]
    assert j.max_deg == A.ARM_TRAVEL_DEG[1]
    assert j.max_rate_deg_s == A.ARM_RATE_DEG_S
    assert j.within_limits()
    with pytest.raises(ValueError):
        J.ArmJointState(joint="front", angle_deg=A.ARM_TRAVEL_DEG[1] + 5.0)   # beyond the max limit
    with pytest.raises(ValueError):
        J.ArmJointState(joint="nose", angle_deg=0.0)                          # unknown joint id


def test_braked_joint_holds():  # [REQ:VT-03]
    """VT-03/AM-08: a braked joint ignores the command and does not move; released, it slews toward
    the command rate-limited by the sourced ARM_RATE_DEG_S and stops (velocity->0) at the target."""
    braked = J.ArmJointState(joint="rear", angle_deg=20.0).engage_brake()
    assert braked.brake_engaged and braked.velocity_deg_s == 0.0
    held = braked.step(target_deg=90.0, dt=1.0)
    assert held.angle_deg == 20.0 and held.velocity_deg_s == 0.0        # holds despite the command

    free = braked.release_brake()
    moved = free.step(target_deg=90.0, dt=0.1)
    assert moved.angle_deg == pytest.approx(20.0 + A.ARM_RATE_DEG_S * 0.1)   # one rate-limited tick
    assert moved.velocity_deg_s == pytest.approx(A.ARM_RATE_DEG_S)
    for _ in range(1000):
        moved = moved.step(target_deg=90.0, dt=0.1)
    assert moved.angle_deg == pytest.approx(90.0)                       # converges to the command
    assert moved.velocity_deg_s == pytest.approx(0.0)                   # and stops


def test_braked_state_consistent_and_velocity_bounded():  # [REQ:VT-03]
    """A braked joint cannot carry a nonzero velocity, and no joint may exceed its slew rate."""
    with pytest.raises(ValueError):
        J.ArmJointState(joint="front", angle_deg=0.0, velocity_deg_s=5.0, brake_engaged=True)
    with pytest.raises(ValueError):
        J.ArmJointState(joint="front", angle_deg=0.0, velocity_deg_s=A.ARM_RATE_DEG_S + 10.0)


def test_pair_from_arm_state_links_front_and_rear():  # [REQ:VT-03]
    """The vehicle twin's arm kinematics (arm_state.ArmState) project to the two typed joint records
    with velocities derived from the SAME rate limit ArmState.step uses; a braked joint reports 0."""
    arm = A.ArmState()
    arm.command(front_deg=40.0, back_deg=-30.0)
    arm.step(dt=0.1)
    front, rear = J.pair_from_arm_state(arm, dt=0.1)
    assert front.joint == "front" and rear.joint == "rear"
    assert front.angle_deg == pytest.approx(arm.front_deg)
    assert rear.angle_deg == pytest.approx(arm.back_deg)
    assert front.velocity_deg_s == pytest.approx(A.ARM_RATE_DEG_S)      # slewing at the rate limit
    assert abs(rear.velocity_deg_s) <= rear.max_rate_deg_s + 1e-9
    assert front.within_limits() and rear.within_limits()

    fb, _rb = J.pair_from_arm_state(arm, dt=0.1, front_brake=True)
    assert fb.brake_engaged and fb.velocity_deg_s == 0.0               # braked joint reports 0
