"""EP-06: posture / observation POLICY -- transition and dwell TIME and ENERGY.

A Meerkat/arm posture change and the camera/LED usage at the observation vantage are not free: reaching
the posture takes TIME (the arms slew at a finite rate) and holding it to observe takes TIME (the dwell),
and each interval draws power (arm-actuator lift work + avionics/compute; camera LEDs during the dwell).
This module makes that a first-class POLICY the planner/executive can price, filling the EP-01 ledger's
explicit `arm_drum` / `observation` / `led` gaps for a Meerkat observation maneuver
(``lode.planner_assembly._energy_ledger``, which today documents them as zeros).

Nothing here is fabricated -- every quantity COMPOSES an existing sourced/derived model:

  * transition TIME       -- the arm sweep angle / the real slew limit
                             ``stewie.specs.arm_state.ARM_RATE_DEG_S`` (the one place the rate lives).
  * transition ENERGY     -- the arm-actuator LIFT WORK to raise the chassis over the posture change
                             (``stewie.physics.posture_kinematics.chassis_lift_m`` delta x lifted mass x g
                             / the ``rassor_mass_model.ARM_LIFT_EFFICIENCY`` drivetrain efficiency; raising
                             costs, lowering is ~free, matching ``arm_state.raise_energy_j``) PLUS the
                             avionics/compute draw (``ipex_specs.AVIONICS_POWER_W``) running through the move.
  * dwell TIME            -- a surfaced, tunable POLICY parameter (``DEFAULT_DWELL_S``), NOT a physics
                             claim -- the operator/executive sets the observation hold. Same discipline the
                             ``ipex_specs.IDLE_POWER_W`` idle knob uses: its own line, tagged, overridable.
  * dwell ENERGY         -- (avionics/compute + camera/LED watts) x the dwell. The LED watts come from the
                             real SN-07 selection policy (``dart.led_budget.select_led_budget``) when the
                             observation lights hard shadows, or 0 for a passive/sunlit hold.
  * posture LEGALITY/gate -- ``stewie.specs.posture_machine.can_transition`` (AM-01/AM-02/AM-03): an
                             ILLEGAL transition raises (no policy is priced for an impossible move); a legal
                             transition into a raised stance whose load-aware stability margin is inadequate
                             is reported ``feasible=False`` with the machine's reason (the times/energy are
                             still the real cost of the intended maneuver, for the executive to weigh).

Layer: DART (Decision & Autonomy). Imports upward from ``stewie.specs`` / ``stewie.physics`` / the DART
siblings ``posture_select`` + ``led_budget`` (the same direction ``dart.meerkat_observation`` already
composes). Pure + on-host; no render, no fabricated photometry, no synthetic numbers.
"""
# PROVENANCE: STEWIE DART subsystem (A. Storey)
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from dart import led_budget, posture_select as ps
from stewie.physics import posture_kinematics as pk
from stewie.physics.rassor_mass_model import ARM_LIFT_EFFICIENCY
from stewie.specs import ipex_specs, posture_machine as pm
from stewie.specs.arm_state import ARM_RATE_DEG_S

#: the observation HOLD at the posture vantage [s] -- a surfaced, tunable OPERATIONAL policy knob, NOT a
#: sourced physics figure. A multi-frame parallax/shadow capture + settle is seconds-scale; the operator
#: or executive overrides it per observation. Tagged like ipex_specs.IDLE_POWER_W: its own line, defensible
#: as an assumption, never buried. [ASSUMPTION/POLICY]
DEFAULT_DWELL_S = 5.0


