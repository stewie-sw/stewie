"""AG-07 routes (PRD §7.12): namespace-aware mission routes. deps.namespace_for confines
trainees/guests to their own sandbox and defaults operator+ to live; the publish route promotes a
sandbox draft into live. Pure routing logic (unit) + a real-socket sandbox->publish->live round-trip
(api-key identity == director == operator+).

Run: <venv>/bin/python -m pytest stewie/server/test_ns_routes.py -q
"""
import importlib

import pytest
from fastapi.testclient import TestClient

_PW = "a-strong-passphrase"
_M = {"body": "moon", "orders": []}


@pytest.fixture()
def deps(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWIE_DIRECTORS", "")
    from stewie.server import operators as OPS
    importlib.reload(OPS)
    from stewie.server import deps as DEPS
    importlib.reload(DEPS)
    for role in ("guest", "trainee", "operator", "director"):
        OPS.create_active(f"{role}@x.com", _PW, role=role, by="test")
    return DEPS


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


def test_namespace_for_confines_suboperators_to_sandbox(deps):
    nf = deps.namespace_for
    assert nf("guest@x.com") == ("sandbox", "guest@x.com")              # forced sandbox
    assert nf("trainee@x.com") == ("sandbox", "trainee@x.com")
    assert nf("guest@x.com", "live") == ("sandbox", "guest@x.com")      # cannot escape to live
    assert nf("operator@x.com") == ("live", None)                       # operator+ -> live
    assert nf("director@x.com") == ("live", None)
    assert nf("operator@x.com", "sandbox") == ("sandbox", "operator@x.com")   # opt-in draft


def test_sandbox_draft_hidden_from_live_then_published(client):
    c, key = client
    h = {"X-API-Key": key}
    r = c.post("/missions/Draft?ns=sandbox", headers=h, json=_M)
    assert r.status_code == 200 and r.json()["namespace"] == "sandbox", r.text
    assert not any(m["name"] == "draft" for m in c.get("/missions", headers=h).json()["missions"])   # not live
    assert any(m["name"] == "draft"
               for m in c.get("/missions?ns=sandbox", headers=h).json()["missions"])                 # in sandbox
    assert c.post("/missions/Draft/publish", headers=h).json()["ok"] is True                         # promote
    assert any(m["name"] == "draft" for m in c.get("/missions", headers=h).json()["missions"])        # now live


def test_publish_missing_draft_is_false(client):
    c, key = client
    r = c.post("/missions/ghost/publish", headers={"X-API-Key": key})
    assert r.status_code == 200 and r.json()["ok"] is False
