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


# --- NV-08 faults + NV-09 executive over the API -------------------------------------------------
def test_nav_faults_classifies_telemetry(client):
    r = client.post("/nav/faults", json={"tip_margin_deg": -1.0, "battery_frac": 0.5})
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] and j["summary"]["safety_critical"] is True       # exhausted tip margin -> critical
    assert any(f["fault"] == "tip" and f["severity"] == "critical" for f in j["faults"])


def test_nav_executive_fail_safe_on_critical_fault(client):
    r = client.post("/nav/executive", json={"slip": 0.97})           # entrapment -> critical
    j = r.json()
    assert r.status_code == 200 and j["action"] == "fail_safe" and j["safety_critical"] is True


def test_nav_executive_routes_recovery_and_continues_when_nominal(client):
    # a stalled, blocked rover (progress far below slip prediction) -> reverse
    rev = client.post("/nav/executive", json={"progress_ratio": 0.05, "stall_duration_s": 3.0,
                                              "expected_progress_ratio": 0.9}).json()
    assert rev["action"] == "reverse"
    # nominal telemetry -> continue
    nom = client.post("/nav/executive", json={"battery_frac": 0.8}).json()
    assert nom["action"] == "continue" and nom["safety_critical"] is False


def test_nav_executive_pauses_on_unacked_command(client):
    j = client.post("/nav/executive", json={"command_acked": False}).json()
    assert j["action"] == "pause"


def test_nav_react_steers_around_an_observed_rock(client):
    # a 1 m rock dead ahead, in sensor range -> becomes a keep-out + a local detour
    r = client.post("/nav/react", json={
        "pose": [0, 0], "heading_rad": 0.0, "goal": [20, 0], "planned_path": [[0, 0], [20, 0]],
        "rocks": [[8.0, 0.0, 1.0]], "sensor_range_m": 18.0, "horizon_m": 10.0, "clearance_m": 0.5})
    assert r.status_code == 200
    j = r.json()
    assert j["replan"] is True and j["scope"] == "local" and j["n_new_hazards"] == 1
    assert j["local_arc"] and len(j["local_arc"]) > 1                 # a steering arc was returned


def test_nav_react_no_hazard_on_route_does_not_replan(client):
    j = client.post("/nav/react", json={"pose": [0, 0], "heading_rad": 0.0, "goal": [20, 0],
                                        "planned_path": [[0, 0], [20, 0]], "deviation_max_m": 2.0}).json()
    assert j["replan"] is False and j["scope"] == "none" and j["n_new_hazards"] == 0


# --- FS-05 end-to-end navigation spine over the API (POST /nav/run) ------------------------------
def test_nav_run_drives_a_real_haworth_corridor(client):  # [REQ:FS-05]
    # the end-to-end spine reachable through the product path: route the global corridor on the REAL
    # Haworth DEM, then drive it to the goal, with every on-host stage exercised in one connected call.
    r = client.post("/nav/run", json={"start": [4.0, 4.0], "goal": [44.0, 36.0], "dt": 2.0,
                                      "max_ticks": 600})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] and j["reached"] is True and j["arrived"] is True and j["reason"] == "arrived"
    assert {"global_route", "local_trajectory", "tracker", "recovery", "deviation"} <= set(j["stages"])
    assert len(j["waypoints"]) >= 2 and j["routed_m"] > 0.0
    assert len(j["trajectory"]) > 2 and j["n_ticks"] > 10
    end = j["trajectory"][-1]
    assert ((end[0] - 44.0) ** 2 + (end[1] - 36.0) ** 2) ** 0.5 <= 2.0   # finished at the requested goal
    assert "mean_m" in j["deviation"] and j["deviation"]["max_m"] < 8.0


def test_nav_run_unknown_site_returns_400(client):
    r = client.post("/nav/run", json={"start": [0.0, 0.0], "goal": [10.0, 0.0], "site": "nosuchsite_zzz"})
    assert r.status_code == 400 and r.json()["ok"] is False and "DEM" in r.json()["error"]


def test_nav_run_rejects_extra_fields(client):
    r = client.post("/nav/run", json={"start": [0.0, 0.0], "goal": [10.0, 0.0], "true_pose": [1, 1]})
    assert r.status_code == 400 and r.json()["ok"] is False