@dataclass(frozen=True)
class PosturePolicy:
    """The time + energy cost of ONE posture change and the observation dwell that follows it.

    Times: ``transition_time_s`` is the arm slew to reach the posture (sweep / rate); ``dwell_time_s`` is
    the held observation. Energies (all Joules): ``transition_energy_j`` = the chassis LIFT WORK over the
    posture change + the avionics/compute draw through the slew; ``dwell_energy_j`` = (avionics/compute +
    camera/LED watts) x the dwell; ``total_energy_j`` is their sum. ``feasible``/``reason`` carry the
    AM-01 posture-machine verdict (a legal transition with an adequate load-aware stability margin);
    ``stability_margin_m`` is that margin when supplied. Frozen: a policy snapshot is immutable."""
    from_state: str
    to_state: str
    from_pitch_deg: float
    to_pitch_deg: float
    sweep_deg: float
    arm_rate_deg_s: float
    transition_time_s: float
    dwell_time_s: float
    lifted_mass_kg: float
    chassis_lift_delta_m: float
    lift_work_j: float
    avionics_power_w: float
    led_power_w: float
    transition_energy_j: float
    dwell_energy_j: float
    total_energy_j: float
    feasible: bool
    reason: str
    stability_margin_m: float | None = None


def _lift_work_j(from_pitch_rad: float, to_pitch_rad: float, *, lifted_mass_kg: float,
                 g_ms2: float, efficiency: float) -> tuple[float, float]:
    """(chassis_lift_delta_m, lift_work_j) for a SYMMETRIC arm sweep between two pitches. The chassis rises
    by the canonical forward-kinematics delta; raising it costs ``m * g * dlift / efficiency`` and lowering
    is ~free (gravity does the work), so only a POSITIVE lift is charged -- the ``arm_state.raise_energy_j``
    convention. Efficiency is the [CALIB] arm drivetrain efficiency (electrical-in -> useful-lift)."""
    lift_delta = (pk.chassis_lift_m(to_pitch_rad, to_pitch_rad)
                  - pk.chassis_lift_m(from_pitch_rad, from_pitch_rad))
    work = max(0.0, lifted_mass_kg * g_ms2 * lift_delta) / efficiency
    return lift_delta, work


def posture_transition_policy(from_state: str, to_state: str, *, from_pitch_rad: float,
                              to_pitch_rad: float, dwell_time_s: float = DEFAULT_DWELL_S,
                              led_power_w: float = 0.0,
                              lifted_mass_kg: float = ps.CHASSIS_MASS_KG,
                              g_ms2: float = ipex_specs.LUNAR_G_MS2,
                              arm_rate_deg_s: float = ARM_RATE_DEG_S,
                              avionics_power_w: float = ipex_specs.AVIONICS_POWER_W,
                              efficiency: float = ARM_LIFT_EFFICIENCY,
                              stability_margin_m: float | None = None,
                              min_margin_m: float = 0.05) -> PosturePolicy:
    """Price a posture change (``from_state`` -> ``to_state``) driven by a SYMMETRIC arm sweep
    (``from_pitch_rad`` -> ``to_pitch_rad``) plus the observation dwell that follows.

    Transition time = the sweep angle / ``arm_rate_deg_s``. Transition energy = the chassis lift work over
    the sweep + ``avionics_power_w`` through the move. Dwell energy = (``avionics_power_w`` + ``led_power_w``)
    x ``dwell_time_s``. Raises ``ValueError`` for an ILLEGAL transition (not in the posture-machine legal
    table -- no cost is priced for an impossible move); a legal transition whose supplied stability margin
    is below ``min_margin_m`` is returned ``feasible=False`` with the machine's reason, the real cost intact.
    """
    if dwell_time_s < 0.0:
        raise ValueError(f"dwell_time_s must be >= 0, got {dwell_time_s}")
    if arm_rate_deg_s <= 0.0:
        raise ValueError(f"arm_rate_deg_s must be > 0, got {arm_rate_deg_s}")
    if led_power_w < 0.0:
        raise ValueError(f"led_power_w must be >= 0, got {led_power_w}")

    # AM-01 legality: an illegal transition is not priced (fabricating a cost for an impossible move is a
    # lie). A self-transition and BRAKED_HOLD are always legal (posture_machine); reuse its exact table.
    if to_state != from_state and to_state not in pm.legal_transitions(from_state):
        raise ValueError(f"illegal posture transition {from_state}->{to_state}; "
                         f"legal from {from_state}: {sorted(pm.legal_transitions(from_state))}")
    feasible, reason = pm.can_transition(from_state, to_state, stability_margin_m=stability_margin_m,
                                         min_margin_m=min_margin_m)

    from_pitch_deg = math.degrees(from_pitch_rad)
    to_pitch_deg = math.degrees(to_pitch_rad)
    sweep_deg = abs(to_pitch_deg - from_pitch_deg)
    transition_time_s = sweep_deg / arm_rate_deg_s

    lift_delta_m, lift_work_j = _lift_work_j(from_pitch_rad, to_pitch_rad, lifted_mass_kg=lifted_mass_kg,
                                             g_ms2=g_ms2, efficiency=efficiency)
    transition_energy_j = lift_work_j + avionics_power_w * transition_time_s
    dwell_energy_j = (avionics_power_w + led_power_w) * dwell_time_s
    total_energy_j = transition_energy_j + dwell_energy_j

    return PosturePolicy(
        from_state=from_state, to_state=to_state,
        from_pitch_deg=from_pitch_deg, to_pitch_deg=to_pitch_deg, sweep_deg=sweep_deg,
        arm_rate_deg_s=arm_rate_deg_s, transition_time_s=transition_time_s, dwell_time_s=dwell_time_s,
        lifted_mass_kg=lifted_mass_kg, chassis_lift_delta_m=lift_delta_m, lift_work_j=lift_work_j,
        avionics_power_w=avionics_power_w, led_power_w=led_power_w,
        transition_energy_j=transition_energy_j, dwell_energy_j=dwell_energy_j,
        total_energy_j=total_energy_j, feasible=feasible, reason=reason,
        stability_margin_m=stability_margin_m)


