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


def resync(belief, observation: dict):
    """Fuse an independent pose observation into the believed state (precision-weighted, the
    standard 1-D fuse per axis -- honest about what it is; a full ESKF is the P15 track).
    ``observation``: {x, y, pos_sigma_m}."""
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
