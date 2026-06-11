"""#79 slice: the docking-autonomy state machine.

Drives the gated transitions over the DOCK_PHASES (lode.actions): APPROACH -> ALIGN -> DOCK ->
DOCKED, with every transition PERCEPTION-GATED (the #57 DockWithLander preconditions made
executable). Tag-lock + illumination + range + pose-error budget decide each step; tag loss or a
busted budget routes to ABORT (back off and retry), never a blind push. A pure state function:
step(state, obs) -> (next_state, reason); obs is what the perception stack reports this tick.
"""
from __future__ import annotations

from dataclasses import dataclass

from lode.actions import TAG_ACQUIRE_RANGE_M

#: pose-error gates [m] -- ALIGN closes the coarse error; DOCK is the final-contact tolerance.
ALIGN_TOL_M = 0.30
DOCK_TOL_M = 0.05

STATES = ("APPROACH", "ALIGN", "DOCK", "DOCKED", "ABORT")


@dataclass(frozen=True)
class DockObs:
    """One perception tick: is the lander tag locked, how far, how big the pose error, is it lit."""
    tag_visible: bool
    range_m: float
    pose_error_m: float
    illuminated: bool


def step(state: str, obs: DockObs) -> tuple:
    """The gated transition. Returns (next_state, reason). Terminal states (DOCKED/ABORT) hold."""
    if state in ("DOCKED", "ABORT"):
        return state, "terminal"
    # SHADOW or TAG LOSS aborts any in-progress dock -- the AprilTag is the only pose truth here.
    if not obs.illuminated:
        return ("APPROACH" if state == "APPROACH" else "ABORT",
                "site unlit: AprilTag cannot be acquired" if state == "APPROACH"
                else "lost illumination mid-dock -> abort, back off")
    if state in ("ALIGN", "DOCK") and not obs.tag_visible:
        return "ABORT", "tag-lock lost mid-dock -> abort, back off and re-acquire"
    if state == "APPROACH":
        if obs.tag_visible and obs.range_m <= TAG_ACQUIRE_RANGE_M:
            return "ALIGN", "tag acquired in range -> begin visual servo"
        return "APPROACH", f"closing to tag-acquire range ({obs.range_m:.0f} > {TAG_ACQUIRE_RANGE_M:.0f} m)"
    if state == "ALIGN":
        if obs.pose_error_m <= ALIGN_TOL_M:
            return "DOCK", f"aligned ({obs.pose_error_m:.2f} <= {ALIGN_TOL_M} m) -> final approach"
        return "ALIGN", f"servoing ({obs.pose_error_m:.2f} > {ALIGN_TOL_M} m)"
    if state == "DOCK":
        if obs.pose_error_m <= DOCK_TOL_M:
            return "DOCKED", f"contact within {DOCK_TOL_M} m -> docked"
        return "DOCK", f"final approach ({obs.pose_error_m:.3f} > {DOCK_TOL_M} m)"
    raise ValueError(f"unknown docking state {state!r}")


def run(observations, *, start: str = "APPROACH") -> dict:
    """Drive the FSM over a sequence of perception ticks. Returns the final state + the transition
    trace (the auditable record of WHY each step happened)."""
    state = start
    trace = []
    for obs in observations:
        nxt, reason = step(state, obs)
        if nxt != state:
            trace.append({"from": state, "to": nxt, "reason": reason})
        state = nxt
        if state in ("DOCKED", "ABORT"):
            break
    return {"final": state, "trace": trace, "docked": state == "DOCKED"}
