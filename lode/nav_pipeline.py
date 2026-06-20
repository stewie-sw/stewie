"""FS-05 end-to-end navigation spine: the ONE executable loop that CONNECTS the contract's on-host nav
stages into a single receding-horizon drive, instead of leaving them as nine seams that merely import.

The FS-05 contract (``planner_routing.navigation_contract``) verifies each stage's seam is importable and
callable; ``autonomy.run_closed_loop`` runs the MISSION-level belief loop (route geometry -> energy ->
map-channel). Neither one actually DRIVES a route through ``plan_local`` -> ``track_plan`` -> integrate ->
``recovery_needed``. This module is that missing connection -- the navigation spine that turns the named
stages into a running closed loop:

    global_route        route_leg(...)            -- terrain + keep-out + drop-off aware global corridor
    local_trajectory    plan_local(...)           -- per-tick constant-curvature fan toward a pure-pursuit carrot
    tracker             track_plan(...)            -- bounded twist (cmd_vel) for the chosen arc
    (integrate)         constant_curvature_arc(...) -- exact unicycle step by one control tick
    recovery            recovery_needed(...)        -- stall / planner-failure backup + reorient
    deviation           cross_track_deviation(...)  -- executed path vs the planned route (path_track)

The spine core (``drive_route``) is pure geometry with INJECTED predicates -- ``is_blocked(x,y)`` and
``speed_scale_fn(x,y)`` -- exactly the decoupling ``plan_local`` already uses, so it has no DEM/coordinate
dependency and is testable in isolation. ``run_navigation`` wires those predicates to the REAL DEM
(``slope_costmap`` slope/drop-off hazard + the system slip ladder) and runs the global route first, so the
local spine sees the SAME terrain the global router did. No fabricated terrain, slip, or pose: heights come
from the real DEM, slip from the sourced ladder, the executed pose from the exact unicycle integral.
"""
# PROVENANCE: STEWIE DART/LODE subsystem (A. Storey)
from __future__ import annotations

import math
from collections import deque

import numpy as np

from lode.local_planner import (
    DEFAULT_OMEGA_MAX,
    constant_curvature_arc,
    plan_local,
    track_plan,
)
from lode.path_track import cross_track_deviation
from lode.planner_routing import MAX_DROP_M, route_leg, slope_costmap, slope_deg_map
from lode.recovery import recovery_needed
from stewie.specs import ipex_specs as S


def dem_blocked_predicate(dem, dem_origin=(0.0, 0.0), *, max_slope_deg=25.0, slip_alpha=2.0,
                          max_drop_m=MAX_DROP_M):
    """Build ``is_blocked(x_local, y_local) -> bool`` from the REAL DEM's slope/drop-off hazard map -- the
    SAME ``slope_costmap`` the global router (``route_leg``) routes against, so the local planner rejects
    exactly the cells the global corridor avoided. A point off the mapped tile is blocked (the rover may not
    drive onto unmapped terrain). LOCAL coords map to world via ``+dem_origin`` (the M11 anchoring)."""
    Z, cell = dem[0], float(dem[1])
    ox, oy = dem_origin
    _cost, passable = slope_costmap(Z, cell, max_slope_deg=max_slope_deg, slip_alpha=slip_alpha,
                                    max_drop_m=max_drop_m)
    H, W = passable.shape

    def is_blocked(x_local: float, y_local: float) -> bool:
        c = int(round((ox + x_local) / cell))
        r = int(round((oy + y_local) / cell))
        if not (0 <= r < H and 0 <= c < W):
            return True
        return not bool(passable[r, c])

    return is_blocked


