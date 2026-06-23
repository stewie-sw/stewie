"""#70 (rung 2): resync + faster-than-realtime forward comparison.

The honest architecture (PRD §18, PLANNING_REVISION): we do NOT need a learned world model --
the exact conserved authority IS the world model, and it steps in sub-milliseconds. What rung 2
adds is the LOOP: a real observation corrects the believed state (resync), and candidate futures
re-simulate from the corrected state and get COMPARED, not asserted.

    telemetry observation ──► resync(belief, obs)  (precision-weighted fuse; σ shrinks)
                                   │
                                   ▼
    forward_compare(mission, candidates) ── runs each candidate solver input through the real
    planner/simulator at wall speeds ≫ realtime ── ranked outcomes + a recommendation the
    operator can argue with.
"""
from __future__ import annotations

import dataclasses
import time

from lode import mission_planner as MP


def resync_se2(belief, *, between=None, imu_yaw=None, observations=None, yaw0: float = 0.0):
    """#78: the SE(2) resync path -- fuse body-frame odometry (between), a gyro-preintegrated yaw
    factor (imu_yaw=(dyaw, sigma)), and absolute (x,y) fixes into one heading-aware estimate. Returns
    (x, y, yaw, xy_sigma, yaw_sigma) for the latest node. The orientation-aware successor to
    resync_graph; full SE(3) (z/roll/pitch) is only needed off the ground plane."""
    from dart.pose_graph_se2 import PoseGraphSE2
    g = PoseGraphSE2()
    g.add_prior(0, (belief.x, belief.y, yaw0), sigma_xy=max(1e-6, belief.pos_sigma_m), sigma_yaw=0.3)
    if between is not None:
        g.add_between(0, 1, between[0], sigma_xy=between[1], sigma_yaw=between[2])
        last = 1
    else:
        last = 0
    if imu_yaw is not None and last == 1:
        g.add_imu_yaw(0, 1, imu_yaw[0], sigma=imu_yaw[1])
    for o in (observations or []):
        g.add_absolute(last, (float(o["x"]), float(o["y"])), sigma=float(o.get("pos_sigma_m", 0.5)))
    out = g.optimize_with_cov()
    p = out["pose"][last]
    return {"x": p[0], "y": p[1], "yaw": p[2], "xy_sigma": out["xy_sigma"][last],
            "yaw_sigma": out["yaw_sigma"][last]}


def resync_graph(belief, observations: list):
    """#78: the GRAPH path -- fuse MULTIPLE absolute factors (DEM-registration + shadow-outline
    fixes) against the odometry prior in one windowed least-squares solve (dart.pose_graph),
    returning the corrected belief + shrunk sigma. This supersedes the 1-D resync() below for
    the multi-factor case; resync() stays as the single-observation fast path. ``observations``:
    [{x, y, pos_sigma_m}, ...]."""
    from dart.pose_graph import PoseGraph
    g = PoseGraph()
    g.add_prior(0, (belief.x, belief.y), sigma=max(1e-6, belief.pos_sigma_m))
    for o in observations:
        g.add_absolute(0, (float(o["x"]), float(o["y"])), sigma=float(o.get("pos_sigma_m", 0.5)))
    out = g.optimize_with_cov()
    return dataclasses.replace(belief, x=out["pose"][0][0], y=out["pose"][0][1],
                               pos_sigma_m=out["sigma"][0])


def resync(belief, observation: dict):
    """Fuse an independent pose observation into the believed state (precision-weighted, the
    standard 1-D fuse per axis -- honest about what it is; the windowed multi-factor version is
    resync_graph; full SE(3) + IMU preintegration is the next slice)."""
    ox, oy = float(observation["x"]), float(observation["y"])
    osig = max(1e-6, float(observation.get("pos_sigma_m", 0.5)))
    bsig = max(1e-6, float(belief.pos_sigma_m))
    w = (1.0 / bsig**2) / (1.0 / bsig**2 + 1.0 / osig**2)   # weight on the BELIEF
    fused_x = w * belief.x + (1.0 - w) * ox
    fused_y = w * belief.y + (1.0 - w) * oy
    fused_sig = (1.0 / (1.0 / bsig**2 + 1.0 / osig**2)) ** 0.5
    return dataclasses.replace(belief, x=fused_x, y=fused_y, pos_sigma_m=fused_sig)


