"""#79 slice: the berm-building autonomy state machine.

Drives the conserved cut-haul-fill cycle (column_state cut_to_inventory -> drum -> fill_toward) as
a gated FSM: LOAD -> HAUL -> DUMP -> (repeat until the berm target mass is placed) -> GRADE -> DONE.
The same discipline as the docking FSM: every transition is gated by a real signal --
  LOAD->HAUL : the drum is full enough to be worth hauling (should_offload upper-bound logic)
  HAUL->DUMP : arrived at the build site AND the rover is stable (tip margin > 0)
  DUMP->LOAD : berm not yet at target mass -> go cut more
  DUMP->GRADE: target mass placed -> smooth the berm
  any->ABORT : tip-over risk (stability margin <= 0) -- never dump while unstable.
Mass is conserved by the authority; this commands, it never writes terrain. A pure
step(state, obs) -> (next, reason); run() drives a cycle sequence + the auditable trace.
"""
from __future__ import annotations

from dataclasses import dataclass

from stewie.physics.rassor_mass_model import REGOLITH_PER_CYCLE_KG

#: a drum is "worth hauling" at >= this fraction of capacity (avoid trips with a near-empty drum).
HAUL_FRACTION = 0.8


@dataclass(frozen=True)
class BermObs:
    """One cycle tick: drum fill, distance to the build site, placed-vs-target berm mass, stability."""
    drum_kg: float
    at_site: bool
    placed_kg: float
    target_kg: float
    stable: bool                     # tip margin > 0 (from stewie.physics.stability)


def step(state: str, obs: BermObs) -> tuple:
    """The gated transition. Returns (next_state, reason). DONE/ABORT are terminal."""
    if state in ("DONE", "ABORT"):
        return state, "terminal"
    # never operate while unstable -- a dump or dig that could tip aborts (the #59 stability gate).
    if not obs.stable and state in ("HAUL", "DUMP"):
        return "ABORT", "tip margin <= 0 -> abort, do not dump while unstable"
    if state == "LOAD":
        if obs.drum_kg >= HAUL_FRACTION * REGOLITH_PER_CYCLE_KG:
            return "HAUL", f"drum {obs.drum_kg:.1f} kg >= {HAUL_FRACTION:.0%} cap -> haul to site"
        return "LOAD", f"cutting ({obs.drum_kg:.1f} kg < {HAUL_FRACTION:.0%} of {REGOLITH_PER_CYCLE_KG:.0f} kg)"
    if state == "HAUL":
        if obs.at_site:
            return "DUMP", "arrived at the build site (stable) -> dump"
        return "HAUL", "driving to the build site"
    if state == "DUMP":
        if obs.placed_kg >= obs.target_kg:
            return "GRADE", f"berm at target ({obs.placed_kg:.1f} >= {obs.target_kg:.1f} kg) -> grade"
        return "LOAD", f"berm under target ({obs.placed_kg:.1f} < {obs.target_kg:.1f} kg) -> cut more"
    if state == "GRADE":
        return "DONE", "berm graded to profile -> done"
    raise ValueError(f"unknown berm state {state!r}")


def run(observations, *, start: str = "LOAD") -> dict:
    state = start
    trace = []
    for obs in observations:
        nxt, reason = step(state, obs)
        if nxt != state:
            trace.append({"from": state, "to": nxt, "reason": reason})
        state = nxt
        if state in ("DONE", "ABORT"):
            break
    return {"final": state, "trace": trace, "built": state == "DONE"}
