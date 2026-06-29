"""#241 TDD: per-owner SOIL OVERLAY. An operator can save a measured soil profile to their own overlay on
top of the static bodies.py baseline (which is never mutated). NO-FABRICATION invariant: a soil missing
provenance/confidence is rejected -- mirrors the bodies.py MEASURED/ESTIMATED/UNKNOWN discipline. Per-owner
isolated + sandbox-only. Real store under a tmp data_dir."""
import pytest
from fastapi.testclient import TestClient

_GOOD = {"bekker": [1400, 820000, 1.0], "cohesion_pa": 170, "friction_deg": 35,
         "bulk_density": 1500, "confidence": "MEASURED", "provenance": "NASA LTV bevameter (sample doc)"}


def test_save_load_soil_roundtrip_isolation_sandbox(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    from stewie.server import objects as OBJ
    OBJ.save_soil("grc3", _GOOD, owner="alice@x.com")
    got = OBJ.load_soil("grc3", owner="alice@x.com")
    assert got and got["provenance"] == _GOOD["provenance"] and got["bekker"] == [1400, 820000, 1.0]
    assert OBJ.load_soil("grc3", owner="bob@x.com") is None          # per-owner isolation
    assert not (tmp_path / "soil" / "grc3.json").exists()            # NOT the live tier
    assert (tmp_path / "soil" / "sandbox").exists()                  # per-owner sandbox


def test_soil_requires_provenance_and_confidence(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    from stewie.server import objects as OBJ
    no_prov = {**_GOOD}; no_prov["provenance"] = ""
    with pytest.raises(ValueError):
        OBJ.save_soil("x", no_prov, owner="a@x.com")                 # no source -> rejected (no fabrication)
    no_conf = {k: v for k, v in _GOOD.items() if k != "confidence"}
    with pytest.raises(ValueError):
        OBJ.save_soil("x", no_conf, owner="a@x.com")


def test_soil_rejects_unknown_fields(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    from stewie.server import objects as OBJ
    with pytest.raises(ValueError):
        OBJ.save_soil("x", {**_GOOD, "gravity": 1.62}, owner="a@x.com")   # gravity is the body's, not the soil's


def test_soil_routes(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("STEWIE_API_KEY", raising=False)
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")
    import stewie.server.server as SRV
    c = TestClient(SRV.app)
    assert c.post("/soil/grc3", json=_GOOD).status_code == 200
    names = [s["name"] for s in c.get("/soils").json()["soils"]]
    assert "grc3" in names
    bad = {**_GOOD}; bad["provenance"] = ""
    assert c.post("/soil/nope", json=bad).status_code == 400         # no-fabrication gate at the route


def test_soil_routes_require_auth(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("STEWIE_API_KEY", raising=False)
    monkeypatch.delenv("STEWIE_DEV_OPEN", raising=False)
    import stewie.server.server as SRV
    c = TestClient(SRV.app)
    assert c.get("/soils").status_code == 503
    assert c.post("/soil/x", json=_GOOD).status_code == 503
