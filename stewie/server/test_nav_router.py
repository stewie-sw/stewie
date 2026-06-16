"""NV-03/04 over the API: POST /nav/local_plan returns a feasible arc + bounded drive command, steers
around a keep-out, and reports feasible=false (for the global router) when the goal is walled off. Driven
through the real ASGI app via TestClient; auth via the loopback dev-open path."""
import pytest
from fastapi.testclient import TestClient

from stewie.server import server as SRV


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.delenv("STEWIE_API_KEY", raising=False)
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")            # loopback/in-process -> require_auth = dev-open
    return TestClient(SRV.app)


def test_local_plan_returns_arc_and_bounded_command(client):
    r = client.post("/nav/local_plan", json={"pose": [0, 0], "heading_rad": 0.0, "goal": [20, 0]})
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] and j["feasible"] is True
    assert abs(j["curvature"]) < 1e-9                     # straight toward a clear dead-ahead goal
    assert j["progress_m"] > 0 and len(j["arc"]) > 1
    cmd = j["command"]
    assert cmd["v_cmd"] > 0 and cmd["expected_speed_ms"] > 0 and cmd["duration_s"] > 0
    assert cmd["arc_length_m"] > 0


def test_local_plan_steers_around_a_keepout(client):
    r = client.post("/nav/local_plan", json={
        "pose": [0, 0], "heading_rad": 0.0, "goal": [20, 0],
        "keepouts": [[8.0, 0.0, 2.0]], "horizon_m": 10.0, "clearance_m": 0.5})
    assert r.status_code == 200
    j = r.json()
    assert j["feasible"] is True and abs(j["curvature"]) > 0.0    # had to curve off the blocked straight line
    for x, y, _th in j["arc"]:                                    # the returned arc clears the keep-out
        assert ((x - 8.0) ** 2 + (y - 0.0) ** 2) ** 0.5 > 2.0 + 0.5 - 1e-6


def test_local_plan_reports_infeasible_when_walled_off(client):
    # ring the start tightly with keep-outs so no arc in the fan escapes -> feasible=false (global re-route)
    walls = [[2.0 * __import__("math").cos(t), 2.0 * __import__("math").sin(t), 1.5]
             for t in [i * 0.4 for i in range(16)]]
    r = client.post("/nav/local_plan", json={
        "pose": [0, 0], "heading_rad": 0.0, "goal": [20, 0], "keepouts": walls,
        "horizon_m": 8.0, "clearance_m": 1.0})
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] and j["feasible"] is False and "blocked" in j["reason"] and "command" not in j


def test_local_plan_rejects_extra_fields(client):
    r = client.post("/nav/local_plan", json={"pose": [0, 0], "heading_rad": 0.0, "goal": [20, 0],
                                             "true_slip": 0.9})   # extra key (extra='forbid')
    # the app maps Pydantic validation failures to 400 + {ok:false,error} (not FastAPI's 422 default)
    assert r.status_code == 400 and r.json()["ok"] is False
