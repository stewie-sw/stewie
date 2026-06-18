"""NV-11 + NV-12 (X-closing): the /rc/plan_ros route lowers a LIVE mission's plan to ROS2-shaped command
messages (NV-11 lower_plan_ir) framed on a versioned StreamSession (NV-12), under the AG-08 interlock --
operator+ and a published (live) mission only; a sandbox draft is structurally refused. Real store + the
SF-01 RC router via a TestClient (api-key identity == director == operator+)."""
import importlib

import pytest
from fastapi.testclient import TestClient

_ORDERS = [{"action": "borrow", "kind": "cut", "x": 20.0, "y": 0.0, "footprint_m2": 16.0, "depth_m": 0.3},
           {"action": "pad", "kind": "fill", "x": 40.0, "y": 0.0, "footprint_m2": 16.0, "depth_m": 0.3}]


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
    OBJ.save_mission("Live Pad", {"body": "moon", "orders": _ORDERS}, owner="op@x.com", namespace="live")
    OBJ.save_mission("Draft", {"body": "moon", "orders": _ORDERS}, owner="op@x.com", namespace="sandbox")
    yield TestClient(srv.app), "test-key"
    monkeypatch.undo()
    importlib.reload(srv)


def test_live_mission_lowers_to_sequenced_ros_frames(client):  # [REQ:NV-11] [REQ:NV-12]
    c, key = client
    r = c.post("/rc/plan_ros", headers={"X-API-Key": key}, json={"mission": "Live Pad"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] and d["plan_id"] and d["ir_version"]
    assert d["counts"]["paths"] >= 1 and d["counts"]["work_goals"] >= 1     # NV-11 lowered the plan
    # NV-12: each frame is a versioned, monotonically sequenced StreamSession frame
    assert d["frames"] and d["frames"][0]["v"] == "1.0" and d["frames"][0]["seq"] == 0
    assert [f["seq"] for f in d["frames"]] == list(range(len(d["frames"])))
    assert d["stream"]["version"] == "1.0" and d["stream"]["seq"] == len(d["frames"])


def test_sandbox_draft_is_refused(client):
    c, key = client
    r = c.post("/rc/plan_ros", headers={"X-API-Key": key}, json={"mission": "Draft"})
    assert r.status_code == 403 and "live" in r.text.lower()                # AG-08: sandbox barred


def test_missing_mission_is_refused(client):
    c, key = client
    r = c.post("/rc/plan_ros", headers={"X-API-Key": key}, json={"mission": "ghost"})
    assert r.status_code == 403


def test_no_mission_ref_is_400(client):
    c, key = client
    r = c.post("/rc/plan_ros", headers={"X-API-Key": key}, json={})
    assert r.status_code == 400