def dem_speed_scale_fn(dem, dem_origin=(0.0, 0.0), *, slip_model=None):
    """Build ``speed_scale_fn(x_local, y_local) -> (0,1]`` = ``1 - slip`` at the rover's real terrain slope,
    using the system slip ladder (NOT a fabricated derate -- ``track_arc`` explicitly forbids inventing
    slip). ``slip_model`` defaults to ``mission_planner.slip_alpha_to_slip`` (the same function the executor
    and energy model use); injectable for tests. A flat cell -> scale 1.0; a 15-deg cell -> ~0.88."""
    if slip_model is None:
        from lode.mission_planner import slip_alpha_to_slip as slip_model
    Z, cell = dem[0], float(dem[1])
    ox, oy = dem_origin
    smap = slope_deg_map(Z, cell)
    H, W = smap.shape

    def speed_scale_fn(x_local: float, y_local: float) -> float:
        c = int(round((ox + x_local) / cell))
        r = int(round((oy + y_local) / cell))
        if not (0 <= r < H and 0 <= c < W):
            return 1.0
        slip = float(slip_model(float(smap[r, c])))
        return float(min(1.0, max(0.05, 1.0 - slip)))

    return speed_scale_fn


def _carrot(waypoints, pose, idx, lookahead_m):
    """Pure-pursuit carrot: advance the route index past every waypoint already within ``lookahead_m`` of
    the rover and return (new_idx, carrot_xy). The carrot is the first waypoint beyond the lookahead (or the
    final waypoint), so the local planner always aims ~lookahead ahead along the planned corridor rather than
    stuttering on the dense (one-per-cell) route polyline. Monotonic: the index never moves backward."""
    i = int(idx)
    while i + 1 < len(waypoints) and math.hypot(pose[0] - waypoints[i][0], pose[1] - waypoints[i][1]) < lookahead_m:
        i += 1
    return i, waypoints[i]


def _backup_recover(pose, heading, target, *, backup_m):
    """NV-06 backup recovery action: reverse ``backup_m`` opposite the current heading, then reorient toward
    the carrot. Frees the rover from a local trap (all-arcs-blocked or a low-progress stall) and re-aims it so
    the next ``plan_local`` samples a fresh fan from a new pose. Returns (new_pose, new_heading)."""
    nx = pose[0] - backup_m * math.cos(heading)
    ny = pose[1] - backup_m * math.sin(heading)
    new_heading = math.atan2(target[1] - ny, target[0] - nx)
    return (nx, ny), new_heading


