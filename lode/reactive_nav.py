"""NV-05: reactive replan. Closes the nav loop -- newly OBSERVED D/E rock hazards within sensor range are
folded into the dynamic keep-out set, and a replan is triggered (a new hazard, or the actual pose drifted
off the planned route past tolerance). The replan is tried LOCALLY first (an NV-03 constant-curvature arc
around the updated keep-outs); if every local arc is blocked it escalates to GLOBAL (the caller re-routes
on the hazard map). Pure geometry, built on path_track (detection) + local_planner (NV-03); never drives an
unsafe arc -- an all-blocked local fan returns scope='global', not a forced path.
"""
from __future__ import annotations

from lode.local_planner import plan_local
from lode.path_track import cross_track_deviation, discover_hazards


def hazards_to_keepouts(hazards, *, clearance_m: float = 1.0) -> list:
    """Convert discovered (x, y, Rock) hazards into keep-out circles (x, y, r). r = the rock's physical
    radius (diameter/2) + clearance -- a full ready-to-use keep-out, the same convention as the planner's
    mission keep-outs (so a downstream planner treats hazard and mission keep-outs uniformly)."""
    return [(float(x), float(y), float(rk.diameter_m) / 2.0 + clearance_m) for x, y, rk in hazards]


def react(pose, heading_rad: float, goal, *, planned_path=(), hazards_world=(), known_hazards=(),
          keepouts=(), is_blocked=None, sensor_range_m: float = 18.0, deviation_max_m: float = 8.0,
          clearance_m: float = 1.0, horizon_m: float = 8.0) -> dict:
    """One reactive step. Discover the newly-observed D/E hazards in sensor range, fold them into the active
    keep-out set, and decide the replan scope:

      * ``scope='none'``   -- no new hazard and still on-route: keep driving.
      * ``scope='local'``  -- a replan is needed and an NV-03 local arc avoids the updated keep-outs.
      * ``scope='global'`` -- a replan is needed but every local arc is blocked: the caller must re-route.

    Returns ``{replan, scope, new_hazards, keepouts (all active, ready-to-use circles), deviation_m,
    local_plan}``. ``known_hazards`` is the list of already-known keep-out/hazard dicts ({"x","y"}); a
    re-observed known hazard is not a fresh trigger. The local replan treats keep-outs as full circles
    (clearance is already baked in), so it passes clearance_m=0 to the NV-03 planner."""
    new = discover_hazards(pose, hazards_world, sensor_range_m=sensor_range_m, known=known_hazards)
    dev = 0.0
    if len(planned_path):
        _, _, dev = cross_track_deviation(planned_path, [pose])
    replan = bool(new) or dev > deviation_max_m
    active = list(keepouts) + hazards_to_keepouts(new, clearance_m=clearance_m)
    if not replan:
        return {"replan": False, "scope": "none", "new_hazards": new, "keepouts": active,
                "deviation_m": float(dev), "local_plan": None}
    plan = plan_local(pose, heading_rad, goal, keepouts=active, is_blocked=is_blocked,
                      horizon_m=horizon_m, clearance_m=0.0)        # keep-outs are already full circles
    return {"replan": True, "scope": "local" if plan["feasible"] else "global", "new_hazards": new,
            "keepouts": active, "deviation_m": float(dev),
            "local_plan": plan if plan["feasible"] else None}