def meerkat_observation_policy(*, from_state: str = pm.TRANSIT,
                               target_pitch_rad: float = ps.MEERKAT_PITCH_RAD,
                               dwell_time_s: float = DEFAULT_DWELL_S,
                               shadow_targets: Sequence[tuple[float, float]] | None = None,
                               fill_front_kg: float = 0.0, fill_rear_kg: float = 0.0,
                               active_cam_limit: int = 2, power_budget_w: float = 20.0,
                               g_ms2: float = ipex_specs.LUNAR_G_MS2,
                               min_margin_m: float = 0.05) -> PosturePolicy:
    """The EP-06 policy for a Meerkat observation: raise from ``from_state`` to the MEERKAT stance
    (arms-down ``target_pitch_rad``, the SN-08/SN-11 vantage) and hold to observe.

    The transition TIME is the real arm sweep (0 -> MEERKAT) / the slew rate; the transition ENERGY is the
    chassis lift work over that raise + avionics. The dwell TIME is the tunable ``dwell_time_s``; the dwell
    ENERGY adds the camera/LED usage -- when ``shadow_targets`` (SN-07 (body_azimuth_deg, need) hard-shadow
    targets) are given, the LED watts come from the real ``led_budget.select_led_budget`` selection under
    the same active-camera and power budgets; a passive/sunlit hold (``None``) draws 0 LED watts. The
    load-aware MEERKAT stability margin (``posture_select._stability_margin_m`` under the drum fill) gates
    feasibility exactly as ``dart.meerkat_observation`` does."""
    if target_pitch_rad > 0.0:
        raise ValueError(f"MEERKAT is an arms-DOWN raise; target_pitch_rad must be <= 0, got {target_pitch_rad}")

    led_power_w = 0.0
    if shadow_targets:
        sel = led_budget.select_led_budget(list(shadow_targets), active_cam_limit=active_cam_limit,
                                           power_budget_w=power_budget_w)
        led_power_w = float(sel["power_used_w"])

    margin_m = ps._stability_margin_m(target_pitch_rad, fill_front_kg, fill_rear_kg)
    return posture_transition_policy(
        from_state, pm.MEERKAT, from_pitch_rad=0.0, to_pitch_rad=target_pitch_rad,
        dwell_time_s=dwell_time_s, led_power_w=led_power_w, g_ms2=g_ms2,
        stability_margin_m=margin_m, min_margin_m=min_margin_m)
