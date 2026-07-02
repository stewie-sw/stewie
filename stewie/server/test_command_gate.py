"""AG-08 [REQ:AG-08] (PRD §7.12, END GOAL): real rover instructions are emitted only for a LIVE-namespace mission,
by an operator+, under the SF-01 watchdog. A command that CITES a mission is rejected unless that
mission is published (live); a sandbox draft can be simulated but is structurally barred from the real
rover-command path. Low-level teleop (no mission ref) is unaffected. Real store + the SF-01 RC backend
via a TestClient (api-key identity == director == operator+; require_role("operator") already passes).

Run: <venv>/bin/python -m pytest stewie/server/test_command_gate.py -q
"""
import importlib
import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_API_KEY", "test-key")
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    # SF-02: this file exercises the AG-08 / SF-01 / AS-12 gates for a MISSION-LESS GoTo (watchdog,
    # malformed, stale-link). Those downstream gates only run once the new SF-02 teleop-authority gate
    # admits a mission-less command, so pin an explicit dev/bench teleop posture here; the SF-02 decision
    # itself is covered in test_rc_command_authority.py. Mission-BOUND cases are unaffected by these flags.
    monkeypatch.setenv("STEWIE_RUNNABLE_PROFILE", "bench")
    monkeypatch.setenv("STEWIE_ALLOW_TELEOP", "1")
    from stewie.server import operators as OPS
    importlib.reload(OPS)
    from stewie.server import objects as OBJ
    importlib.reload(OBJ)
    import stewie.server.server as srv
    importlib.reload(srv)
    OBJ.save_mission("Live Pad", {"body": "moon", "orders": []}, owner="op@x.com", namespace="live")
    OBJ.save_mission("Draft", {"body": "moon", "orders": []}, owner="alice@x.com", namespace="sandbox")
    yield TestClient(srv.app), "test-key"
    monkeypatch.undo()
    importlib.reload(srv)


def _cmd(mission=None):
    b = {"kind": "safe"}                      # Safe needs no extra args and still goes through the watchdog
    if mission is not None:
        b["mission"] = mission
    return b


def test_command_for_a_live_mission_is_accepted(client):
    c, key = client
    r = c.post("/rc/command", headers={"X-API-Key": key}, json=_cmd("Live Pad"))
    assert r.status_code == 200, r.text
    assert r.json()["accepted"] == "safe"


def test_command_for_a_sandbox_draft_is_rejected(client):
    c, key = client
    r = c.post("/rc/command", headers={"X-API-Key": key}, json=_cmd("Draft"))
    assert r.status_code == 403, r.text
    assert "live" in r.text.lower()                  # message shape is handler-dependent; check the text


def test_command_for_a_missing_mission_is_rejected(client):
    c, key = client
    r = c.post("/rc/command", headers={"X-API-Key": key}, json=_cmd("ghost"))
    assert r.status_code == 403, r.text


def test_low_level_teleop_without_a_mission_is_unaffected(client):
    c, key = client
    r = c.post("/rc/command", headers={"X-API-Key": key}, json=_cmd())   # no mission ref
    assert r.status_code == 200, r.text
    assert r.json()["accepted"] == "safe"


def test_malformed_goto_is_400_not_500(client):
    """#275: a GoTo with missing/garbled numeric fields is a client error (400), not an uncaught 500
    (raw body['goal_row']/['goal_col'] subscripts inside float() previously had no try/except)."""
    c, key = client
    H = {"X-API-Key": key}
    assert c.post("/rc/command", headers=H, json={"kind": "goto", "leg_id": 0}).status_code == 400  # missing goals
    assert c.post("/rc/command", headers=H,
                  json={"kind": "goto", "goal_row": "north", "goal_col": 1}).status_code == 400      # non-numeric
    ok = c.post("/rc/command", headers=H, json={"kind": "goto", "goal_row": 5, "goal_col": 6})        # well-formed
    assert ok.status_code == 200 and ok.json()["accepted"] == "goto", ok.text


