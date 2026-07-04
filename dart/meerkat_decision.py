"""[REQ:AM-09] The planner decision rule for the SN-11 Meerkat observation: raise ONLY when the predicted
information gain justifies the cost of raising (arm-lift energy + transition time).

MEERKAT (arms rotate DOWN under the chassis, planting the drums and pushing the body UP) buys a real
vertical parallax baseline + a changing self-shadow geometry -- the SN-11 observation. But raising is not
free: the arm actuators do lift work and the rate-limited sweep costs time, and the raised stance shrinks
the support polygon (which SN-11 already gates on). AM-09 says the planner may pick the raise ONLY when its
predicted value exceeds that cost; otherwise the rover stays in TRANSIT and observes from the floor.

This module is the DECISION, and nothing more. It composes:
  * dart.meerkat_observation.MeerkatObservation (SN-11)  -- the candidate maneuver + its AM-01/AM-02/AM-03
    feasibility verdict (an infeasible raise is NEVER chosen, whatever the gain).
  * stewie.specs.arm_state.ArmState.raise_energy_j        -- the arm-lift energy over the MEERKAT round trip.
  * stewie.specs.arm_state.ARM_RATE_DEG_S                 -- the arm rate limit -> the transition time.
  * stewie.specs.bodies                                   -- the body's REAL gravity for the lift energy.

NO FABRICATED GAIN. The caller supplies ``info_gain`` -- the predicted information gain in the mission's own
value units (e.g. the SN-15 perception fill's predicted reduction in localization/mapping uncertainty). This
rule never invents a gain; it reads the physical COST from real code and returns choose iff the gain-to-cost
ratio strictly EXCEEDS an explicit threshold (default 1.0 = gain must exceed cost). The energy/time exchange
rates that put the physical cost on the same value scale as the gain are mission POLICY, surfaced as explicit
tunable parameters (never hidden constants).

Energy model note: ``arm_state.raise_energy_j`` accounts the drum-lift work only (the ICE-RASSOR mass
observable: lifting costs m*g*dh/eta, lowering ~0). Over the MEERKAT round trip the descent leg (arms
rotate DOWN, drums lower) is gravity-assisted ~0 and the recovery leg (arms rotate UP, drums lift back to
stow) carries the real actuator lift cost; the composed cost is the sum of both legs. The chassis
potential-energy component of a body raise is not in ``arm_state.raise_energy_j`` today -- when a
chassis-raise energy model lands it ADDS to this cost term (the decision structure is unchanged).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from dart import posture_select as ps
from dart.meerkat_observation import MeerkatObservation
from stewie.specs import arm_state as arm
from stewie.specs import bodies as B

#: Mission POLICY (not physics): how a Joule and a second convert to the same "value" units ``info_gain`` is
#: denominated in. 1.0 = one value unit per Joule / per second -- a placeholder unit exchange a mission MUST
#: calibrate to its own utility scale (energy-scarce vs time-scarce). Surfaced, tunable, never hidden.
DEFAULT_VALUE_PER_J = 1.0
DEFAULT_VALUE_PER_S = 1.0

#: The explicit AM-09 decision threshold: choose MEERKAT ONLY when info_gain / cost strictly EXCEEDS this.
#: 1.0 = the gain must exceed the cost (the acceptance); raise it for a mission that wants a value margin
#: before it commits to a raise.
DEFAULT_MIN_GAIN_COST_RATIO = 1.0

#: The total drum mass the recovery leg raises back to stow, default = both empty drums (a real lower
#: bound, ps.DRUM_MASS_KG per drum). The caller passes the ACTUAL loaded drum mass (structure + fill).
DEFAULT_DRUM_MASS_KG = 2.0 * ps.DRUM_MASS_KG


@dataclass(frozen=True)
class MeerkatDecision:
    """The AM-09 verdict over a MeerkatObservation candidate: WHETHER to raise, and the gain-vs-cost
    accounting behind it. ``choose`` is True ONLY when the maneuver is feasible AND the caller's predicted
    ``info_gain`` beats its cost by the explicit ``min_gain_cost_ratio``. ``raise_energy_j`` and
    ``transition_time_s`` are the physical cost from arm_state + the body's gravity; ``cost_value`` maps
    them into info_gain's value units via the mission exchange rates; ``gain_cost_ratio`` is
    info_gain / cost_value (``inf`` when the cost is 0). Nothing here is fabricated."""
    choose: bool
    feasible: bool
    info_gain: float
    raise_energy_j: float
    transition_time_s: float
    cost_value: float
    gain_cost_ratio: float
    min_gain_cost_ratio: float
    parallax_baseline_m: float
    reason: str


def meerkat_raise_cost(observation: MeerkatObservation, *, drum_mass_kg: float = DEFAULT_DRUM_MASS_KG,
                       body: str = "moon") -> tuple[float, float]:
    """The physical cost of the MEERKAT maneuver in ``observation``: ``(raise_energy_j, transition_time_s)``.

    ``raise_energy_j`` composes ``arm_state.raise_energy_j`` over the round trip stow -> MEERKAT -> stow
    (descent ~0, recovery = the drum-lift cost); ``transition_time_s`` is the round-trip arm sweep under the
    ``arm_state.ARM_RATE_DEG_S`` rate limit. Both are read from the observation's own MEERKAT sample -- the
    deepest (last) height of the sweep. Requires a feasible observation (an infeasible one has no samples)."""
    if not observation.samples:
        raise ValueError("meerkat_raise_cost requires a feasible observation with at least one sample")
    g = B.get_body(body).g
    meerkat_deg = math.degrees(observation.samples[-1].arm_pitch_rad)
    a = arm.ArmState()
    descent_j = a.raise_energy_j(drum_mass_kg, g, from_deg=0.0, to_deg=meerkat_deg)   # ~0 (gravity-assisted)
    recovery_j = a.raise_energy_j(drum_mass_kg, g, from_deg=meerkat_deg, to_deg=0.0)  # the real lift cost
    raise_energy_j = descent_j + recovery_j
    transition_time_s = 2.0 * abs(meerkat_deg) / arm.ARM_RATE_DEG_S
    return raise_energy_j, transition_time_s


def should_meerkat(observation: MeerkatObservation, *, info_gain: float,
                   drum_mass_kg: float = DEFAULT_DRUM_MASS_KG, body: str = "moon",
                   value_per_j: float = DEFAULT_VALUE_PER_J, value_per_s: float = DEFAULT_VALUE_PER_S,
                   min_gain_cost_ratio: float = DEFAULT_MIN_GAIN_COST_RATIO) -> MeerkatDecision:
    """[REQ:AM-09] Decide whether to run the SN-11 Meerkat ``observation`` given a caller-supplied predicted
    ``info_gain``. Choose iff the maneuver is FEASIBLE and its gain-to-cost ratio strictly EXCEEDS
    ``min_gain_cost_ratio`` (default 1.0 -> gain must exceed cost).

    The cost is real, from ``meerkat_raise_cost``: the arm-lift energy (``arm_state.raise_energy_j`` over the
    MEERKAT round trip) + the rate-limited transition time, mapped into info_gain's value units by the
    mission exchange rates ``value_per_j`` / ``value_per_s``. An INFEASIBLE observation (SN-11 refused the
    raise: illegal from-state or inadequate stability margin) is never chosen, whatever the gain -- you
    cannot execute a raise the rover cannot safely hold. ``info_gain`` is the caller's predicted gain; this
    rule fabricates none."""
    if not math.isfinite(info_gain) or info_gain < 0.0:
        raise ValueError(f"info_gain must be a finite, non-negative predicted gain, got {info_gain!r}")
    if value_per_j < 0.0 or value_per_s < 0.0:
        raise ValueError("value exchange rates (value_per_j, value_per_s) must be non-negative")
    if min_gain_cost_ratio <= 0.0:
        raise ValueError(f"min_gain_cost_ratio must be > 0, got {min_gain_cost_ratio}")

    if not observation.feasible:
        return MeerkatDecision(
            choose=False, feasible=False, info_gain=info_gain, raise_energy_j=0.0, transition_time_s=0.0,
            cost_value=0.0, gain_cost_ratio=0.0, min_gain_cost_ratio=min_gain_cost_ratio,
            parallax_baseline_m=observation.parallax_baseline_m, reason=f"infeasible: {observation.reason}")

    raise_energy_j, transition_time_s = meerkat_raise_cost(observation, drum_mass_kg=drum_mass_kg, body=body)
    cost_value = value_per_j * raise_energy_j + value_per_s * transition_time_s
    if cost_value <= 0.0:
        ratio = math.inf if info_gain > 0.0 else 0.0
    else:
        ratio = info_gain / cost_value
    choose = ratio > min_gain_cost_ratio
    reason = ("gain justifies cost" if choose else "gain does not justify cost")
    return MeerkatDecision(
        choose=choose, feasible=True, info_gain=info_gain, raise_energy_j=raise_energy_j,
        transition_time_s=transition_time_s, cost_value=cost_value, gain_cost_ratio=ratio,
        min_gain_cost_ratio=min_gain_cost_ratio, parallax_baseline_m=observation.parallax_baseline_m,
        reason=reason)


__all__ = [
    "DEFAULT_DRUM_MASS_KG",
    "DEFAULT_MIN_GAIN_COST_RATIO",
    "DEFAULT_VALUE_PER_J",
    "DEFAULT_VALUE_PER_S",
    "MeerkatDecision",
    "meerkat_raise_cost",
    "should_meerkat",
]