"""[REQ:AD-01] The AUTODIG behaviour layer -- a torque-regulating autonomous-excavation controller.

STEWIE had the excavation PRIMITIVES (the McKyes/Reece draft model in ``stewie.physics.excavation``,
the drum-mass FDC sensor + offload trigger in ``rassor_mass_model``, the arm kinematics in
``specs.arm_state``, the cut/dump/relax seam on ``physics.worksite.WorkSite``, and the berm-building
cut-haul-fill FSM in ``lode.berm_fsm``) but no AUTONOMOUS controller sequencing one dig CYCLE. This
row is that controller, grounded in ``docs/vehicle_ipex.md`` (the ``[BUCKLES]`` IPEx auto-dig loop):

  * drum TORQUE is the PROCESS variable, the arm/bite depth the CONTROL variable. The torque is the
    earthmoving DRAFT force (``excavation.draft_force``, the McKyes/Reece FEE) times the drum radius --
    a DENSITY-RESPONSIVE quantity, because the FEE reads the cell's (phi, cohesion) from the SAME
    material model the terramechanics spine uses. So a single torque setpoint yields a SHALLOWER bite
    in denser regolith. This is the density adaptation PX-14's drum-CURRENT loop honestly could NOT
    claim (its conserved sim field is uniform); here it falls out of the physics, not out of a fit.
  * the bite is bounded by the anti-bridging cut-per-pass cap (``ipex_specs.max_cut_per_pass_m``); an
    unreachable setpoint saturates the bite AT the cap, never above it.
  * a rock >= 10 cm in the cut path, or a buried-rock surcharge that spikes even the shallowest
    productive bite past a drum-overload torque ceiling, aborts to STALL (docs: rocks >= 10 cm
    "threaten autonomy -- the digger reaches a stall state ... needs intervention").
  * drum-full (``rassor_mass_model.should_offload`` on the conservative UPPER bound) fires the offload
    handoff: DIG -> LIFT -> OFFLOAD -> a ``berm_fsm.BermObs`` that drives the berm FSM LOAD -> HAUL. The
    AutoDig cycle therefore sits BENEATH ``lode.berm_fsm`` -- it is the excavation controller the
    berm FSM's LOAD state delegates to.
  * every dig pass emits a conserved-EFFORT record (drum torque, specific dig energy, ingested mass,
    mechanical work). This is the AD-02 effort log -- the conserved effort AD-02 generalises into the
    per-actuator electrical observables (I, V, tau, P, E).

[CALIB] The torque setpoint, the drum-overload ceiling and the productive-bite floor are OURS -- the
real IPEx auto-dig setpoints/PID gains are not published (like PX-14's damping). Acceptance is on the
closed-loop BEHAVIOUR (regulation, density adaptation, the bound, the stall/offload logic), never on
reproducing a specific NASA number.
"""
# PROVENANCE: STEWIE DART/LODE autonomy layer (A. Storey), row AD-01.
from __future__ import annotations

from dataclasses import dataclass

from lode.berm_fsm import BermObs
from stewie.physics import excavation as _ex
from stewie.physics import material as _material
from stewie.physics import rassor_mass_model as _rm
from stewie.specs import ipex_specs as _ipex

# ---- behaviour-layer constants --------------------------------------------------------------------
#: which bucket-drum's geometry the controller regulates (large = RASSOR-2.0 flight drum).
DRUM = "large"
#: [CALIB] the drum-torque setpoint the loop holds [N*m]. Chosen so the nominal BP-1 bite sits inside
#: the anti-bridging cap at every density in the material envelope; the real auto-dig setpoint is
#: unpublished (like PX-14's damping), so acceptance is on the closed-loop behaviour, not this number.
TORQUE_SETPOINT_NM = 1.0
#: [CALIB] drum-overload ceiling [N*m]: if even the shallowest productive bite exceeds this, the drum
#: cannot advance (a grabbed buried rock) and the cycle stalls.
STALL_TORQUE_CEILING_NM = 8.0
#: rocks >= this size threaten autonomy -> stall (docs/vehicle_ipex.md, [BUCKLES]).
ROCK_HAZARD_M = 0.10
#: [CALIB] productive-bite floor as a fraction of the cut-per-pass cap: a dig must engage at least this
#: much to advance, so the overload check is evaluated at this shallowest bite.
MIN_BITE_FRAC = 0.05

