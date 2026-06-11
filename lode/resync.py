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


def forward_compare(mission, *, candidates=("auto", "nearest"), objective: str = "duration",
                    stem: str = "resync_fwd") -> dict:
    """Re-simulate the mission under each candidate solver input at wall speed and rank the
    outcomes. Returns every future WITH its numbers -- the comparison is the product, the
    recommendation is just the head of the ranking."""
    futures = []
    for algo in candidates:
        t0 = time.monotonic()
        _, _, totals = MP.run(mission, stem=f"{stem}_{algo}", algorithm=algo, objective=objective)
        futures.append({
            "algorithm": algo,
            "resolved": totals.get("resolved_algorithm", algo),
            "time_s": float(totals["time_s"]),
            "energy_MJ": round(float(totals["energy_J"]) / 1e6, 3),
            "recharges": totals.get("recharges"),
            "hazard_flags": len(totals.get("hazard_violations", [])) if isinstance(
                totals.get("hazard_violations"), list) else 0,
            "wall_s": round(time.monotonic() - t0, 3),      # the faster-than-realtime claim, measured
        })
    futures.sort(key=lambda f: f["time_s"] if objective in ("duration", "time") else f["energy_MJ"])
    return {"objective": objective, "futures": futures, "recommended": futures[0]["algorithm"]}
