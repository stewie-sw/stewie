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


def test_large_plan_lowers_every_goal_without_silent_backpressure_drop(client):  # #287 [REQ:NV-12]
    """A plan whose lowered messages exceed the StreamSession default 64-frame un-acked window must
    still lower EVERY goal. This route is a one-shot batch lowering (no live consumer acks within the
    request), so the backpressure window previously REFUSED every frame past the 64th as a null frame
    while HTTP stayed 200 -- a silent goal drop. Now the session is sized to the batch: no nulls, no
    refusals, contiguous seqs, and len(frames) == sum(counts)."""
    c, key = client
    from stewie.server import objects as OBJ
    # ~60 orders -> well over 64 lowered frames across the 5 groups (paths/motion/work/observation/replan)
    big = [{"action": f"o{i}", "kind": ("cut" if i % 2 else "fill"),
            "x": 20.0 + 5.0 * (i % 12), "y": 5.0 * (i // 12),
            "footprint_m2": 16.0, "depth_m": 0.3} for i in range(60)]
    OBJ.save_mission("Big Pad", {"body": "moon", "orders": big}, owner="op@x.com", namespace="live")
    r = c.post("/rc/plan_ros", headers={"X-API-Key": key}, json={"mission": "Big Pad"})
    assert r.status_code == 200, r.text
    d = r.json()
    total = sum(d["counts"].values())
    assert total > 64, f"test needs a >64-frame plan to exercise the window (got {total})"
    assert all(f is not None for f in d["frames"]), "a goal was silently refused as a null frame (#287)"
    assert len(d["frames"]) == total, "lowered-message count != framed count -> goals were dropped"
    assert [f["seq"] for f in d["frames"]] == list(range(total))      # contiguous, nothing missing
    assert d["stream"]["refused"] == 0, "backpressure refused frames in a one-shot batch lowering (#287)"


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
