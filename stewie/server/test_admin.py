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