def test_telemetry_stream_pushes_sse_frames(client):  # #230 live-ops: the SSE telemetry stream
    c, key = client
    r = c.get("/rc/telemetry/stream", params={"max_frames": 2, "interval_s": 0.05},
              headers={"X-API-Key": key})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")
    frames = [ln[len("data: "):] for ln in r.text.splitlines() if ln.startswith("data: ")]
    assert len(frames) == 2                                  # max_frames bounded the stream (no hang)
    for f in frames:
        payload = json.loads(f)
        assert payload["ok"] is True
        assert "telemetry" in payload and "deadline_s" in payload["watchdog"]


def test_telemetry_stream_requires_auth(client):  # #230: the stream is auth-gated like the snapshot
    c, _key = client
    r = c.get("/rc/telemetry/stream", params={"max_frames": 1})
    assert r.status_code in (401, 403), r.text


def test_ros_odom_ingest_round_trips(client):  # #144: the live ROS2 node POSTs /odom -> cockpit live view
    c, key = client
    r = c.post("/rc/ros_odom", headers={"X-API-Key": key},
               json={"x_m": 12.5, "y_m": -4.0, "yaw_rad": 0.3, "slip": 0.1, "soc": 0.8, "mode": "cmd_vel"})
    assert r.status_code == 200, r.text
    # the ingested live-ROS pose surfaces on the telemetry payload (the cockpit stream renders it)
    tel = c.get("/rc/telemetry", headers={"X-API-Key": key}).json()
    ro = tel["ros_odom"]
    assert ro is not None
    assert ro["x_m"] == 12.5 and ro["y_m"] == -4.0
    assert ro["mode"] == "cmd_vel"                                      # tier-2: the rover's control mode
    assert isinstance(ro["age_s"], (int, float)) and ro["age_s"] >= 0   # staleness is reported


def test_ros_odom_ingest_requires_operator(client):  # a write to the live-ops surface is auth-gated
    c, _key = client
    r = c.post("/rc/ros_odom", json={"x_m": 0.0, "y_m": 0.0})
    assert r.status_code in (401, 403), r.text


def test_ros_odom_ingest_rejects_nonfinite(client):  # bounded input -> no NaN/Inf poisons the live view
    c, key = client
    # raw JSON: 1e400 parses to +inf server-side (the client json encoder would refuse float('inf'))
    r = c.post("/rc/ros_odom", headers={"X-API-Key": key, "Content-Type": "application/json"},
               content=b'{"x_m": 1e400, "y_m": 0.0}')
    assert r.status_code == 400, r.text          # rejected (this app maps validation errors to 400), not stored
    # and a finite OUT-OF-RANGE value is rejected by the same bound (not silently clamped/stored)
    r2 = c.post("/rc/ros_odom", headers={"X-API-Key": key}, json={"x_m": 1e9, "y_m": 0.0})
    assert r2.status_code == 400 and "less than or equal" in r2.text, r2.text


def test_telemetry_payload_carries_cell_m(client):  # #230 step 3: the live drive map needs the grid scale
    # The Pose is in grid (row, col) cells; the cockpit live map converts to REP-103 meters
    # (x=col*cell_m, y=-row*cell_m, frames.py). So the telemetry MUST expose the backend cell_m, else the
    # map can only plot dimensionless cells. Assert it on both the one-shot snapshot and a streamed frame.
    c, key = client
    snap = c.get("/rc/telemetry", headers={"X-API-Key": key})
    assert snap.status_code == 200, snap.text
    assert isinstance(snap.json()["cell_m"], (int, float)) and snap.json()["cell_m"] > 0
    st = c.get("/rc/telemetry/stream", params={"max_frames": 1, "interval_s": 0.05},
               headers={"X-API-Key": key})
    frame = json.loads([ln[len("data: "):] for ln in st.text.splitlines() if ln.startswith("data: ")][0])
    assert isinstance(frame["cell_m"], (int, float)) and frame["cell_m"] > 0