# ---- FSM states (STALL and DONE are terminal) -----------------------------------------------------
TRAVERSE = "TRAVERSE"
DIG = "DIG"
LIFT = "LIFT"
OFFLOAD = "OFFLOAD"
STALL = "STALL"
DONE = "DONE"
_TERMINAL = frozenset({STALL, DONE})


@dataclass(frozen=True)
class BiteSolution:
    """The regulated bite for one pass: the CONTROL variable (depth) that holds the PROCESS variable
    (torque) on the setpoint, plus the FEE specific dig energy at that bite."""
    depth_m: float
    torque_nm: float
    saturated: bool                    # True iff the setpoint was unreachable and the bite hit the cap
    specific_energy_j_per_kg: float
    bulk_density_kg_m3: float


@dataclass
class AutoDigController:
    """The torque-regulating bite controller. ``open_loop=True`` neuters the feedback (always the max
    bite) -- the non-vacuity lever: an open loop neither holds the setpoint nor adapts to density."""
    torque_setpoint_nm: float = TORQUE_SETPOINT_NM
    drum: str = DRUM
    gravity_ms2: float = _ipex.LUNAR_G_MS2
    stall_ceiling_nm: float = STALL_TORQUE_CEILING_NM
    open_loop: bool = False

    @property
    def width_m(self) -> float:
        """The bucket-drum cutting width [m] (BDSCALE Table 1)."""
        return float(_ipex.DRUM_DIMENSIONS_M[self.drum]["width"])

    @property
    def radius_m(self) -> float:
        """The drum radius [m] -- the moment arm turning the draft force into a reaction torque."""
        return float(_ipex.DRUM_DIMENSIONS_M[self.drum]["diameter"]) / 2.0

    @property
    def max_cut_m(self) -> float:
        """The anti-bridging cut-per-pass cap [m] (50% of the scoop-opening height, BDS p.7)."""
        return float(_ipex.max_cut_per_pass_m(self.drum))

    @property
    def min_bite_m(self) -> float:
        """The shallowest productive bite [m] -- a dig must engage at least this much to advance."""
        return MIN_BITE_FRAC * self.max_cut_m

    def _report(self, depth_m: float, bulk_density_kg_m3: float, surcharge_pa: float) -> dict:
        """The McKyes/Reece FEE report at (depth, density): draft + specific dig energy. Soil (phi,
        cohesion) come from the SAME material model the terramechanics spine reads."""
        phi_rad, cohesion_pa = _material.cell_strength(float(bulk_density_kg_m3))
        return _ex.earthmoving_report(
            depth_m=max(1e-6, float(depth_m)), width_m=self.width_m, cohesion_pa=cohesion_pa,
            bulk_density_kg_m3=float(bulk_density_kg_m3), gravity_ms2=self.gravity_ms2,
            phi_rad=phi_rad, surcharge_pa=float(surcharge_pa))

    def torque_at(self, depth_m: float, bulk_density_kg_m3: float, *, surcharge_pa: float = 0.0) -> float:
        """The drum reaction torque [N*m] to cut ``depth_m`` in soil of ``bulk_density_kg_m3``: the FEE
        draft force times the drum radius. Monotone increasing in both depth and density."""
        return self._report(depth_m, bulk_density_kg_m3, surcharge_pa)["draft_n"] * self.radius_m

    def regulate_bite(self, bulk_density_kg_m3: float, *, surcharge_pa: float = 0.0) -> BiteSolution:
        """Solve for the CONTROL variable (bite depth) that holds the PROCESS variable (drum torque)
        on ``torque_setpoint_nm`` -- the steady state of the torque loop. Since the torque is monotone
        in depth, a bisection on the valid bite window [min_bite, max_cut] finds the unique root; when
        the setpoint is unreachable within the cap the bite SATURATES at the cap (bound respected).

        ``open_loop`` neuters the feedback (always the max bite), so the loop no longer holds the
        setpoint or adapts to density -- the non-vacuity witness."""
        lo, hi = self.min_bite_m, self.max_cut_m
        setpoint = float(self.torque_setpoint_nm)
        if self.open_loop:
            rep = self._report(hi, bulk_density_kg_m3, surcharge_pa)
            return BiteSolution(depth_m=hi, torque_nm=rep["draft_n"] * self.radius_m, saturated=True,
                                specific_energy_j_per_kg=rep["specific_energy_j_per_kg"],
                                bulk_density_kg_m3=float(bulk_density_kg_m3))
        t_hi = self.torque_at(hi, bulk_density_kg_m3, surcharge_pa=surcharge_pa)
        t_lo = self.torque_at(lo, bulk_density_kg_m3, surcharge_pa=surcharge_pa)
        if setpoint >= t_hi:                        # unreachable within the cap -> saturate at the cap
            depth, saturated = hi, True
        elif setpoint <= t_lo:                      # already over the setpoint at the floor bite
            depth, saturated = lo, False
        else:
            a, b = lo, hi
            for _ in range(60):                     # bisection to machine precision on a monotone plant
                mid = 0.5 * (a + b)
                if self.torque_at(mid, bulk_density_kg_m3, surcharge_pa=surcharge_pa) < setpoint:
                    a = mid
                else:
                    b = mid
            depth, saturated = 0.5 * (a + b), False
        rep = self._report(depth, bulk_density_kg_m3, surcharge_pa)
        return BiteSolution(depth_m=depth, torque_nm=rep["draft_n"] * self.radius_m, saturated=saturated,
                            specific_energy_j_per_kg=rep["specific_energy_j_per_kg"],
                            bulk_density_kg_m3=float(bulk_density_kg_m3))

    def is_stalled(self, bulk_density_kg_m3: float, *, rock_m: float = 0.0,
                   surcharge_pa: float = 0.0) -> tuple[bool, str]:
        """Whether the dig has stalled and needs intervention. Two grounded triggers: (1) a rock >= 10
        cm in the cut path (docs [BUCKLES]); (2) a drum overload -- even the shallowest productive bite
        (min_bite) exceeds the torque ceiling, so the drum cannot advance without stalling."""
        if float(rock_m) >= ROCK_HAZARD_M:
            return True, f"rock {float(rock_m) * 100:.0f} cm >= {ROCK_HAZARD_M * 100:.0f} cm in cut path -> stall"
        floor_torque = self.torque_at(self.min_bite_m, bulk_density_kg_m3, surcharge_pa=surcharge_pa)
        if floor_torque >= self.stall_ceiling_nm:
            return True, (f"drum overload: min-bite torque {floor_torque:.1f} N*m >= ceiling "
                          f"{self.stall_ceiling_nm:.1f} N*m -> stall")
        return False, "clear"