def drive_route(waypoints, *, is_blocked=None, speed_scale_fn=None, rocks=(), keepouts=(),
                v_max=S.DRIVE_SPEED_MS, omega_max=DEFAULT_OMEGA_MAX, dt=1.0, horizon_m=8.0,
                lookahead_m=6.0, clearance_m=1.0, goal_tol_m=2.0, max_ticks=4000,
                stall_window=5, progress_thresh=0.25, min_stall_s=2.0, backup_m=2.0,
                max_recoveries=40):
    """Drive a planned route to its final waypoint as a receding-horizon closed loop, connecting the FS-05
    local stages. Each control tick: ``plan_local`` a constant-curvature fan toward the pure-pursuit carrot;
    if feasible, ``track_plan`` it to a bounded twist and integrate the pose forward one tick along the chosen
    arc (exact unicycle); if EVERY arc is blocked, ``recovery_needed`` fires on the planner failure. A
    sustained low ratio of goal-ward headway to commanded distance also trips ``recovery_needed`` (a stall);
    recovery backs up + reorients. Terminates on arrival (within ``goal_tol_m`` of the last waypoint), on the
    tick budget, or when recovery cannot escape (``scope='global'`` -- the caller must re-route).

    Pure geometry: ``is_blocked``/``speed_scale_fn`` are injected (the DEM wiring lives in ``run_navigation``).
    Returns the executed ``trajectory`` ((N,2)), the per-tick ``twists`` (the cmd_vel egress), ``recovery_events``,
    ``arrived``, ``reason``, the stages exercised, and tick/call counts."""
    if len(waypoints) < 2:
        raise ValueError("drive_route needs at least a start and a goal waypoint")
    wps = [(float(x), float(y)) for x, y in waypoints]
    goal = wps[-1]
    pose = wps[0]
    idx, carrot = _carrot(wps, pose, 0, lookahead_m)
    heading = math.atan2(carrot[1] - pose[1], carrot[0] - pose[0])
    traj = [pose]
    twists: list = []
    recovery_events: list = []
    stages: set = set()
    ratios: deque = deque(maxlen=stall_window)
    low_progress_s = 0.0
    local_calls = track_calls = n_recover = 0
    arrived = False
    reason = "tick_budget"

    for tick in range(max_ticks):
        if math.hypot(pose[0] - goal[0], pose[1] - goal[1]) <= goal_tol_m:
            arrived, reason = True, "arrived"
            break
        idx, carrot = _carrot(wps, pose, idx, lookahead_m)

        # ---- local_trajectory ----
        plan = plan_local(pose, heading, carrot, is_blocked=is_blocked, keepouts=keepouts, rocks=rocks,
                          clearance_m=clearance_m, horizon_m=horizon_m)
        local_calls += 1
        stages.add("local_trajectory")

        if not plan["feasible"]:
            # ---- recovery (planner failure: no safe arc) ----
            low_progress_s += dt
            rec = recovery_needed(0.0, low_progress_s, planner_failed=True,
                                  progress_thresh=progress_thresh, min_stall_s=min_stall_s)
            stages.add("recovery")
            n_recover += 1
            if n_recover > max_recoveries:
                reason = "stuck_needs_global_reroute"
                break
            pose, heading = _backup_recover(pose, heading, carrot, backup_m=backup_m)
            recovery_events.append({"tick": tick, "reason": rec["reason"], "scope": "global",
                                    "pose": pose})
            traj.append(pose)
            ratios.clear()
            continue

        # ---- tracker (bounded twist = cmd_vel) ----
        scale = float(speed_scale_fn(pose[0], pose[1])) if speed_scale_fn is not None else 1.0
        twist = track_plan(plan, v_max=v_max, omega_max=omega_max, speed_scale=scale)
        track_calls += 1
        stages.add("tracker")
        twists.append({"v": twist["v_cmd"], "omega": twist["omega_cmd"], "dt": dt,
                       "speed_scale": scale})

        # ---- integrate one control tick along the chosen arc (exact unicycle) ----
        step_d = min(twist["expected_speed_ms"] * dt, float(twist["arc_length_m"]))
        seg = constant_curvature_arc(pose[0], pose[1], heading, float(plan["curvature"]), step_d, n_pts=2)
        new_pose = (float(seg[-1, 0]), float(seg[-1, 1]))
        new_heading = float(seg[-1, 2])

        # goal-ward headway vs commanded distance -> the recovery stall signal
        commanded = max(step_d, 1e-6)
        goalward = (math.hypot(pose[0] - goal[0], pose[1] - goal[1])
                    - math.hypot(new_pose[0] - goal[0], new_pose[1] - goal[1]))
        ratios.append(max(0.0, goalward) / commanded)
        pose, heading = new_pose, new_heading
        traj.append(pose)

        # ---- recovery (sustained low progress) ----
        wmean = sum(ratios) / len(ratios)
        if len(ratios) == ratios.maxlen and wmean < progress_thresh:
            low_progress_s += dt
        else:
            low_progress_s = 0.0
        rec = recovery_needed(wmean, low_progress_s, planner_failed=False,
                              progress_thresh=progress_thresh, min_stall_s=min_stall_s)
        stages.add("recovery")
        if rec["recover"]:
            n_recover += 1
            if n_recover > max_recoveries:
                reason = "stuck_needs_global_reroute"
                break
            pose, heading = _backup_recover(pose, heading, carrot, backup_m=backup_m)
            recovery_events.append({"tick": tick, "reason": rec["reason"], "scope": "local",
                                    "pose": pose})
            traj.append(pose)
            ratios.clear()
            low_progress_s = 0.0

    return {
        "arrived": arrived,
        "reason": reason,
        "trajectory": np.asarray(traj, dtype=float),
        "twists": twists,
        "recovery_events": recovery_events,
        "n_ticks": len(twists),
        "local_calls": local_calls,
        "track_calls": track_calls,
        "n_recoveries": len(recovery_events),
        "stages": sorted(stages),
    }


