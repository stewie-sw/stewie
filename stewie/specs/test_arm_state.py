"""ARGUS T2.1-T2.2: the arm-swing joint model -- ONE articulated state for every consumer.

Doc truth: arm actuator excavation load 18.5 N*m on the Moon (TRL5 Table 7); arm origins at
base_link x = +/-0.20 (the sidecar render rig); arm raise = the ICE-RASSOR mass-inference
observable (mass * g * h / eta). Travel limits and rates are [ASSUMPTION]-tagged until the docs
give them -- the STRUCTURE (rate-limited travel, CG shift, camera pose, raise energy, reaction
cancellation) is the truth being integrated.
"""
import math

import pytest

from stewie.specs import arm_state as A


def test_travel_and_rate_limits_enforced():
    arm = A.ArmState()
    arm.command(front_deg=200.0, back_deg=-200.0)        # beyond travel
    assert arm.front_target_deg == A.ARM_TRAVEL_DEG[1]
    assert arm.back_target_deg == A.ARM_TRAVEL_DEG[0]
    arm.command(front_deg=40.0)
    arm.step(dt=0.1)                                     # one tick at the rate limit
    assert arm.front_deg == pytest.approx(min(40.0, A.ARM_RATE_DEG_S * 0.1))
    for _ in range(200):
        arm.step(dt=0.1)
    assert arm.front_deg == pytest.approx(40.0)          # converges to the command


def test_cg_shift_follows_geometry():
    arm = A.ArmState()
    z0 = arm.cg_offset_m()
    arm.command(front_deg=90.0, back_deg=90.0)           # both arms up
    for _ in range(400):
        arm.step(dt=0.1)
    dx, dz = arm.cg_offset_m()
    assert dz > z0[1]                                     # raising both arms RAISES the CG
    arm2 = A.ArmState()
    arm2.command(front_deg=90.0)                          # raising the FRONT arm curls its mass back
    for _ in range(400):                                  # over the pivot -> CG shifts REARWARD (the
        arm2.step(dt=0.1)                                 # physics; the first draft expected forward)
    assert arm2.cg_offset_m()[0] < 0.0


def test_drum_camera_pose_follows_the_arm():
    arm = A.ArmState()
    p0 = arm.drum_cam_offset_m("front")
    arm.command(front_deg=60.0)
    for _ in range(200):
        arm.step(dt=0.1)
    p1 = arm.drum_cam_offset_m("front")
    assert p1[1] > p0[1]                                  # the drum camera RISES with the arm
    assert math.hypot(p1[0] - A.ARM_ORIGIN_FRONT[0], p1[1]) == pytest.approx(
        A.ARM_LENGTH_M, abs=1e-9)                         # rigid link: constant radius from the pivot


def test_raise_energy_is_the_documented_observable():
    arm = A.ArmState()
    e = arm.raise_energy_j(drum_mass_kg=20.0, g=1.62, from_deg=0.0, to_deg=90.0)
    # m*g*dh/eta with dh = L*(sin90-sin0): pure mechanics on the documented geometry
    expect = 20.0 * 1.62 * A.ARM_LENGTH_M * 1.0 / A.ARM_LIFT_EFFICIENCY
    assert e == pytest.approx(expect)
    assert arm.raise_energy_j(20.0, 1.62, from_deg=90.0, to_deg=0.0) == 0.0   # lowering costs ~0 (brake)


def test_dig_reaction_cancellation():
    """T2.2: counter-rotating drums cancel the horizontal dig reaction (KSC-TOPS-7)."""
    net = A.net_dig_reaction_n(torque_nm=18.5, drum_radius_m=0.15)
    assert abs(net) < 1e-9                               # equal+opposite by construction
    single = A.net_dig_reaction_n(torque_nm=18.5, drum_radius_m=0.15, drums=("front",))
    assert abs(single) > 100.0                           # one drum alone DOES push -- the design point


def test_loaded_drums_shift_the_cg_for_maneuver_design():
    """Aaron 2026-06-10: maneuvers use POSTURES with WEIGHTED drums for balance -- the CG must
    include the drum LOAD at the drum position, not just link mass. A 25 kg front drum raised
    high pulls the CG up and toward the front pivot; the same drum empty barely moves it."""
    arm = A.ArmState()
    arm.command(front_deg=80.0)
    for _ in range(400):
        arm.step(dt=0.1)
    dx_e, dz_e = arm.cg_offset_m(front_drum_kg=0.0, back_drum_kg=0.0, dry_mass_kg=30.0)
    dx_l, dz_l = arm.cg_offset_m(front_drum_kg=25.0, back_drum_kg=0.0, dry_mass_kg=30.0)
    assert dz_l > dz_e + 0.02                             # the loaded raised drum lifts the CG
    assert abs(dx_l) != abs(dx_e)                         # and shifts it longitudinally
    # THE REAL MANEUVER PHYSICS (the first draft's intuition was wrong and the model caught it):
    # raising the EMPTY back arm curls its link mass FORWARD -> makes a front-heavy CG WORSE.
    arm.command(back_deg=80.0)
    for _ in range(400):
        arm.step(dt=0.1)
    dx_worse, _ = arm.cg_offset_m(front_drum_kg=25.0, back_drum_kg=0.0, dry_mass_kg=30.0)
    assert abs(dx_worse) > abs(dx_l)                      # naive counter-pose backfires
    # the TRUE ballast is mass-symmetric: equal loads at symmetric posture balance the CG
    dx_sym, _ = arm.cg_offset_m(front_drum_kg=25.0, back_drum_kg=25.0, dry_mass_kg=30.0)
    assert abs(dx_sym) < 0.01                             # balanced -- the designed-maneuver target