@dataclass(frozen=True)
class AutoDigObs:
    """One control tick: whether the rover is at the cut face, the DrumSensor-inferred fill, the
    in-situ regolith density under the drum, tip stability, and disturbance flags."""
    at_face: bool
    drum_kg: float
    bulk_density_kg_m3: float
    stable: bool                       # tip margin > 0 (stewie.physics.stability)
    rock_m: float = 0.0                # largest rock in the cut path [m]
    surcharge_pa: float = 0.0          # buried-rock bearing surcharge on the tool [Pa]


@dataclass(frozen=True)
class EffortRecord:
    """One dig pass's conserved EFFORT -- the AD-02 effort log entry (AD-02 generalises this into the
    per-actuator electrical observables I, V, tau, P, E)."""
    pass_idx: int
    phase: str
    bite_depth_m: float
    drum_torque_nm: float
    specific_energy_j_per_kg: float
    mass_kg: float
    mechanical_work_j: float
    bulk_density_kg_m3: float


def step(state: str, obs: AutoDigObs, controller: AutoDigController,
         sensor: _rm.DrumSensor) -> tuple[str, str]:
    """The gated AutoDig transition -> (next_state, reason). STALL/DONE are terminal. Guards first:
    a violated stability gate or a stall aborts the cycle before any transition (fail-safe)."""
    if state in _TERMINAL:
        return state, "terminal"
    # never excavate while unstable -- the #59 tip-over gate (same discipline as berm_fsm).
    if not obs.stable and state in (TRAVERSE, DIG, LIFT):
        return STALL, "tip margin <= 0 -> abort dig (unstable), needs intervention"
    # a rock hazard / drum overload stalls while approaching or cutting the face.
    if state in (TRAVERSE, DIG):
        stalled, why = controller.is_stalled(obs.bulk_density_kg_m3, rock_m=obs.rock_m,
                                             surcharge_pa=obs.surcharge_pa)
        if stalled:
            return STALL, why
    if state == TRAVERSE:
        if obs.at_face:
            return DIG, "arrived at the cut face -> dig (regulate torque via bite)"
        return TRAVERSE, "driving to the cut face"
    if state == DIG:
        if sensor.offload(obs.drum_kg).offload:
            return LIFT, "drum full (should_offload upper bound) -> lift the loaded drum"
        return DIG, "regulating the bite to the torque setpoint"
    if state == LIFT:
        return OFFLOAD, "raised the loaded drum -> offload"
    if state == OFFLOAD:
        return DONE, "offloaded -> handoff to berm_fsm (LOAD -> HAUL)"
    raise ValueError(f"unknown AutoDig state {state!r}")