def run_navigation(dem, dem_origin, start_xy, goal_xy, *, keepouts=(), rocks=(),
                   max_slope_deg=25.0, slip_alpha=2.0, margin_m=20.0,
                   v_max=S.DRIVE_SPEED_MS, omega_max=DEFAULT_OMEGA_MAX, dt=1.0, horizon_m=8.0,
                   lookahead_m=6.0, clearance_m=1.0, goal_tol_m=2.0, max_ticks=4000):
    """The FS-05 end-to-end navigation pipeline on the REAL DEM: route the global corridor, then DRIVE it.

    Stage 1 ``global_route`` -- ``route_leg`` finds the terrain/keep-out/drop-off-aware corridor from
    ``start_xy`` to ``goal_xy`` (LOCAL coords anchored by ``dem_origin``). If no corridor exists the pipeline
    reports ``reached=False`` (the honest infeasible, never a straight line through the hazard).

    Stages 2-5 -- ``drive_route`` follows the corridor with ``plan_local`` -> ``track_plan`` -> integrate ->
    ``recovery_needed``, wired to the REAL DEM via ``dem_blocked_predicate`` (the same slope/drop-off hazard
    the router used) and ``dem_speed_scale_fn`` (the sourced slip ladder). Then ``cross_track_deviation``
    (path_track) measures the executed path against the planned route.

    Returns ``reached`` (a corridor existed), ``arrived`` (the drive reached the goal), the global
    ``waypoints`` + ``routed_m``, the executed ``trajectory`` + cmd_vel ``twists`` (the ROS egress stream),
    ``deviation`` (mean/max cross-track m), ``recovery_events``, and the ``stages`` exercised."""
    routed_m, straight_m, reached, waypoints = route_leg(
        dem, dem_origin, start_xy, goal_xy, max_slope_deg=max_slope_deg, slip_alpha=slip_alpha,
        margin_m=margin_m, keepouts=keepouts)
    if not reached or len(waypoints) < 2:
        return {"reached": False, "arrived": False, "reason": "no global corridor",
                "waypoints": [tuple(w) for w in waypoints], "routed_m": float(routed_m),
                "straight_m": float(straight_m), "trajectory": np.empty((0, 2)), "twists": [],
                "recovery_events": [], "deviation": {"mean_m": 0.0, "max_m": 0.0},
                "stages": ["global_route"]}

    is_blocked = dem_blocked_predicate(dem, dem_origin, max_slope_deg=max_slope_deg, slip_alpha=slip_alpha)
    speed_scale_fn = dem_speed_scale_fn(dem, dem_origin)
    # route_leg snaps the goal to its DEM cell; extend the corridor by the literal requested goal so the
    # drive finishes at goal_xy (and `arrived` is measured against the true goal, not the snapped cell).
    route = [tuple(w) for w in waypoints]
    gx, gy = float(goal_xy[0]), float(goal_xy[1])
    if math.hypot(route[-1][0] - gx, route[-1][1] - gy) > 1e-6:
        route.append((gx, gy))
    drive = drive_route(route, is_blocked=is_blocked, speed_scale_fn=speed_scale_fn, rocks=rocks,
                        keepouts=keepouts, v_max=v_max, omega_max=omega_max, dt=dt, horizon_m=horizon_m,
                        lookahead_m=lookahead_m, clearance_m=clearance_m, goal_tol_m=goal_tol_m,
                        max_ticks=max_ticks)

    _dev, dev_mean, dev_max = cross_track_deviation(route, drive["trajectory"])
    stages = ["global_route", *drive["stages"], "deviation"]
    return {
        "reached": True,
        "arrived": drive["arrived"],
        "reason": drive["reason"],
        "waypoints": [tuple(w) for w in waypoints],
        "routed_m": float(routed_m),
        "straight_m": float(straight_m),
        "trajectory": drive["trajectory"],
        "twists": drive["twists"],
        "recovery_events": drive["recovery_events"],
        "n_recoveries": drive["n_recoveries"],
        "deviation": {"mean_m": float(dev_mean), "max_m": float(dev_max)},
        "n_ticks": drive["n_ticks"],
        "local_calls": drive["local_calls"],
        "track_calls": drive["track_calls"],
        "stages": sorted(set(stages)),
    }
