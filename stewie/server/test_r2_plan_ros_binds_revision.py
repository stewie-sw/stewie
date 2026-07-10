"""[dispatch-audit R2 / F3] /rc/plan_ros can BIND an immutable released revision and lower the FROZEN
signed plan to ROS -- reporting the SAME content_hash release + run report, so release/run/ROS-lowering
all agree on one immutable identity.

The audit (F3) found /rc/plan_ros lowered a MUTABLE saved mission (``OBJ.load_mission(name, 'live')`` ->
``mission_from_dict``) to ROS: the lowered plan was not bound to the immutable released revision, so an
edited saved mission could lower different commands than what was signed. F3 adds an additive ``revision_hash``
path: the route fetches the frozen R1 revision (db.read_release_revision), lowers
``compile_intent(frozen_intent).mission``'s plan_ir, and reports the bound ``content_hash``. A director-signed
revision is authority-equivalent to AG-08's published-live gate. The legacy mission-name path is unchanged
(``content_hash`` null) for backward compatibility. Real store + the SF-01 RC router via a TestClient.
"""
from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_API_KEY", "test-key")
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    from stewie.server import objects as OBJ
    importlib.reload(OBJ)
    from stewie.server import operators as OPS
    importlib.reload(OPS)
    import stewie.server.server as srv
    importlib.reload(srv)
    OBJ.save_mission("Live Pad", {"body": "moon",
                                  "orders": [{"action": "borrow", "kind": "cut", "x": 20.0, "y": 0.0,
                                              "footprint_m2": 16.0, "depth_m": 0.3}]},
                     owner="op@x.com", namespace="live")
    yield TestClient(srv.app), "test-key"
    monkeypatch.undo()
    importlib.reload(srv)


def _release(c, key) -> str:
    """Release a real build plan and return its immutable content_hash (the R1 signed revision)."""
    payload = {"body": "moon", "mission_id": "M-f3", "orders": [
        {"action": "Pad cut", "kind": "cut", "x": 10.0, "y": 5.0, "footprint_m2": 9.0, "depth_m": 0.2},
        {"action": "Berm fill", "kind": "fill", "x": 4.0, "y": 5.0, "footprint_m2": 4.0, "depth_m": 0.1},
    ]}
    r = c.post("/executive/release-plan", headers={"X-API-Key": key}, json=payload)
    assert r.status_code == 200, r.text
    return r.json()["signed_revision"]["content_hash"]


def test_plan_ros_binds_a_released_revision_and_reports_the_same_hash(client):  # [dispatch-audit R2]
    c, key = client
    ch = _release(c, key)
    r = c.post("/rc/plan_ros", headers={"X-API-Key": key}, json={"revision_hash": ch})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] is True
    assert d["content_hash"] == ch                         # ROS-lowering reports the SAME immutable hash
    assert d["plan_id"] and d["ir_version"]                # correlatable to the source plan
    assert d["counts"]["paths"] >= 1 and d["counts"]["work_goals"] >= 1   # the frozen plan lowered non-vacuously
    assert d["frames"] and d["stream"]["seq"] == len(d["frames"])


def test_plan_ros_rejects_an_unknown_revision_hash(client):  # [dispatch-audit R2]
    c, key = client
    r = c.post("/rc/plan_ros", headers={"X-API-Key": key}, json={"revision_hash": "0" * 64})
    assert r.status_code == 400, r.text


def test_plan_ros_legacy_mission_path_is_unbound(client):  # [dispatch-audit R2]
    """Backward compatibility: the mission-name path still lowers a live mission, reporting content_hash
    null so a consumer sees it was NOT bound to a released revision."""
    c, key = client
    r = c.post("/rc/plan_ros", headers={"X-API-Key": key}, json={"mission": "Live Pad"})
    assert r.status_code == 200, r.text
    assert r.json()["content_hash"] is None
    assert r.json()["counts"]["paths"] >= 1