def handoff_obs(drum_kg: float, *, target_kg: float = 25.0, stable: bool = True) -> BermObs:
    """Build the ``berm_fsm.BermObs`` the offload handoff hands up: a full drum, not yet at the build
    site, berm still under target -> the berm FSM steps LOAD -> HAUL."""
    return BermObs(drum_kg=float(drum_kg), at_site=False, placed_kg=0.0,
                   target_kg=float(target_kg), stable=bool(stable))


def run(observations, controller: AutoDigController, sensor: _rm.DrumSensor, *,
        start: str = TRAVERSE, target_kg: float = 25.0) -> dict:
    """Drive the AutoDig cycle over a stream of control ticks. One tick per observation; the
    deterministic LIFT -> OFFLOAD -> DONE tail is drained automatically once the drum offloads. Returns
    ``{final, trace, effort_log, offloaded, stalled, handoff}`` -- the effort log carries one
    conserved-effort record per DIG pass, and ``handoff`` is the ``BermObs`` for the berm FSM."""
    state = start
    trace: list[dict] = []
    effort: list[EffortRecord] = []
    prev_drum = 0.0
    last_obs: AutoDigObs | None = None
    for obs in observations:
        last_obs = obs
        nxt, reason = step(state, obs, controller, sensor)
        if state == DIG:                            # this tick is one regulated dig pass
            sol = controller.regulate_bite(obs.bulk_density_kg_m3, surcharge_pa=obs.surcharge_pa)
            mass = max(0.0, float(obs.drum_kg) - prev_drum)
            effort.append(EffortRecord(
                pass_idx=len(effort), phase=DIG, bite_depth_m=sol.depth_m,
                drum_torque_nm=sol.torque_nm, specific_energy_j_per_kg=sol.specific_energy_j_per_kg,
                mass_kg=mass, mechanical_work_j=sol.specific_energy_j_per_kg * mass,
                bulk_density_kg_m3=float(obs.bulk_density_kg_m3)))
        prev_drum = float(obs.drum_kg)
        if nxt != state:
            trace.append({"from": state, "to": nxt, "reason": reason})
        state = nxt
        if state in _TERMINAL:
            break
    # drain the deterministic lift/offload tail (does not consume fresh observations).
    while state in (LIFT, OFFLOAD) and last_obs is not None:
        nxt, reason = step(state, last_obs, controller, sensor)
        if nxt == state:
            break
        trace.append({"from": state, "to": nxt, "reason": reason})
        state = nxt
        if state in _TERMINAL:
            break
    offloaded = state == DONE
    return {
        "final": state,
        "trace": trace,
        "effort_log": effort,
        "offloaded": offloaded,
        "stalled": state == STALL,
        "handoff": handoff_obs(prev_drum, target_kg=target_kg) if offloaded else None,
    }
