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
