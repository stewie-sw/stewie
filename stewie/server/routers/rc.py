"""RC command-path router (ARCH-3 / §21): the safety-relevant teleop command + telemetry surface,
isolated so the SF-01 watchdog seam reviews in one place. Owns its backend/watchdog/lock state; the
app includes this router. Auth comes from server.deps, the audit log from server.services -- no import
of the app module (no cycle)."""
from __future__ import annotations

import asyncio
import json
import os
import threading
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from stewie.bridge import rc_contract as RC
from stewie.server import objects as OBJ
from stewie.server.deps import require_auth, require_role
from stewie.server.services import log_event

router = APIRouter()

_RC_BACKEND = RC.SimBackend(start_rc=(0.0, 0.0))
_RC_WATCHDOG = RC.SafingWatchdog(_RC_BACKEND, deadline_s=float(os.environ.get("STEWIE_RC_DEADLINE_S", "5")))
_RC_LOCK = threading.Lock()

# #144 (PRD §16.7 / P20, autonomy seam): the LIVE ROS2 odometry the container's rover_executive_node
# pushes here (REP-103 metres, bridge.pose_to_odom-shaped). The cockpit live drive-map renders it as the
# real ROS-driven rover, distinct from the in-process SimBackend teleop. Latest-wins + a monotonic
# receive stamp so the cockpit can show staleness; one slot, no unbounded growth (Power-of-10).
_ROS_ODOM_LOCK = threading.Lock()
_ROS_ODOM: dict | None = None
_ROS_ODOM_RECV = 0.0


@router.post("/rc/command")
def rc_command(body: dict, identity: str = Depends(require_role("operator"))):
    """#66 / AG-02: submit an RC command (GoTo/Safe/SetSim) to the active backend through the SF-01
    watchdog. This is the real rover-command path -> operator+ required (a guest/trainee cannot drive
    the rover). SetSim (a training time-warp) is further DIRECTOR-only; GoTo/Safe need any operator+."""
    from stewie.server import auth as AUTH
    # AG-08 (PRD §7.12, END GOAL): a command issued FOR a mission may only target a PUBLISHED (live)
    # mission. operator+ is already enforced by the route gate; the SF-01 watchdog wraps submission
    # below; here we bar the sandbox -> a trainee's (or anyone's) sandbox draft can be simulated but is
    # structurally unable to be lowered to a real rover command. Low-level teleop carries no mission ref.
    mission = body.get("mission")
    if mission is not None and OBJ.load_mission(str(mission), namespace="live") is None:
        raise HTTPException(status_code=403, detail=f"mission {mission!r} is not published (live); only a "
                            "live mission can be commanded to the rover")
    kind = str(body.get("kind", "")).lower()
    now = time.monotonic()
    with _RC_LOCK:
        cmd: object
        if kind == "goto":
            cmd = RC.GoTo(leg_id=int(body.get("leg_id", 0)), goal_row=float(body["goal_row"]),
                          goal_col=float(body["goal_col"]), v_max_mps=float(body.get("v_max_mps", 0.3)),
                          goal_radius_cells=float(body.get("goal_radius_cells", 1.0)))
        elif kind == "safe":
            cmd = RC.Safe(reason=RC.SAFE_REASON_OPERATOR)
        elif kind == "setsim":
            if AUTH.role_of(identity) != "director":
                raise HTTPException(status_code=403, detail="SetSim (time-warp) is director-only")
            cmd = RC.SetSim(time_factor=float(body.get("time_factor", 1.0)))
        else:
            raise HTTPException(status_code=400, detail=f"unknown RC command kind {kind!r}")
        _RC_WATCHDOG.submit(cmd, now=now)
        log_event(identity, f"rc.{kind}", str(body.get("leg_id", "")))
    return {"ok": True, "accepted": kind, "watchdog_tripped": _RC_WATCHDOG.tripped}


@router.post("/rc/plan_ros")
def rc_plan_ros(body: dict, identity: str = Depends(require_role("operator"))):
    """NV-11 + NV-12 + AG-08: lower a LIVE mission's plan to the ROS2 command messages a Space ROS /
    Nav2 / MoveIt executive consumes (paths / motion / arm-drum / observation goals + replan events),
    framed on a versioned StreamSession (monotonic seq + backpressure + the SF-01 link-stall safe-stop).

    operator+ is enforced by the route gate; AG-08 bars the sandbox -- the mission MUST be a PUBLISHED
    (live) mission, so a trainee's draft can be simulated but is structurally unable to lower to a real
    rover. rclpy is not required here: the lowering returns message-shaped dicts the live ROS2 node
    publishes; this route is the product-path seam (NV-11/NV-12 egress under the AG-08 interlock)."""
    from lode import mission_planner as MP
    from lode import planner_views as PV
    from stewie.bridge.plan_lowering import lower_plan_ir
    from stewie.bridge.stream import StreamSession
    name = body.get("mission")
    if name is None:
        raise HTTPException(status_code=400, detail="plan_ros requires a 'mission' (the live mission to lower)")
    saved = OBJ.load_mission(str(name), namespace="live")
    if saved is None:                                     # AG-08: only a published (live) mission lowers to ROS
        raise HTTPException(status_code=403, detail=f"mission {name!r} is not published (live); only a live "
                            "mission can be lowered to rover ROS commands")
    lowered = lower_plan_ir(PV.plan_ir(MP.mission_from_dict(saved)))
    groups = ("paths", "motion_goals", "work_goals", "observation_goals", "replan_events")
    sess = StreamSession()
    now = time.monotonic()
    frames = [sess.send({"topic": g, "msg": m}, now=now) for g in groups for m in lowered[g]]
    log_event(identity, "rc.plan_ros", str(name))
    return {"ok": True, "plan_id": lowered["plan_id"], "ir_version": lowered["ir_version"],
            "frames": frames, "stream": sess.status(),
            "counts": {g: len(lowered[g]) for g in groups}}


