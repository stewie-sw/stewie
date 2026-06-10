"""#39: the event history -- who did what when, append-only, actor from the auth identity."""
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


def test_mutations_are_logged_with_the_operator_identity(client):
    # sign in as Aaron -> the mission save must log HIS identity, not "api-key"
    tok = client.post("/auth/login", json={"email": "aaron.w.storey80@gmail.com"},
                      headers={"X-API-Key": "test-key"}).json()["token"]
    client.post("/missions/audit-me", headers={"Authorization": f"Bearer {tok}"},
                json={"body": "moon", "orders": []})
    client.delete("/missions/audit-me", headers={"X-API-Key": "test-key"})
    ev = client.get("/events").json()["events"]
    assert ev[0]["action"] == "mission.delete" and ev[0]["actor"] == "api-key"
    assert ev[1]["action"] == "mission.save" and ev[1]["actor"] == "aaron.w.storey80@gmail.com"
    assert ev[1]["target"] == "audit-me" and ev[1]["ts"] > 0


def test_events_endpoint_caps_and_orders(client):
    for i in range(7):
        client.post(f"/missions/m{i}", headers={"X-API-Key": "test-key"},
                    json={"body": "moon", "orders": []})
    ev = client.get("/events?n=3").json()["events"]
    assert len(ev) == 3 and ev[0]["target"] == "m6"          # newest first
