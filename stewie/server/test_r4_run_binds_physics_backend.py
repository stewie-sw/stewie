"""[dispatch-audit R4] /executive/run attributes the REVIEWED physics backend -- the executed mission's
declared physics_backend_id (PX-02) -- not a hardcoded literal.

The audit (finding 3, "physics and terrain inputs diverge") wants the run to execute + attribute against the
reviewed physics snapshot. The run hardcoded get_backend("tier2_numpy") / physics_attribution("tier2_numpy")
in three places, so if a second backend ever became selectable the run would silently ignore the mission's
declared choice. R4 binds those to mission.physics_backend_id (the PX-02-validated backend carried on the
signed plan). Today only tier2_numpy is selectable, so this is behaviour-preserving; the test PROVES the
sourcing by injecting a distinguishable declared backend and asserting the run attributes THAT, not the literal.
"""
from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_API_KEY", "test-key")
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    from stewie.server import operators as OPS
    importlib.reload(OPS)
    import stewie.server.server as srv
    importlib.reload(srv)
    yield TestClient(srv.app), "test-key"
    monkeypatch.undo()
    importlib.reload(srv)


def _release(c, key) -> str:
    r = c.post("/executive/release-plan", headers={"X-API-Key": key}, json={
        "body": "moon", "mission_id": "M-r4", "orders": [
            {"action": "Pad cut", "kind": "cut", "x": 10.0, "y": 5.0, "footprint_m2": 9.0, "depth_m": 0.2}]})
    assert r.status_code == 200, r.text
    return r.json()["signed_revision"]["content_hash"]


def test_run_attributes_the_missions_physics_backend_not_a_literal(client, monkeypatch):  # [dispatch-audit R4]
    c, key = client
    ch = _release(c, key)

    # register a 2nd SELECTABLE backend that aliases the real conserved TIER2 authority, so a non-default id
    # both resolves (get_backend) and conserves mass -- the run's physics preconditions still hold.
    from stewie.physics import backend as BK
    monkeypatch.setitem(BK._BACKENDS, "tier2_test", BK._BACKENDS["tier2_numpy"])

    # make the EXECUTED mission DECLARE that backend. A hardcoded 'tier2_numpy' literal would then diverge from
    # the mission's declared backend; sourcing from mission.physics_backend_id echoes 'tier2_test'.
    from lode import mission_intent_compiler as MIC
    _real = MIC.compile_intent

    def _swap(intent):
        req = _real(intent)
        req.mission.physics_backend_id = "tier2_test"      # Mission is a mutable dataclass
        return req

    monkeypatch.setattr(MIC, "compile_intent", _swap)

    r = c.post("/executive/run", headers={"X-API-Key": key},
               json={"revision_hash": ch, "site": "haworth"})
    assert r.status_code == 200, r.text
    # the run attributes the physics backend the reviewed mission DECLARED, not the old hardcoded literal.
    assert r.json()["physics_attribution"]["backend"] == "tier2_test"


def test_default_run_attributes_tier2_numpy(client):  # [dispatch-audit R4]
    """The default (no injection): a released plan carries the default PX-02 backend, so the run attributes
    tier2_numpy -- unchanged behaviour."""
    c, key = client
    ch = _release(c, key)
    r = c.post("/executive/run", headers={"X-API-Key": key},
               json={"revision_hash": ch, "site": "haworth"})
    assert r.status_code == 200, r.text
    pa = r.json()["physics_attribution"]
    assert pa["backend"] == "tier2_numpy" and pa["conserves_mass"] is True
