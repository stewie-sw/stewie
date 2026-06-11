"""#32: the no-terminal rule -- twin backup ops + gate validation runnable from the frontend."""
import importlib
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_API_KEY", "test-key")
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWIE_BACKUP_DIR", str(tmp_path / "replica"))
    import stewie.server.server as srv
    importlib.reload(srv)
    yield TestClient(srv.app)
    monkeypatch.undo()
    importlib.reload(srv)


H = {"X-API-Key": "test-key"}


def test_snapshot_then_retention_then_replicate(client, tmp_path):
    r = client.post("/admin/twin/snapshot", headers=H)
    assert r.status_code == 200 and r.json()["ok"]
    snap = r.json()["snapshot"]
    assert os.path.exists(snap)
    r2 = client.post("/admin/twin/retention", headers=H)
    assert r2.json()["ok"] and isinstance(r2.json()["removed"], list)
    r3 = client.post("/admin/backup/replicate", headers=H)
    assert r3.json()["ok"] and os.path.isdir(tmp_path / "replica")


def test_gate_validation_reports_byte_identity(client):
    r = client.post("/admin/gates/validate", headers=H)
    d = r.json()
    assert d["ok"] is True
    assert d["g1"].startswith("PASSED") and d["g2"].startswith("PASSED")
    assert d["byte_identical_to_frozen"] is True           # the standing invariant, now a button


def test_admin_ops_are_auth_gated(client):
    assert client.post("/admin/twin/snapshot").status_code == 401
    assert client.post("/admin/gates/validate").status_code == 401


def test_twin_cg_endpoint_reports_loaded_cg_and_margin(client):
    """#25: the live CG -- posture + drum loads -> CG offset + tip margin (physics-backed)."""
    r = client.get("/twin/cg?front_deg=80&back_deg=0&front_kg=25&back_kg=0&pitch_deg=5&roll_deg=2")
    d = r.json()
    assert d["ok"]
    assert d["cg_dz_m"] > 0.02                             # the raised loaded drum lifts the CG
    assert d["margin_deg"] > 0 and d["risk"] in ("ok", "warn", "tip")
    # the balanced symmetric load centers the CG
    r2 = client.get("/twin/cg?front_deg=80&back_deg=80&front_kg=25&back_kg=25")
    assert abs(r2.json()["cg_dx_m"]) < 0.01


def test_config_full_aggregates_safely(client):
    """#61: the Config pane's one-call state -- NO secrets (the key itself must never appear)."""
    d = client.get("/config/full").json()
    assert d["ok"]
    assert d["auth"]["api_key_set"] is True and "test-key" not in str(d)
    assert "operator_login" in d["auth"] and "trust_tailscale" in d["auth"]
    assert d["data"]["sites_imported"] >= 1 and "spice_available" in d["data"]
    assert "version" in d["server"] and "data_dir" in d["server"]
    assert "overlay" in d                                   # the N15 block, intact