def _objective_key(objective: str):
    """The within-group sort key for a future, by the chosen objective (duration/time -> time_s,
    else energy). Used by both forward_compare and rank_feasible_first so the two agree."""
    if objective in ("duration", "time"):
        return lambda f: f.get("time_s", float("inf"))
    return lambda f: f.get("energy_MJ", float("inf"))


def rank_feasible_first(futures: list, *, objective: str = "duration") -> list:
    """Mission-ops screen-2 INVARIANT: a feasible candidate is ALWAYS ranked above an infeasible one,
    regardless of how the infeasible candidate scores on the raw objective. Within each feasibility
    group the order is best-first on the objective. A pure, stable two-key sort -- no weighted score
    can ever float an infeasible future above a feasible one."""
    key = _objective_key(objective)
    # sort key: feasible(=False=0) groups ahead of infeasible(=True=1); then objective best-first.
    return sorted(futures, key=lambda f: (not bool(f.get("feasible", True)), key(f)))


def forward_compare(mission, *, candidates=("auto", "nearest"), objective: str = "duration",
                    stem: str = "resync_fwd") -> dict:
    """Re-simulate the mission under each candidate solver input at wall speed and rank the
    outcomes FEASIBLE-FIRST. Returns every future WITH its numbers -- the comparison is the product;
    the recommendation is the head of the feasible-first ranking (None when no candidate is feasible).
    Every field is read straight from the conserved planner totals (no fabricated numbers)."""
    futures = []
    n_orders = len(getattr(mission, "orders", []) or [])
    for algo in candidates:
        t0 = time.monotonic()
        # CP-04: when the mission carries a COMPILED as-built acceptance tolerance (MO-01 AcceptanceCriterion
        # -> Mission.accept_flatness_tol_m), exercise it on this LIVE REHEARSE path -- plan with_acceptance so
        # validate_plan honors the COMPILED tolerance, then surface its as-built verdict in the future. No
        # compiled tolerance -> with_acceptance=False -> byte-identical (no extra work, no new field).
        _accept = getattr(mission, "accept_flatness_tol_m", None) is not None
        result = MP.plan(mission, algorithm=algo, objective=objective, with_acceptance=_accept)
        _, _, totals = MP.run(mission, stem=f"{stem}_{algo}", result=result)   # reuse the result (RB-03; no recompute)
        rtl = totals.get("return_to_lander") or {}
        fut = {
            "algorithm": algo,
            "resolved": totals.get("resolved_algorithm", algo),
            "optimality": totals.get("optimality"),
            "objective_exact": bool(totals.get("objective_exact", False)),
            "time_s": float(totals["time_s"]),
            "energy_MJ": round(float(totals["energy_J"]) / 1e6, 3),
            "recharges": totals.get("recharges"),
            "charges": int(totals.get("charges", totals.get("recharges", 0)) or 0),
            # feasibility FIRST: the conserved planner's combined route+battery verdict (#161/C-04).
            "feasible": bool(totals.get("feasible", True)),
            "infeasible_reasons": list(totals.get("infeasible_reasons", []) or []),
            "return_to_lander": rtl,                         # #161 margin/feasibility, carried verbatim
            # objective completion: how many of the mission's orders the plan resolves into work.
            "objectives_total": n_orders,
            "blocked_legs": int(totals.get("blocked_legs", 0) or 0),
            "hazard_flags": len(totals.get("hazard_violations", [])) if isinstance(
                totals.get("hazard_violations"), list) else 0,
            "wall_s": round(time.monotonic() - t0, 3),      # the faster-than-realtime claim, measured
        }
        if _accept and isinstance(result.validation, dict):   # CP-04: the compiled-tolerance as-built verdict, on the live path
            fut["as_built_pass"] = bool(result.validation.get("as_built_pass"))
            _tol = result.validation.get("as_built_tol_m")
            fut["as_built_tol_m"] = float(_tol) if _tol is not None else None
        futures.append(fut)
    futures = rank_feasible_first(futures, objective=objective)
    recommended = futures[0]["algorithm"] if futures and futures[0]["feasible"] else None
    return {"objective": objective, "futures": futures, "recommended": recommended}
