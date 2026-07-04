"""[REQ:PX-02] A mission carries a SELECTABLE physics backend (validated fail-closed at the mission boundary),
and GET /physics/backends exposes the selectable engines + the EG-12 model-governance ledger (each model's
validated/frozen/deprecated status), so the cockpit can drive the physics_backend_id selector honestly."""
import pytest
from fastapi.testclient import TestClient

_BASE = {"name": "t", "body": "moon", "charger": [0, 0],
         "orders": [{"kind": "cut", "x": 1, "y": 1, "action": "d", "footprint_m2": 4, "depth_m": 0.3}]}


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("STEWIE_API_KEY", raising=False)
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")                    # dev-open -> operator-authed
    import stewie.server.server as SRV
    return TestClient(SRV.app)


def test_px02_mission_carries_a_validated_physics_backend_id():  # [REQ:PX-02]
    from lode.mission_planner import mission_from_dict
    assert mission_from_dict(_BASE).physics_backend_id == "tier2_numpy"                 # default = conserved
    assert mission_from_dict({**_BASE, "physics_backend_id": "tier2_numpy"}).physics_backend_id == "tier2_numpy"
    # fail-closed: the not-yet-conserving oracle + a bogus id are REJECTED, not silently defaulted
    with pytest.raises(ValueError):
        mission_from_dict({**_BASE, "physics_backend_id": "tier3_chrono"})
    with pytest.raises(ValueError):
        mission_from_dict({**_BASE, "physics_backend_id": "bogus"})


def test_px02_physics_backends_endpoint_lists_engines_and_model_status(monkeypatch, tmp_path):  # [REQ:PX-02]
    c = _client(monkeypatch, tmp_path)
    r = c.get("/physics/backends")
    assert r.status_code == 200, r.text
    j = r.json()
    assert "tier2_numpy" in j["selectable_backends"]              # the conserved engine is selectable
    assert j["models"] and all({"validated", "frozen", "deprecated", "backend_id", "model_id"} <= set(m)
                               for m in j["models"])
    # the oracle backend is listed for transparency but is NOT in the selectable set (validated=False)
    chrono = [m for m in j["models"] if m["backend_id"] == "tier3_chrono"]
    if chrono:
        assert chrono[0]["validated"] is False
        assert "tier3_chrono" not in j["selectable_backends"]
