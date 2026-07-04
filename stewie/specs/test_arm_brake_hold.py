"""AM-08: a VALIDATED braked posture hold with a MODELED holding torque and zero holding power.

Composes VT-03's zero-velocity brake hold (`arm_joint`) with the real arm geometry (`arm_state`), the
30 kg IPEx mass class (`ipex_specs`), and the body's sourced surface gravity (`stewie_bodies`) -- analytic
ground truth, no synthetic data. Verifies (1) a braked joint HOLDS the posture, (2) the modeled holding
torque IS the gravity moment ``m*g*L*|cos(theta)|`` -- NONZERO when the arm is extended/horizontal, ZERO
when it is vertical, (3) the hold is VALIDATED against the static tip-over margin, and (4) the passive hold
draws zero power so transition energy remains charged.
"""
from __future__ import annotations

import math

import pytest

from stewie.specs import arm_brake_hold as H
from stewie.specs import arm_state as A
from stewie.specs.ipex_specs import ROVER_MASS_CLASS_KG
from stewie_bodies import DEFAULT_BODY, get_body


def test_braked_hold_holds_and_torque_is_the_gravity_moment():  # [REQ:AM-08]
    """The two things AM-08 adds over VT-03: a braked joint HOLDS the posture, and the modeled holding
    torque IS the gravity moment -- nonzero when the arm is extended (front, horizontal) and zero when it
    is vertical (rear, 90 deg)."""
    g = get_body(DEFAULT_BODY).g
    hold = H.braked_hold(front_deg=0.0, rear_deg=90.0)   # front extended/horizontal, rear vertical

    # (1) a braked joint HOLDS: both joints braked, zero velocity, and it ignores a drive command (VT-03)
    assert hold.held()
    assert hold.front.brake_engaged and hold.rear.brake_engaged
    assert hold.front.velocity_deg_s == 0.0 and hold.rear.velocity_deg_s == 0.0
    assert hold.front.step(target_deg=100.0, dt=1.0).angle_deg == 0.0   # braked -> command ignored

    # (2) the modeled holding torque IS the gravity moment m*g*L*|cos(theta)|
    m = A.ARM_MASS_FRAC * ROVER_MASS_CLASS_KG                           # arm's share of the dry mass
    assert hold.holding_torque_front_nm == pytest.approx(m * g * A.ARM_LENGTH_M)   # theta=0 -> max lever
    assert hold.holding_torque_front_nm > 0.0                                       # NONZERO when extended
    assert hold.holding_torque_rear_nm == pytest.approx(0.0, abs=1e-9)              # theta=90 -> ZERO

    # holding power is zero: a passive mechanical brake reacts a static torque, it draws no power
    assert hold.holding_power_w == 0.0


def test_holding_torque_matches_arm_geometry_and_drum_load():  # [REQ:AM-08]
    """The gravity-moment model, checked against the real arm geometry: full lever at horizontal, zero at
    vertical, cos-scaled between, magnitude symmetric in the sign of the angle, and a loaded drum riding at
    the drum axis increases the moment the brake must react."""
    g = get_body(DEFAULT_BODY).g
    tau0 = H.gravity_hold_torque_nm(0.0, g=g)                           # extended/horizontal -> max moment
    assert tau0 == pytest.approx(A.ARM_MASS_FRAC * ROVER_MASS_CLASS_KG * g * A.ARM_LENGTH_M)
    assert H.gravity_hold_torque_nm(90.0, g=g) == pytest.approx(0.0, abs=1e-9)      # vertical -> zero
    assert H.gravity_hold_torque_nm(45.0, g=g) == pytest.approx(tau0 * math.cos(math.radians(45.0)))
    assert H.gravity_hold_torque_nm(-30.0, g=g) == pytest.approx(H.gravity_hold_torque_nm(30.0, g=g))

    loaded = H.gravity_hold_torque_nm(0.0, drum_load_kg=5.0, g=g)       # regolith in the drum adds moment
    assert loaded == pytest.approx((A.ARM_MASS_FRAC * ROVER_MASS_CLASS_KG + 5.0) * g * A.ARM_LENGTH_M)
    assert loaded > tau0


def test_hold_is_validated_against_tip_over_margin():  # [REQ:AM-08]
    """The hold is VALIDATED: on flat/moderate terrain the posture is a valid stability-margin hold; past
    the pitch tip-over angle it is refused as invalid -- while the joints still mechanically hold."""
    flat = H.braked_hold(front_deg=30.0, rear_deg=30.0, pitch_deg=0.0, roll_deg=0.0)
    assert flat.valid and flat.margin_deg > 0.0 and flat.risk != "tip"

    # gauge (0.57) > wheelbase (0.40) -> pitch binds at atan((0.40/2)/0.30) ~ 33.7 deg; 80 deg tips
    steep = H.braked_hold(front_deg=0.0, rear_deg=0.0, pitch_deg=80.0, roll_deg=0.0)
    assert steep.risk == "tip" and not steep.valid
    assert steep.held()          # the joints still hold; the POSTURE just is not stability-valid


def test_hold_draws_no_power_so_transition_energy_remains_charged():  # [REQ:AM-08]
    """The passive hold draws zero power for any duration, so a transition-energy budget reserved to LEAVE
    the hold (the ICE-RASSOR raise energy to swing the arm back up) is preserved -- remains charged."""
    assert H.hold_energy_j(3600.0) == 0.0                              # an hour of holding costs nothing

    budget = A.ArmState().raise_energy_j(drum_mass_kg=7.3, g=get_body(DEFAULT_BODY).g,
                                         from_deg=0.0, to_deg=90.0)     # a real raise-energy budget
    assert budget > 0.0
    assert H.transition_energy_remains_charged(budget, hold_duration_s=3600.0) == pytest.approx(budget)