"""[REQ:AM-09] The planner chooses the SN-11 Meerkat raise ONLY when predicted information gain justifies
its cost (arm-lift energy + transition time), else it stays in TRANSIT and does NOT raise.

Composes REAL code end-to-end: a real MeerkatObservation (SN-11), the arm_state raise energy + rate limit,
and the body's gravity. No fabricated gain -- the caller supplies info_gain; the rule decides. No fabricated
cost -- it is recomputed here from arm_state directly and cross-checked against the decision.
"""
import math

import pytest

from dart import meerkat_observation as MO
from dart.meerkat_decision import (
    DEFAULT_DRUM_MASS_KG,
    meerkat_raise_cost,
    should_meerkat,
)
from stewie.specs import arm_state as arm
from stewie.specs import bodies as B


def _feasible_obs() -> MO.MeerkatObservation:
    """A real, feasible TRANSIT -> MEERKAT observation (zero fill clears the SN-11 stability gate)."""
    obs = MO.meerkat_observation(feature_id="rock_9", target_xy=(5.0, 0.0), rover_xy=(0.0, 0.0))
    assert obs.feasible and obs.samples          # guard: the composition premise
    return obs


def _raw_cost() -> tuple[float, float]:
    """Recompute the MEERKAT cost from arm_state DIRECTLY (independent of the module under test)."""
    obs = _feasible_obs()
    g = B.get_body("moon").g
    mk_deg = math.degrees(obs.samples[-1].arm_pitch_rad)
    a = arm.ArmState()
    energy_j = (a.raise_energy_j(DEFAULT_DRUM_MASS_KG, g, from_deg=0.0, to_deg=mk_deg)
                + a.raise_energy_j(DEFAULT_DRUM_MASS_KG, g, from_deg=mk_deg, to_deg=0.0))
    time_s = 2.0 * abs(mk_deg) / arm.ARM_RATE_DEG_S
    return energy_j, time_s


def test_am09_cost_composes_arm_state_raise_energy_and_rate_limit():
    """[REQ:AM-09] The decision's cost is the REAL arm_state round-trip lift energy + rate-limited transition
    time (not a fabricated number), and cost_value is exactly value_per_j*E + value_per_s*T."""
    obs = _feasible_obs()
    energy_j, time_s = _raw_cost()
    assert energy_j > 0.0 and time_s > 0.0                       # a raise is never free
    # meerkat_raise_cost returns the same real cost recomputed from arm_state.
    e2, t2 = meerkat_raise_cost(obs)
    assert e2 == pytest.approx(energy_j) and t2 == pytest.approx(time_s)
    d = should_meerkat(obs, info_gain=0.0, value_per_j=1.0, value_per_s=1.0)
    assert d.raise_energy_j == pytest.approx(energy_j)
    assert d.transition_time_s == pytest.approx(time_s)
    assert d.cost_value == pytest.approx(energy_j + time_s)


def test_am09_meerkat_chosen_only_when_gain_exceeds_cost():
    """[REQ:AM-09] With unit exchange rates and the default threshold (gain must exceed cost): a gain ABOVE
    the cost is chosen; a gain BELOW the cost is NOT; the boundary (gain == cost) is NOT (strict exceed)."""
    obs = _feasible_obs()
    energy_j, time_s = _raw_cost()
    cost = energy_j + time_s

    above = should_meerkat(obs, info_gain=cost * 2.0, value_per_j=1.0, value_per_s=1.0)
    assert above.choose is True and above.feasible is True
    assert above.gain_cost_ratio == pytest.approx(2.0)

    below = should_meerkat(obs, info_gain=cost * 0.5, value_per_j=1.0, value_per_s=1.0)
    assert below.choose is False                                 # the "ONLY when" direction
    assert below.gain_cost_ratio == pytest.approx(0.5)

    at = should_meerkat(obs, info_gain=cost, value_per_j=1.0, value_per_s=1.0)
    assert at.choose is False                                    # strict exceed: equal does NOT justify
    assert at.gain_cost_ratio == pytest.approx(1.0)

    just_over = should_meerkat(obs, info_gain=cost * 1.0001, value_per_j=1.0, value_per_s=1.0)
    assert just_over.choose is True


def test_am09_infeasible_meerkat_is_never_chosen_whatever_the_gain():
    """[REQ:AM-09] An infeasible raise (SN-11 refused it -- here an unclearable stability-margin guard) is
    NOT chosen even for an enormous predicted gain: you cannot execute a raise the rover cannot hold."""
    infeasible = MO.meerkat_observation(feature_id="rock_9", target_xy=(5.0, 0.0), rover_xy=(0.0, 0.0),
                                        min_margin_m=10.0)
    assert infeasible.feasible is False and infeasible.samples == ()
    d = should_meerkat(infeasible, info_gain=1.0e9)
    assert d.choose is False and d.feasible is False
    assert d.raise_energy_j == 0.0 and d.transition_time_s == 0.0
    assert "infeasible" in d.reason


def test_am09_threshold_is_explicit_and_tunable():
    """[REQ:AM-09] The gain/cost threshold is an EXPLICIT parameter: a marginal candidate chosen at the
    default ratio (1.0) is REJECTED once the mission demands a larger value margin."""
    obs = _feasible_obs()
    energy_j, time_s = _raw_cost()
    cost = energy_j + time_s
    gain = cost * 1.15                                           # 15% over cost: a marginal candidate

    lenient = should_meerkat(obs, info_gain=gain, value_per_j=1.0, value_per_s=1.0,
                             min_gain_cost_ratio=1.0)
    assert lenient.choose is True

    strict = should_meerkat(obs, info_gain=gain, value_per_j=1.0, value_per_s=1.0,
                            min_gain_cost_ratio=1.5)
    assert strict.choose is False                               # same candidate, higher bar -> not raised
    assert strict.min_gain_cost_ratio == 1.5


def test_am09_energy_scarce_mission_weights_change_the_decision():
    """[REQ:AM-09] The energy/time exchange rates are real, tunable policy: an energy-scarce mission (a large
    value_per_j) inflates the same maneuver's cost enough to flip a would-be raise to NOT-raise."""
    obs = _feasible_obs()
    energy_j, time_s = _raw_cost()

    cheap = should_meerkat(obs, info_gain=energy_j + time_s + 1.0, value_per_j=1.0, value_per_s=1.0)
    assert cheap.choose is True

    # Same gain, but energy now costs 100x: cost_value climbs above the gain -> the raise is not worth it.
    scarce = should_meerkat(obs, info_gain=energy_j + time_s + 1.0, value_per_j=100.0, value_per_s=1.0)
    assert scarce.cost_value == pytest.approx(100.0 * energy_j + time_s)
    assert scarce.choose is False


def test_am09_negative_or_nonfinite_gain_is_rejected():
    """[REQ:AM-09] The rule refuses a nonsensical gain rather than fabricating a decision from it."""
    obs = _feasible_obs()
    with pytest.raises(ValueError):
        should_meerkat(obs, info_gain=-1.0)
    with pytest.raises(ValueError):
        should_meerkat(obs, info_gain=math.inf)
    with pytest.raises(ValueError):
        should_meerkat(obs, info_gain=5.0, min_gain_cost_ratio=0.0)