"""[REQ:RS-03] the receding-horizon navigation runtime loop.

One ``nav_tick`` takes the current pose/belief, updates against the local hazard costmap, (re)plans a
global route when it has none / is uncertain / the corridor is blocked, produces the local trajectory
(the next waypoint) EACH tick, and lowers ONLY the next bounded ``TrajectoryCommand`` (RS-01) -- never a
whole trajectory, never an unbounded speed. When there is no traversable corridor it RECOVERS (holds,
emits no motion command, and replans next tick) rather than crashing or driving blind. The route is a
real least-cost path over the hazard grid (``dart.hazard_map.plan_route``); the pose advance is real
kinematics; nothing here is a stub.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from stewie.contracts.runtime_spine import TrajectoryCommand

if TYPE_CHECKING:                              # [REQ:AP-01] type-only import: nav_loop is app-layer orchestration
    from dart.hazard_map import HazardMap      # (it composes DART) so it must not import dart at module load

#: the IPEx-class hard velocity cap [m/s]; a lowered command's speed is bounded to at most this.
V_CAP_MPS = 0.5


@dataclass(frozen=True)
class NavState:
    """The receding-horizon loop's belief/pose state between ticks (frozen; each tick returns a new one)."""
    x: float
    y: float
    goal_x: float
    goal_y: float
    route: tuple = ()            # remaining world-xy waypoints of the current global route
    tick: int = 0
    done: bool = False
    recovering: bool = False     # last tick found NO traversable corridor -> holding + replanning
    status: str = "driving"      # driving | recovering | arrived


def _dist(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(bx - ax, by - ay)


def nav_tick(state: NavState, hmap: HazardMap, *, v_max: float = 0.3, step_m: float = 0.5,
             goal_tol_m: float = 0.75, uncertain: bool = False,
             blocked: bool = False) -> tuple[NavState, TrajectoryCommand | None]:
    """Advance the loop by ONE receding-horizon tick. Returns ``(new_state, command_or_None)``.

    - arrived within ``goal_tol_m`` -> done, no command.
    - replans the global route when it has none, ``uncertain`` (belief diverged), ``blocked`` (the next
      step is occupied), or it was recovering.
    - no traversable corridor -> RECOVER: no motion command, hold pose, retry next tick.
    - otherwise -> lower EXACTLY ONE bounded ``TrajectoryCommand`` toward the next waypoint and advance
      the pose one ``step_m`` toward it (consuming the waypoint when reached).
    """
    v = min(float(v_max), V_CAP_MPS)                          # bounded: never exceed the hard cap
    if v <= 0.0:
        v = min(0.1, V_CAP_MPS)                               # a lowered command always has a positive speed
    if _dist(state.x, state.y, state.goal_x, state.goal_y) <= goal_tol_m:
        return replace(state, done=True, status="arrived", tick=state.tick + 1), None

    route = state.route
    if (not route) or uncertain or blocked or state.recovering:
        from dart.hazard_map import plan_route    # [REQ:AP-01] lazy: app-layer call, not a module-level dart edge
        route = tuple(plan_route(hmap, (state.x, state.y), (state.goal_x, state.goal_y)))

    if len(route) < 2:                                        # no corridor (or already at goal cell) -> recover
        return replace(state, route=(), recovering=True, status="recovering", tick=state.tick + 1), None

    nx, ny = route[1]                                         # the local trajectory target this tick
    r, c = hmap.world_to_rc(nx, ny)
    cmd = TrajectoryCommand(leg_id=state.tick, kind="goto", goal_row=float(r), goal_col=float(c),
                            v_max_mps=v, bounded=True)
    d = _dist(state.x, state.y, nx, ny)
    if d <= step_m:                                           # reached this waypoint -> consume it
        px, py, route = nx, ny, route[1:]
    else:                                                     # step one increment toward it (real kinematics)
        px = state.x + (nx - state.x) / d * step_m
        py = state.y + (ny - state.y) / d * step_m
    return replace(state, x=px, y=py, route=route, recovering=False, status="driving",
                   tick=state.tick + 1), cmd


def run_to_goal(state: NavState, hmap: HazardMap, *, max_ticks: int = 4000,
                **tick_kw) -> tuple[NavState, list[TrajectoryCommand]]:
    """Drive the receding-horizon loop until it arrives or ``max_ticks`` is hit. Returns the final state
    and the ordered list of bounded commands it lowered (one per driving tick; recovering ticks emit
    none). A convenience over ``nav_tick`` for callers/tests that want the whole traverse."""
    cmds: list[TrajectoryCommand] = []
    for _ in range(max_ticks):
        state, cmd = nav_tick(state, hmap, **tick_kw)
        if cmd is not None:
            cmds.append(cmd)
        if state.done:
            break
    return state, cmds