def test_goto_is_refused_409_while_watchdog_tripped_until_rearm(client):
    """#286 [REQ:SF-01]: once the SF-01 watchdog has tripped (comms-dropout safe-stop), POST /rc/command
    GoTo must be REFUSED (409, no silent resume) until an explicit operator re-arm. A 'rearm' command
    clears the latch; only then does a GoTo drive again. (Force the latch directly -- the route's watchdog
    uses a real monotonic clock, so we set its tripped state rather than sleep past the live deadline.)"""
    c, key = client
    H = {"X-API-Key": key}
    from stewie.server.routers import rc as RCR
    saved = RCR._RC_WATCHDOG
    try:
        from stewie.bridge import rc_contract as C
        RCR._RC_WATCHDOG = C.SafingWatchdog(RCR._RC_BACKEND, deadline_s=5.0)
        RCR._RC_WATCHDOG.submit(C.GoTo(leg_id=0, goal_row=0, goal_col=1, v_max_mps=0.3, goal_radius_cells=1),
                                now=0.0)
        RCR._RC_WATCHDOG.tick(now=100.0)                 # past the deadline -> latched SAFE
        assert RCR._RC_WATCHDOG.tripped
        # a GoTo while tripped is refused (409), not silently resumed
        r = c.post("/rc/command", headers=H, json={"kind": "goto", "goal_row": 5, "goal_col": 6})
        assert r.status_code == 409, r.text
        assert "re-arm" in r.text.lower() or "tripped" in r.text.lower()
        # the deliberate re-arm clears the latch
        ra = c.post("/rc/command", headers=H, json={"kind": "rearm"})
        assert ra.status_code == 200 and ra.json()["accepted"] == "rearm", ra.text
        assert ra.json()["watchdog_tripped"] is False
        # now a GoTo drives again
        ok = c.post("/rc/command", headers=H, json={"kind": "goto", "goal_row": 5, "goal_col": 6})
        assert ok.status_code == 200 and ok.json()["accepted"] == "goto", ok.text
    finally:
        RCR._RC_WATCHDOG = saved


def test_goto_refused_409_when_link_is_stale_even_if_not_safed(client):  # #290 [REQ:AS-12]
    """The unified command-eligibility interlock must actually RUN on the live command path -- it had
    zero production callers, so the NV-12 stale-link gate never fired live. A GoTo on a link that has gone
    quiet past the ack deadline (but has NOT yet been ticked into a SAFE trip) must be refused with a
    'stale_link' reason; a fresh command is eligible again. (safed is exercised by the #286 test.)"""
    import time

    from stewie.bridge import rc_contract as C
    from stewie.server.routers import rc as RCR
    c, key = client
    H = {"X-API-Key": key}
    saved = RCR._RC_WATCHDOG
    try:
        wd = C.SafingWatchdog(RCR._RC_BACKEND, deadline_s=5.0)
        wd.feed(now=time.monotonic() - 100.0)            # last command 100 s ago -> link stale, NOT tripped
        assert not wd.tripped
        RCR._RC_WATCHDOG = wd
        r = c.post("/rc/command", headers=H, json={"kind": "goto", "goal_row": 5, "goal_col": 6})
        assert r.status_code == 409, r.text
        assert "stale_link" in r.text, r.text               # NV-12 freshness gate ran live (#290)
        wd.feed(now=time.monotonic())                        # a recent command -> link fresh again
        ok = c.post("/rc/command", headers=H, json={"kind": "goto", "goal_row": 5, "goal_col": 6})
        assert ok.status_code == 200 and ok.json()["accepted"] == "goto", ok.text
    finally:
        RCR._RC_WATCHDOG = saved


def test_sim_telemetry_does_not_fabricate_soc():
    """No-synthetic (Council Operator P2): the in-process kinematic SimBackend has NO energy model, so the
    telemetry payload must NOT report a fabricated soc (the Pose default 1.0). The cockpit then shows no
    SoC rather than a permanent "100%" live reading. A battery-modelling backend reports a real soc."""
    from stewie.server.routers import rc as RCR
    from stewie.bridge import rc_contract as C
    saved = RCR._RC_BACKEND
    try:
        RCR._RC_BACKEND = C.SimBackend(start_rc=(0.0, 0.0))
        RCR._RC_BACKEND.submit(C.GoTo(leg_id=1, goal_row=2.0, goal_col=0.0))
        payload = RCR._telemetry_payload()
        poses = [t for t in payload["telemetry"] if t.get("kind") == "pose"]
        assert poses, "the SimBackend emitted no pose to check"
        assert all(t["soc"] is None for t in poses)        # no fabricated 100% on the sim telemetry path
    finally:
        RCR._RC_BACKEND = saved
