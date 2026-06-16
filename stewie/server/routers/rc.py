"""RC command-path router (ARCH-3 / §21): the safety-relevant teleop command + telemetry surface,
isolated so the SF-01 watchdog seam reviews in one place. Owns its backend/watchdog/lock state; the
app includes this router. Auth comes from server.deps, the audit log from server.services -- no import
of the app module (no cycle)."""
from __future__ import annotations

import os
import threading
import time

from fastapi import APIRouter, Depends, HTTPException

from stewie.bridge import rc_contract as RC
from stewie.server import objects as OBJ
from stewie.server.deps import require_auth, require_role
from stewie.server.services import log_event

router = APIRouter()

_RC_BACKEND = RC.SimBackend(start_rc=(0.0, 0.0))
_RC_WATCHDOG = RC.SafingWatchdog(_RC_BACKEND, deadline_s=float(os.environ.get("STEWIE_RC_DEADLINE_S", "5")))
_RC_LOCK = threading.Lock()


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


@router.get("/rc/telemetry")
def rc_telemetry(_auth: None = Depends(require_auth)):
    """#66: drain the backend telemetry (Pose/Leg) + the SF-01 watchdog state. The watchdog ticks
    on every poll, so a stalled operator (no commands) auto-SAFEs within the deadline."""
    now = time.monotonic()
    with _RC_LOCK:
        tripped = _RC_WATCHDOG.tick(now=now)
        tlm = [t.__dict__ | {"kind": t.kind} for t in _RC_BACKEND.poll()]
    return {"ok": True, "telemetry": tlm, "watchdog": {"tripped": tripped,
            "deadline_s": _RC_WATCHDOG.deadline_s}}
