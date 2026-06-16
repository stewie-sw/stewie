"""Return-to-lander feasibility (#161).

The lander is the rover's safe haven: at its FURTHEST excursion the rover must still retain enough charge
to drive back to the lander before the battery dies. The required reserve is the return drive energy
(distance back * grounded drive J/m) plus an ADJUSTABLE buffer (``return_buffer_frac``) so the operator
can dial in how much margin to keep over the bare return. This is distinct from the planner's general
RESERVE_FRAC -- it is a lander-anchored safety constraint on the plan's reach.

PURE + parametric: the planner supplies the furthest reach from the lander, the energy already spent to
get there, the pack energy, and the grounded drive J/m (DRIVE_J_PER_M). No imports -> no planner cycle.
"""
from __future__ import annotations

import math

DEFAULT_RETURN_BUFFER_FRAC = 0.20   # [ASSUMPTION] keep 20% over the bare return energy; operator-adjustable


def return_distance_m(lander_xy: tuple, point_xy: tuple) -> float:
    """Straight-line distance from a point back to the lander [m]."""
    return math.hypot(float(point_xy[0]) - float(lander_xy[0]), float(point_xy[1]) - float(lander_xy[1]))


def furthest_reach_from_lander_m(lander_xy: tuple, waypoints_xy) -> float:
    """The worst-case return distance: the furthest any plan waypoint sits from the lander [m]."""
    return max((return_distance_m(lander_xy, p) for p in waypoints_xy), default=0.0)


def return_to_lander_feasible(*, furthest_reach_m: float, energy_spent_at_reach_j: float,
                              battery_j: float, drive_j_per_m: float,
                              return_buffer_frac: float = DEFAULT_RETURN_BUFFER_FRAC) -> dict:
    """At the furthest excursion, is the remaining charge >= the buffered return energy? Returns the
    feasibility verdict + the return energy, the buffered reserve, the remaining charge, and the margin."""
    if furthest_reach_m < 0:
        raise ValueError(f"furthest_reach_m must be >= 0 (got {furthest_reach_m})")
    if battery_j <= 0:
        raise ValueError(f"battery_j must be > 0 (got {battery_j})")
    if drive_j_per_m <= 0:
        raise ValueError(f"drive_j_per_m must be > 0 (got {drive_j_per_m})")
    if return_buffer_frac < 0:
        raise ValueError(f"return_buffer_frac must be >= 0 (got {return_buffer_frac})")
    return_energy_j = furthest_reach_m * drive_j_per_m
    reserve_j = return_energy_j * (1.0 + return_buffer_frac)
    remaining_j = battery_j - energy_spent_at_reach_j
    margin_j = remaining_j - reserve_j
    return {
        "feasible": margin_j >= 0.0,
        "return_distance_m": round(furthest_reach_m, 2),
        "return_energy_J": round(return_energy_j, 1),
        "buffer_frac": return_buffer_frac,
        "reserve_with_buffer_J": round(reserve_j, 1),
        "remaining_J": round(remaining_j, 1),
        "margin_J": round(margin_j, 1),
    }
