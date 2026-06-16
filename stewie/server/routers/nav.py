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


class FaultRequest(BaseModel):
    # NV-08: the telemetry signals the existing models produce; all optional (only what's supplied is checked)
    model_config = ConfigDict(extra="forbid")
    tip_margin_deg: float | None = Field(default=None, ge=-90.0, le=90.0)
    slip: float | None = Field(default=None, ge=0.0, le=1.0)
    loc_sigma_m: float | None = Field(default=None, ge=0.0, le=1e4)
    battery_frac: float | None = Field(default=None, ge=0.0, le=1.0)
    temp_c: float | None = Field(default=None, ge=-273.0, le=1000.0)
    actuator_ok: bool | None = None


class ExecutiveRequest(FaultRequest):
    # NV-09: the fault signals (inherited) + the executive's other monitored inputs + optional recovery
    # telemetry (NV-06/07) and a reactive replan scope (NV-05). extra='forbid' -> no hidden state rides in.
    command_acked: bool = True
    plan_accepted: bool = True
    progress_ratio: float | None = Field(default=None, ge=0.0, le=10.0)
    stall_duration_s: float | None = Field(default=None, ge=0.0, le=1e6)
    expected_progress_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    planner_failed: bool = False
    reactive_scope: str | None = Field(default=None, pattern=r"^(local|global)$")


_FAULT_KEYS = ("tip_margin_deg", "slip", "loc_sigma_m", "battery_frac", "temp_c", "actuator_ok")


@router.post("/nav/faults")
def post_faults(req: FaultRequest, _auth: None = Depends(require_auth)):
    """NV-08: classify the active fault state from the supplied telemetry (tip margin, slip, pose sigma,
    battery fraction, temperature, actuator status) -> the fault records + a safety-critical rollup."""
    from lode import faults as F
    active = F.classify_faults(**{k: getattr(req, k) for k in _FAULT_KEYS if getattr(req, k) is not None})
    return {"ok": True, "faults": active, "summary": F.fault_summary(active)}


@router.post("/nav/executive")
def post_executive(req: ExecutiveRequest, _auth: None = Depends(require_auth)):
    """NV-09: one autonomy executive step. Classifies faults (NV-08), folds in a recovery recommendation
    (NV-06/07, when the progress telemetry is supplied) and a reactive replan scope (NV-05), and returns
    the safe next action in strict precedence (fail_safe wins): fail_safe / pause / replan_global /
    reverse / persist / replan_local / continue -- the single decision the cockpit + autonomy loop call."""
    from lode import executive as EX
    from lode import faults as F
    from lode import recovery as R
    active = F.classify_faults(**{k: getattr(req, k) for k in _FAULT_KEYS if getattr(req, k) is not None})
    recovery = None
    pr, sd, ep = req.progress_ratio, req.stall_duration_s, req.expected_progress_ratio
    if pr is not None and sd is not None and ep is not None:
        recovery = R.recommend(float(pr), float(sd), float(ep), planner_failed=req.planner_failed)
    reactive = {"scope": req.reactive_scope} if req.reactive_scope else None
    out = EX.executive_step(faults=active, command_acked=req.command_acked, plan_accepted=req.plan_accepted,
                            recovery=recovery, reactive=reactive)
    return {"ok": True, **out, "faults": active, "fault_summary": F.fault_summary(active)}


class ReactRequest(BaseModel):
    # NV-05: observation-driven reactive replan; observation/geometry only (extra='forbid')
    model_config = ConfigDict(extra="forbid")
    pose: tuple[float, float]
    heading_rad: float = Field(ge=-7.0, le=7.0)
    goal: tuple[float, float]
    planned_path: list[tuple[float, float]] = Field(default_factory=list, max_length=4096)
    rocks: list[tuple[float, float, float]] = Field(default_factory=list, max_length=_MAX_OBSTACLES)  # observed (x,y,diameter_m)
    known_hazards: list[tuple[float, float]] = Field(default_factory=list, max_length=_MAX_OBSTACLES)
    keepouts: list[tuple[float, float, float]] = Field(default_factory=list, max_length=_MAX_OBSTACLES)
    sensor_range_m: float = Field(default=18.0, gt=0.0, le=1e4)
    deviation_max_m: float = Field(default=8.0, ge=0.0, le=1e4)
    clearance_m: float = Field(default=1.0, ge=0.0, le=100.0)
    horizon_m: float = Field(default=8.0, gt=0.0, le=1000.0)


@router.post("/nav/react")
def post_react(req: ReactRequest, _auth: None = Depends(require_auth)):
    """NV-05: reactive replan. Observed rocks (x, y, diameter) are classified into nav hazards; the D/E
    obstacles within sensor range become dynamic keep-outs and trigger a LOCAL replan (an NV-03 arc),
    escalating to GLOBAL when every local arc is blocked. An off-route deviation also triggers. Returns the
    decision (replan/scope), the updated keep-outs, the deviation, and the chosen local arc when feasible."""
    from dart.rock_taxonomy import classify
    from lode import reactive_nav as RN
    hazards = [(float(x), float(y), classify(diameter_m=float(d))) for x, y, d in req.rocks]
    known = [{"x": float(x), "y": float(y)} for x, y in req.known_hazards]
    keepouts = [(float(a), float(b), float(c)) for a, b, c in req.keepouts]
    path = [(float(x), float(y)) for x, y in req.planned_path]
    out = RN.react((float(req.pose[0]), float(req.pose[1])), float(req.heading_rad),
                   (float(req.goal[0]), float(req.goal[1])), planned_path=path, hazards_world=hazards,
                   known_hazards=known, keepouts=keepouts, sensor_range_m=float(req.sensor_range_m),
                   deviation_max_m=float(req.deviation_max_m), clearance_m=float(req.clearance_m),
                   horizon_m=float(req.horizon_m))
    plan = out.get("local_plan")
    arc = None
    if plan and plan.get("feasible"):
        arc = [[round(float(x), 4), round(float(y), 4), round(float(t), 5)] for x, y, t in plan["arc"]]
    return {"ok": True, "replan": out["replan"], "scope": out["scope"],
            "n_new_hazards": len(out["new_hazards"]), "deviation_m": round(out["deviation_m"], 3),
            "keepouts": [[round(k[0], 3), round(k[1], 3), round(k[2], 3)] for k in out["keepouts"]],
            "local_arc": arc}
