"""Session router (ARCH-3): the B3 operator/director training sessions -- start a closed-loop run
(server-side, on the chosen-site DEM) plus the two-view reads (the operator-shaped view vs the
director-truth scorecard/debrief) and the persisted summary. Session state is owned by
server.session (SES); the site DEM comes from server.state; the mission parse from
lode.mission_planner (lazy). No app-module import (no cycle)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict

from stewie.server import session as SES
from stewie.server import state
from stewie.server.deps import require_auth, require_director
from stewie.server.services import log_event

router = APIRouter()


class SessionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")           # mission dict + optional profile
    name: str = "session"
    profile: str = "ideal"


@router.post("/session/start")
def session_start(req: SessionRequest, _auth: str = Depends(require_auth)):
    from lode import mission_planner as MP
    body = req.model_dump()
    profile = body.pop("profile", "ideal")
    mission_t0_s = float(body.pop("mission_t0_s", 0.0) or 0.0)
    try:
        mission = MP.mission_from_dict(body)
        dem, origin = state.moon_dem(body.get("site", "haworth")) if body.get("body", "moon") == "moon" else (None, (0.0, 0.0))
        s = SES.start(mission, profile=profile, dem=dem, dem_origin=origin, mission_t0_s=mission_t0_s)
    except (ValueError, RuntimeError, KeyError, FileNotFoundError) as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
    log_event(_auth, "session.start", s.session_id)         # FS-19: training-run start audit
    return {"ok": True, "session_id": s.session_id, "n_legs": len(s.record["legs"]),
            "operator_url": f"/session/{s.session_id}/operator",
            "debrief_url": f"/session/{s.session_id}/debrief"}


@router.get("/session/{sid}/operator")
def session_operator(sid: str):
    """OPEN by contract (B3): the operator-trainee sees only telemetry-delivered, truth-denylisted data."""
    s = SES.get(sid)
    if s is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": "unknown session"})
    return s.operator_view()


@router.get("/session/{sid}/scorecard")
def session_scorecard(sid: str, identity: str = Depends(require_auth)):
    """#80 / TR-01: the trainer A-board KPIs (incl. makespan-vs-optimal). Operators see the public
    board; directors also get the truth board (believed-vs-actual divergence). Requesting it
    PERSISTS the durable per-session record under data_dir/sessions/, so a finished run survives the
    live-store eviction; an already-evicted session falls back to that persisted record."""
    from stewie.server import auth as AUTH
    is_director = AUTH.role_of(identity) == "director"
    s = SES.get(sid)
    if s is not None:
        SES.persist_scorecard(s)                            # durable record (outlives M-09 eviction)
        sc = s.scorecard()
        board = dict(sc["public"])
        if is_director:
            board.update(sc["truth"])
        return {"ok": True, "scorecard": board}
    rec = SES.load_scorecard_record(sid)                    # live session gone -> the durable record
    if rec is None:
        raise HTTPException(status_code=404, detail="no such session")
    board = dict(rec["public"])
    if is_director:
        board.update(rec["truth"])
    return {"ok": True, "scorecard": board}


@router.get("/session/{sid}/debrief")
def session_debrief(sid: str, fast_forward: float = 1.0, _auth: str = Depends(require_director)):
    s = SES.get(sid)
    if s is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": "unknown session"})
    return s.debrief_view(fast_forward=fast_forward)


@router.get("/session/{sid}/divergence")
def session_divergence(sid: str, _auth: str = Depends(require_director)):
    """TR-02 (DIRECTOR truth board): the believed-vs-true POSE divergence per leg, plus the mean/max
    aggregate. Director-only -- the truth pose track is exactly the truth-denylisted signal (MO-04:
    truth is magenta, directors-only). Built from the live session record (no authored numbers)."""
    s = SES.get(sid)
    if s is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": "unknown session"})
    return {"ok": True, "session_id": sid, "divergence": s.pose_divergence()}


@router.get("/trainer/history")
def trainer_history(identity: str = Depends(require_auth)):
    """TR-03 (PROGRAM board): the cross-session history -- every persisted scorecard record (the REAL
    recorded sessions under data_dir/sessions/), newest first, for the leaderboard + makespan/
    objectives trend. Operator+; the per-session TRUTH block (pose/energy divergence) is included ONLY
    for directors (the same gating the per-session scorecard applies). Honest empty list when no
    sessions have been recorded yet -- the cockpit renders a 'no recorded sessions yet' empty state."""
    from stewie.server import auth as AUTH
    is_director = AUTH.role_of(identity) == "director"
    sessions = []
    for rec in SES.list_scorecard_records():
        row = {"session_id": rec["session_id"], "profile": rec.get("profile", "?"),
               "objective": rec.get("objective", "?"), "recorded_at": rec.get("recorded_at"),
               "public": rec.get("public", {}), "makespan": rec.get("makespan", {})}
        if is_director:
            row["truth"] = rec.get("truth", {})               # TR-02 divergence, directors only
        sessions.append(row)
    return {"ok": True, "is_director": is_director, "count": len(sessions), "sessions": sessions}


@router.get("/session/{sid}/summary")
def session_summary(sid: str, _auth: None = Depends(require_auth)):
    s = SES.get(sid)
    if s is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": "unknown session"})
    SES.persist_summary(s)
    return PlainTextResponse(SES.summary_markdown(s), media_type="text/markdown")
