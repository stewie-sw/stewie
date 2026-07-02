"""SN-14: active-perception objective -- expected viewpoint information per joule AND per second,
with stability risk as a HARD constraint.

Unifies the SN-08 pieces into one ranking: a candidate observation action is a posture maneuver
(TRANSIT -> a deeper symmetric arms-down pitch); its VALUE is the vertical parallax baseline the
two-posture maneuver buys (the SN-08 localization/map-information proxy: a static rover gets zero
vertical baseline); its COST is what the maneuver spends of the two mission currencies -- energy
and time. score = info / (E_maneuver + P_hold * t_slew), all denominator terms in joules, so a
posture that buys the same baseline for fewer joules OR fewer seconds ranks strictly higher.

Every term is grounded in an existing sourced/tagged model (nothing new is invented here):
  info    -- chassis-lift difference from the canonical forward kinematics (posture_kinematics,
             via posture_select._lift; the SN-08 viewpoint_gain numerator).
  energy  -- raising the chassis is gravity work, W = m*g*dh/eta (the ICE-RASSOR arm-raise
             structure, rassor_mass_model): CHASSIS_MASS_KG at ipex_specs.LUNAR_G_MS2 through
             ARM_LIFT_EFFICIENCY [CALIB]. Lowering costs ~0 lift work (arm_state convention).
  time    -- slew duration from the centralized arm rate limit arm_state.ARM_RATE_DEG_S
             [ASSUMPTION]; the same limit that bounds posture-change cadence everywhere else.
  P_hold  -- ipex_specs.AVIONICS_POWER_W [ASSUMPTION]: the avionics/compute draw the rover burns
             for every second spent observing instead of working -- the honest joules-per-second
             exchange rate that puts time in the same units as energy.
STABILITY IS A GATE, NOT A COST: a posture whose load-aware margin (posture_select) is below the
threshold is excluded outright (None) no matter how much information it offers -- tipping is not
tradeable against map quality.
"""
from __future__ import annotations

import math

from dart import posture_select as PS
from stewie.physics.rassor_mass_model import ARM_LIFT_EFFICIENCY
from stewie.specs import ipex_specs as S
from stewie.specs.arm_state import ARM_RATE_DEG_S

#: joules-per-second exchange rate for the time leg: the avionics/compute hold draw [ASSUMPTION].
HOLD_POWER_W = S.AVIONICS_POWER_W


def info_gain_m(to_pitch_rad: float, from_pitch_rad: float = 0.0) -> float:
    """Expected localization/map information of the maneuver: the vertical parallax baseline [m]
    between the two postures (the SN-08 viewpoint_gain numerator; zero for a static rover)."""
    return abs(PS._lift(to_pitch_rad) - PS._lift(from_pitch_rad))


def maneuver_time_s(to_pitch_rad: float, from_pitch_rad: float = 0.0,
                    rate_deg_s: float = ARM_RATE_DEG_S) -> float:
    """Slew duration [s] of the posture change at the centralized arm rate limit."""
    return abs(math.degrees(to_pitch_rad - from_pitch_rad)) / rate_deg_s


def maneuver_energy_j(to_pitch_rad: float, from_pitch_rad: float = 0.0,
                      efficiency: float = ARM_LIFT_EFFICIENCY) -> float:
    """Energy [J] to RAISE the chassis between the postures: gravity work m*g*dh/eta (the
    ICE-RASSOR arm-raise structure) on the chassis mass at lunar g. Lowering costs ~0 lift work."""
    dh = PS._lift(to_pitch_rad) - PS._lift(from_pitch_rad)
    return max(0.0, PS.CHASSIS_MASS_KG * S.LUNAR_G_MS2 * dh / efficiency)


def score_observation_action(to_pitch_rad: float, *, fill_front_kg: float = 0.0,
                             fill_rear_kg: float = 0.0, from_pitch_rad: float = 0.0,
                             min_margin_m: float = 0.05, rate_deg_s: float = ARM_RATE_DEG_S,
                             efficiency: float = ARM_LIFT_EFFICIENCY,
                             hold_power_w: float = HOLD_POWER_W) -> float | None:
    """The SN-14 objective for ONE candidate posture: info / (energy_J + hold_power_W * time_s),
    or None when the load-aware stability margin fails (HARD constraint -- excluded regardless of
    info). The null maneuver (to == from) buys no information and scores 0.0."""
    if PS._stability_margin_m(to_pitch_rad, fill_front_kg, fill_rear_kg) < min_margin_m:
        return None                                              # stability gates, never trades
    cost_j = (maneuver_energy_j(to_pitch_rad, from_pitch_rad, efficiency)
              + hold_power_w * maneuver_time_s(to_pitch_rad, from_pitch_rad, rate_deg_s))
    if cost_j <= 0.0:
        return 0.0                                               # null maneuver: no cost, no info
    return info_gain_m(to_pitch_rad, from_pitch_rad) / cost_j


def candidate_postures(step_rad: float = 0.02) -> list[float]:
    """The symmetric arms-down candidate sweep, TRANSIT (0) .. MEERKAT (the deepest statically-
    modelable canonical posture) -- the same grid posture_select explores."""
    n = int(round(-PS.MEERKAT_PITCH_RAD / step_rad))
    return [round(-i * step_rad, 6) for i in range(n + 1)]


def rank_observation_actions(*, fill_front_kg: float = 0.0, fill_rear_kg: float = 0.0,
                             from_pitch_rad: float = 0.0, min_margin_m: float = 0.05,
                             step_rad: float = 0.02) -> list[tuple[float, float]]:
    """Rank the candidate observation postures by the SN-14 objective under the current drum load:
    (score, arm_pitch_rad) sorted best-first, stability-infeasible candidates EXCLUDED entirely."""
    scored = []
    for pitch in candidate_postures(step_rad):
        s = score_observation_action(pitch, fill_front_kg=fill_front_kg, fill_rear_kg=fill_rear_kg,
                                     from_pitch_rad=from_pitch_rad, min_margin_m=min_margin_m)
        if s is not None:
            scored.append((s, pitch))
    return sorted(scored, key=lambda sp: sp[0], reverse=True)
