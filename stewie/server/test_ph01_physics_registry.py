"""[REQ:PH-01] the physics backend authority registry (/physics/authority): the 5 PRD2 backends + each one's
authority scope, mass-conservation, per-lifecycle validity, and refusal reason. Load-bearing invariants:
tier2_numpy is the conserved, release-eligible terrain authority; gazebo is robot/sensor sim NOT the terrain-
mutation authority (not release-eligible); chrono is not release-eligible until conservation+calibration gates
pass; godot is rendering only, never physics or command authority. Real endpoint + config registry."""
from fastapi.testclient import TestClient

from stewie.server.server import app


def test_ph01_physics_authority_registry(monkeypatch):  # [REQ:PH-01]
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")
    c = TestClient(app, base_url="http://127.0.0.1")
    j = c.get("/physics/authority").json()
    by = {b["id"]: b for b in j["backends"]}
    assert set(by) == {"tier2_numpy", "gazebo", "chrono", "hardware", "godot"}

    # tier2_numpy is the conserved terrain authority, release + execute eligible
    t2 = by["tier2_numpy"]
    assert t2["conserves_mass"] is True and "terrain" in t2["authority_scope"]
    assert t2["valid_for_release"] is True and t2["valid_for_execute"] is True

    # gazebo is robot/sensor sim, NOT the terrain-mutation authority, NOT release-eligible
    gz = by["gazebo"]
    assert "terrain" not in gz["authority_scope"] and "robot" in gz["authority_scope"]
    assert gz["valid_for_release"] is False and gz["refusal_reason"]

    # chrono is not release-eligible until conservation + calibration gates pass
    assert by["chrono"]["valid_for_release"] is False and "calibration" in by["chrono"]["refusal_reason"]

    # godot renders and NEVER owns physics or command authority
    gd = by["godot"]
    assert gd["authority_scope"] == ["rendering"]
    assert not any(gd[k] for k in ("valid_for_planning", "valid_for_release", "valid_for_execute"))
