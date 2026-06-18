"""DT-02: /twin/version is least-privilege. Before this it leaked the full observed-twin event
history with no auth. Now: any authenticated client gets the minimal version TOKEN (version +
chain_valid, NO history); the full audit history requires director (/twin/history)."""
import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_API_KEY", "test-key")
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    import stewie.server.server as srv
    importlib.reload(srv)
    yield TestClient(srv.app)
    monkeypatch.undo()
    importlib.reload(srv)


H = {"X-API-Key": "test-key"}                                    # director-level (API key)


def test_twin_version_requires_auth_and_hides_history(client):
    anon = client.get("/twin/version")
    assert anon.status_code in (401, 403)                        # no anonymous version read
    ok = client.get("/twin/version", headers=H)
    assert ok.status_code == 200
    d = ok.json()
    assert "twin_version" in d and "chain_valid" in d
    assert "events" not in d                                     # the minimal token never carries the audit log


def test_twin_history_is_director_only(client):
    assert client.get("/twin/history").status_code in (401, 403)  # anonymous denied
    ok = client.get("/twin/history", headers=H)
    assert ok.status_code == 200
    assert "events" in ok.json()                                 # director sees the full audit history
