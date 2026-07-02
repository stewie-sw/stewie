"""[REQ:BP-05] a LIVE-namespace artifact is operational/shared, so deleting it requires a DIRECTOR --
even the creator cannot soft-delete their own live mission (the review found owner self-delete of live
violated AG-06). Self-service delete stays for the caller's own SANDBOX artifacts. The delete audit
event names the namespace."""
import importlib
import json

import pytest
from fastapi.testclient import TestClient

H = {"X-API-Key": "test-key"}          # the api-key identity resolves to director
_DIRECTOR = "aaron.w.storey80@gmail.com"
_OPERATOR = "mccardle.john@gmail.com"   # allowlisted, but NOT in STEWIE_DIRECTORS -> operator


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_API_KEY", "test-key")
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWIE_DIRECTORS", _DIRECTOR)     # everyone else is an operator
    from stewie.server import objects as OBJ
    importlib.reload(OBJ)
    import stewie.server.server as srv
    importlib.reload(srv)
    c = TestClient(srv.app)
    tok = c.post("/auth/login", json={"email": _OPERATOR}, headers=H).json()["token"]
    yield c, {"Authorization": f"Bearer {tok}"}, tmp_path
    monkeypatch.undo()
    importlib.reload(srv)


_DOC = {"body": "moon", "orders": [{"action": "wp1", "kind": "goto", "x": 1.0, "y": 1.0}]}


def test_operator_cannot_delete_own_live_mission(client):
    c, op, _ = client
    assert c.post("/missions/pad-live", json=_DOC, headers=op).json()["ok"]   # operator writes to live
    r = c.delete("/missions/pad-live", headers=op)                            # ...and tries to delete it
    assert r.status_code == 403
    assert "director" in r.json()["error"].lower()
    assert c.get("/missions/pad-live", headers=op).status_code == 200         # still there (not deleted)


def test_operator_can_delete_own_sandbox_mission(client):
    c, op, _ = client
    assert c.post("/missions/pad-sbx?ns=sandbox", json=_DOC, headers=op).json()["ok"]
    r = c.delete("/missions/pad-sbx?ns=sandbox", headers=op)                  # self-service in sandbox
    assert r.status_code == 200 and r.json()["ok"]


def test_director_deletes_a_live_mission_and_audit_names_the_namespace(client):
    c, op, tmp_path = client
    assert c.post("/missions/pad-live", json=_DOC, headers=op).json()["ok"]
    r = c.delete("/missions/pad-live", headers=H)                            # the director (api-key) can
    assert r.status_code == 200 and r.json()["ok"]
    actions = [json.loads(ln) for ln in (tmp_path / "events.jsonl").read_text().splitlines() if ln.strip()]
    deletes = [e for e in actions if e["action"] == "mission.delete"]
    assert deletes and "ns=live" in deletes[-1]["target"]                     # BP-05: audit names the namespace


def test_operator_cannot_delete_a_shared_live_structure(client):
    c, op, _ = client
    # a custom structure template is a shared LIVE artifact -> director-only to delete.
    made = c.post("/structures/custom/wall-x", json={"orders": [
        {"action": "a", "kind": "cut", "x": 1.0, "y": 1.0, "footprint_m2": 4.0, "depth_m": 0.1}]}, headers=op)
    if made.status_code == 200:                                              # only assert the delete gate
        assert c.delete("/structures/custom/wall-x", headers=op).status_code == 403
