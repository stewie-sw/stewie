"""[REQ:EP-06] Meerkat/arm posture + camera/LED policy carries transition + dwell time AND energy."""
from __future__ import annotations

import math

import pytest

from dart import posture_policy as pp
from dart.led_budget import select_led_budget
from stewie.physics import posture_kinematics as pk
from stewie.specs import ipex_specs, posture_machine as pm
from stewie.specs.arm_state import ARM_RATE_DEG_S
from dart import posture_select as ps


def test_meerkat_policy_has_transition_time_from_the_arm_sweep_and_an_explicit_dwell():  # [REQ:EP-06]
    """The Meerkat policy carries a NONZERO transition time DERIVED from the real arm sweep (0 -> MEERKAT)
    and the real slew rate, plus an EXPLICIT dwell -- the two times EP-06 requires."""
    pol = pp.meerkat_observation_policy(dwell_time_s=4.0)

    # transition time is the real arm sweep angle / the real slew limit (arm_state.ARM_RATE_DEG_S), nonzero.
    sweep_deg = abs(math.degrees(ps.MEERKAT_PITCH_RAD))          # 0 -> MEERKAT, ~57.3 deg
    assert pol.transition_time_s > 0.0
    assert pol.transition_time_s == pytest.approx(sweep_deg / ARM_RATE_DEG_S)
    assert pol.sweep_deg == pytest.approx(sweep_deg)
    assert pol.arm_rate_deg_s == ARM_RATE_DEG_S

    # the dwell is the explicit, surfaced policy hold (not fabricated, tunable via the argument).
    assert pol.dwell_time_s == 4.0
    assert pol.to_state == pm.MEERKAT and pol.feasible is True


def test_transition_time_tracks_the_slew_rate():  # [REQ:EP-06]
    """A slower arm rate lengthens the transition time proportionally -- the time is genuinely derived from
    ARM_RATE_DEG_S, not a constant."""
    base = pp.posture_transition_policy(pm.TRANSIT, pm.MEERKAT, from_pitch_rad=0.0,
                                        to_pitch_rad=ps.MEERKAT_PITCH_RAD, arm_rate_deg_s=20.0)
    half = pp.posture_transition_policy(pm.TRANSIT, pm.MEERKAT, from_pitch_rad=0.0,
                                        to_pitch_rad=ps.MEERKAT_PITCH_RAD, arm_rate_deg_s=10.0)
    assert half.transition_time_s == pytest.approx(2.0 * base.transition_time_s)


def test_transition_energy_composes_chassis_lift_work_plus_avionics():  # [REQ:EP-06]
    """The transition ENERGY is the chassis LIFT WORK over the raise (posture_kinematics chassis-lift delta
    x lifted mass x g / drivetrain efficiency) PLUS the avionics/compute draw through the slew -- both real,
    both nonzero for a Meerkat raise."""
    pol = pp.meerkat_observation_policy(dwell_time_s=5.0)

    lift_delta = pk.chassis_lift_m(ps.MEERKAT_PITCH_RAD, ps.MEERKAT_PITCH_RAD) - pk.chassis_lift_m(0.0, 0.0)
    assert pol.chassis_lift_delta_m == pytest.approx(lift_delta) and lift_delta > 0.0
    assert pol.lift_work_j > 0.0                                  # a real raise costs lift work
    expected_trans = pol.lift_work_j + ipex_specs.AVIONICS_POWER_W * pol.transition_time_s
    assert pol.transition_energy_j == pytest.approx(expected_trans)
    assert pol.transition_energy_j > 0.0


def test_dwell_energy_grows_with_camera_led_usage():  # [REQ:EP-06]
    """The dwell ENERGY includes the camera/LED usage: a Meerkat hold that lights a hard shadow (SN-07
    led_budget) draws MORE dwell energy than a passive hold, by exactly the selected LED watts x the dwell."""
    passive = pp.meerkat_observation_policy(dwell_time_s=5.0)                       # no LEDs
    lit = pp.meerkat_observation_policy(dwell_time_s=5.0, shadow_targets=[(0.0, 1.0)])

    # the LED watts are the REAL SN-07 selection, not a fabricated number.
    sel = select_led_budget([(0.0, 1.0)], active_cam_limit=2, power_budget_w=20.0)
    assert lit.led_power_w == pytest.approx(sel["power_used_w"]) and lit.led_power_w > 0.0
    assert passive.led_power_w == 0.0

    assert passive.dwell_energy_j == pytest.approx(ipex_specs.AVIONICS_POWER_W * 5.0)
    assert lit.dwell_energy_j == pytest.approx((ipex_specs.AVIONICS_POWER_W + lit.led_power_w) * 5.0)
    assert lit.dwell_energy_j > passive.dwell_energy_j
    # total energy is transition + dwell, all real.
    assert lit.total_energy_j == pytest.approx(lit.transition_energy_j + lit.dwell_energy_j)


def test_unstable_meerkat_is_reported_infeasible_but_still_priced():  # [REQ:EP-06]
    """A heavy unbalanced drum load drops the load-aware MEERKAT margin below the guard: the policy is
    reported feasible=False (the executive can refuse it) yet still carries the real transition/dwell cost
    of the intended maneuver -- the numbers are not fabricated away."""
    unstable = pp.meerkat_observation_policy(fill_front_kg=40.0, fill_rear_kg=0.0)
    assert unstable.feasible is False and "margin" in unstable.reason
    assert unstable.transition_time_s > 0.0 and unstable.total_energy_j > 0.0


def test_illegal_transition_is_not_priced():  # [REQ:EP-06]
    """No cost is priced for an IMPOSSIBLE posture move: MEERKAT is not directly reachable from DIG
    (posture_machine legality), so the policy raises rather than inventing a transition cost."""
    with pytest.raises(ValueError, match="illegal posture transition"):
        pp.posture_transition_policy(pm.DIG, pm.MEERKAT, from_pitch_rad=0.0,
                                     to_pitch_rad=ps.MEERKAT_PITCH_RAD)
