"""Navigation router (ARCH-3; NV-03/04): the local-planner surface that makes the nav primitives reachable
from the cockpit. POST /nav/local_plan takes the rover pose+heading, a goal, and the JSON-expressible
obstacles (keep-out circles + sized rocks), samples a constant-curvature arc fan (local_planner.plan_local,
NV-03), and returns the best feasible arc plus the bounded drive command (track_plan, NV-04: v/omega +
expected speed/duration/progress). An all-blocked fan returns feasible=false so the caller re-routes
globally -- the planner never returns an unsafe arc (NV-01). Read-only compute (no state mutation, no rover
command) -> require_auth, not require_role. No app-module import (no cycle)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from stewie.server.deps import require_auth

router = APIRouter()
log = logging.getLogger("stewie.server")

_MAX_OBSTACLES = 512


class LocalPlanRequest(BaseModel):
    # NV-03/04 is observation/geometry only -- forbid extra keys so no truth/hidden-state field rides in.
    model_config = ConfigDict(extra="forbid")
    pose: tuple[float, float]                                       # current rover (x, y) [m]
    heading_rad: float = Field(ge=-7.0, le=7.0)                    # current heading [rad]
    goal: tuple[float, float]                                       # target (x, y) [m]
    keepouts: list[tuple[float, float, float]] = Field(default_factory=list, max_length=_MAX_OBSTACLES)
    rocks: list[tuple[float, float, float]] = Field(default_factory=list, max_length=_MAX_OBSTACLES)
    horizon_m: float = Field(default=8.0, gt=0.0, le=1000.0)        # arc length sampled ahead
    clearance_m: float = Field(default=1.0, ge=0.0, le=100.0)       # safety margin added to every obstacle
    v_max: float | None = Field(default=None, gt=0.0, le=10.0)      # override nominal drive speed
    omega_max: float | None = Field(default=None, gt=0.0, le=10.0)  # override max yaw rate


@router.post("/nav/local_plan")
def post_local_plan(req: LocalPlanRequest, _auth: None = Depends(require_auth)):
    """Plan one short-horizon local arc to the goal around the given obstacles, with its bounded drive
    command. Returns feasible=false (the global router takes over) when no arc clears the obstacles."""
    from lode import local_planner as LP
    keepouts = [(float(a), float(b), float(c)) for a, b, c in req.keepouts]
    rocks = [(float(a), float(b), float(c)) for a, b, c in req.rocks]
    try:
        plan = LP.plan_local((float(req.pose[0]), float(req.pose[1])), float(req.heading_rad),
                             (float(req.goal[0]), float(req.goal[1])), keepouts=keepouts, rocks=rocks,
                             horizon_m=float(req.horizon_m), clearance_m=float(req.clearance_m))
    except (ValueError, RuntimeError) as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
    if not plan["feasible"]:
        return {"ok": True, "feasible": False, "reason": plan["reason"],
                "n_sampled": plan["n_sampled"], "n_feasible": plan["n_feasible"]}
    tk = {k: v for k, v in (("v_max", req.v_max), ("omega_max", req.omega_max)) if v is not None}
    cmd = LP.track_plan(plan, **tk)
    arc = [[round(float(x), 4), round(float(y), 4), round(float(th), 5)] for x, y, th in plan["arc"]]
    return {"ok": True, "feasible": True, "curvature": plan["curvature"],
            "endpoint": [round(plan["endpoint"][0], 4), round(plan["endpoint"][1], 4)],
            "heading_end": round(plan["heading_end"], 5), "progress_m": round(plan["progress_m"], 4),
            "n_sampled": plan["n_sampled"], "n_feasible": plan["n_feasible"], "arc": arc,
            "command": {"v_cmd": round(cmd["v_cmd"], 5), "omega_cmd": round(cmd["omega_cmd"], 5),
                        "expected_speed_ms": round(cmd["expected_speed_ms"], 5),
                        "duration_s": round(cmd["duration_s"], 3), "arc_length_m": round(cmd["arc_length_m"], 4)}}
