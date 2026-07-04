"""[REQ:BP-06][REQ:SE-02] The training operator view has an explicit AUTHENTICATED access model: a leaked
session id is no longer a bearer token for the truth-denylisted training telemetry. /session/{sid}/operator
requires a valid identity (require_auth); truth-denial (operator_view shaping) is defense-in-depth, not the
access decision."""
import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_API_KEY", "director-key")
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    import stewie.server.server as srv
    importlib.reload(srv)
    yield TestClient(srv.app)
    monkeypatch.undo()
    importlib.reload(srv)


def _mission():
    return {"name": "b3 session", "body": "moon", "charger": [0, 0],
            "orders": [{"action": "cut", "kind": "cut", "x": 8, "y": 6, "footprint_m2": 16,
                        "depth_m": 0.05, "label": "pad"}],
            "profile": "mission_default"}


def test_bp06_operator_view_requires_auth(client):  # [REQ:BP-06] [REQ:SE-02]
    r = client.post("/session/start", json=_mission(), headers={"X-API-Key": "director-key"})
    assert r.status_code == 200, r.text
    sid = r.json()["session_id"]
    # the operator view is NO LONGER open-by-contract: an unauthenticated request is DENIED (was 200).
    assert client.get(f"/session/{sid}/operator").status_code in (401, 403, 503)
    # an authenticated request gets the shaped operator view.
    ok = client.get(f"/session/{sid}/operator", headers={"X-API-Key": "director-key"})
    assert ok.status_code == 200, ok.text