class RosOdomFrame(BaseModel):
    """#144 tier-1: the rover's DEM-crop frame, so the cockpit only overlays it on the MAIN 3D view when
    the loaded DEM matches. dem_origin = the order-frame origin in DEM metres ([c0*cell, r0*cell])."""
    dem: str = Field(..., max_length=32)
    cell_m: float = Field(..., gt=0.0, le=1e4)
    dem_origin: tuple[float, float] = Field(...)


class RosOdomIngest(BaseModel):
    """#144: the live ROS2 odometry frame the rover node POSTs (REP-103 metres + yaw, optional state).
    Bounded (ge/le reject NaN/Inf too) so a malformed push can't poison the live operator view."""
    x_m: float = Field(..., ge=-1e7, le=1e7)
    y_m: float = Field(..., ge=-1e7, le=1e7)
    yaw_rad: float = Field(0.0, ge=-7.0, le=7.0)
    slip: float | None = Field(None, ge=0.0, le=1.0)
    soc: float | None = Field(None, ge=0.0, le=1.0)
    stamp_s: float | None = Field(None, ge=0.0)        # the producer's own clock (informational)
    mode: str | None = Field(None, max_length=16)      # tier-2: control mode (idle|cmd_vel|goal|safe)
    frame: RosOdomFrame | None = Field(None)           # tier-1: the rover's DEM-crop frame (for the 3D overlay)


@router.post("/rc/ros_odom")
def rc_ros_odom(body: RosOdomIngest, identity: str = Depends(require_role("operator"))):
    """#144 (PRD §16.7 / P20, autonomy seam, INGRESS): the live ROS2 container's rover_executive_node
    POSTs its /odom here so the cockpit live drive-map can render the REAL ROS-driven rover (distinct
    from the in-process SimBackend teleop). This is a WRITE to the live-ops view, so operator+ is
    required (the node authenticates as automation = api-key = operator+); a guest/trainee cannot inject
    a pose. Latest-wins, one slot. NOT a command path -- it only feeds the display, never the rover."""
    global _ROS_ODOM, _ROS_ODOM_RECV
    with _ROS_ODOM_LOCK:
        _ROS_ODOM = {"x_m": body.x_m, "y_m": body.y_m, "yaw_rad": body.yaw_rad,
                     "slip": body.slip, "soc": body.soc, "stamp_s": body.stamp_s, "mode": body.mode,
                     "frame": (body.frame.model_dump() if body.frame is not None else None)}
        _ROS_ODOM_RECV = time.monotonic()
    log_event(identity, "rc.ros_odom", f"{body.x_m:.1f},{body.y_m:.1f}")
    return {"ok": True}


def _ros_odom_snapshot(now: float) -> dict | None:
    """The latest live ROS odom + its age (staleness), or None if the node has never pushed."""
    with _ROS_ODOM_LOCK:
        if _ROS_ODOM is None:
            return None
        return _ROS_ODOM | {"age_s": max(0.0, now - _ROS_ODOM_RECV)}


def _telemetry_payload() -> dict:
    """#66: one telemetry frame -- drain the backend Pose/Leg + tick the SF-01 watchdog. The watchdog
    ticks on every drain, so a stalled operator (no commands) auto-SAFEs within the deadline."""
    now = time.monotonic()
    with _RC_LOCK:
        tripped = _RC_WATCHDOG.tick(now=now)
        tlm = [t.__dict__ | {"kind": t.kind} for t in _RC_BACKEND.poll()]
    # #230 step 3: the Pose is in grid (row, col) cells; cell_m lets the cockpit live drive-map convert to
    # REP-103 meters (x=col*cell_m, y=-row*cell_m -- bridge.frames). Without it the map is dimensionless.
    # #144: ros_odom is the live ROS2 rover's odometry (already REP-103 m), surfaced for the same map.
    return {"ok": True, "telemetry": tlm, "cell_m": _RC_BACKEND.cell_m,
            "ros_odom": _ros_odom_snapshot(now),
            "watchdog": {"tripped": tripped, "deadline_s": _RC_WATCHDOG.deadline_s}}


@router.get("/rc/telemetry")
def rc_telemetry(_auth: None = Depends(require_auth)):
    """#66: drain the backend telemetry (Pose/Leg) + the SF-01 watchdog state (one frame)."""
    return _telemetry_payload()


@router.get("/rc/telemetry/stream")
async def rc_telemetry_stream(interval_s: float = 1.0, max_frames: int | None = None,
                              _auth: None = Depends(require_auth)):
    """#230 live-ops: a Server-Sent-Events stream of the live RC telemetry (Pose/Leg) + the SF-01 watchdog,
    pushed every ``interval_s`` so the cockpit Execute console shows continuous live state instead of
    polling. The watchdog ticks on every frame, so the streaming drain itself keeps a live operator's
    deadline armed. Streams until the client disconnects (EventSource auto-reconnects); ``max_frames`` bounds
    it for finite clients + tests. require_auth (any operator+). One-way push only -- never a command path."""
    interval = max(0.1, min(float(interval_s), 10.0))

    async def _gen():
        n = 0
        while max_frames is None or n < max_frames:
            yield f"data: {json.dumps(_telemetry_payload())}\n\n"
            n += 1
            if max_frames is not None and n >= max_frames:
                break
            await asyncio.sleep(interval)

    return StreamingResponse(_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
