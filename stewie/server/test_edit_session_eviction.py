"""SR-09 [REQ:GW-08]: anonymous session churn must not delete an operator's authored keep-outs, and a
plan must never silently route through geometry it failed to load.

`/edit/session` is keyless by design and documented as such. What was NOT designed was the eviction
rule behind it: `db._create_session_row` evicted by `created_at.asc()`, so the LONGEST-LIVED session --
precisely the active operator's -- was always the first victim, and the delete took its `EditAuditRow`
with it, destroying the versioned before/after history the GW-08 doctrine says undo must never delete.

The review reproduced the full chain with MAX_SESSIONS=3: a victim session holding a real circle
keep-out was evicted by churn, `get_session` returned None, and `_merge_session_keepouts` left
`payload['keepouts'] == []` with no error -- so the next Plan returned 200 for a route straight through
the barrier the operator had drawn. An anonymous script sending MAX_SESSIONS requests was enough.

Two fixes, tested here: only a session holding NO authored work is evictable (a flood of empty sessions
evicts itself, and a full store of authored sessions refuses new ones rather than destroying geometry),
and a SUPPLIED-but-unknown session id now refuses instead of silently planning without its keep-outs.

Run: <venv>/bin/python -m pytest stewie/server/test_edit_session_eviction.py -q
"""
from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

_CIRCLE = {"kind": "circle", "cx": 5.0, "cy": 5.0, "r": 2.0}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_API_KEY", "test-key")
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    import stewie.server.server as srv
    importlib.reload(srv)
    from stewie.server import edit_session as ES
    monkeypatch.setattr(ES, "MAX_SESSIONS", 3)          # small bound -> the flood is 3 requests
    yield TestClient(srv.app)
    monkeypatch.undo()
    importlib.reload(srv)


def _new(c) -> str:
    r = c.post("/edit/session")
    assert r.status_code == 200, r.text
    return r.json()["session"]


def test_authored_session_survives_an_anonymous_flood(client):
    """The SR-09 attack: churn must not delete the operator's drawn geometry."""
    victim = _new(client)
    assert client.post(f"/edit/session/{victim}/keepout", json=_CIRCLE).status_code == 200

    for _ in range(6):                                   # twice the bound, all empty
        client.post("/edit/session")

    r = client.get(f"/edit/session/{victim}")
    assert r.status_code == 200, "the operator's authored session was evicted by anonymous churn"
    feats = r.json()["features"]
    assert len(feats) == 1, f"the authored keep-out was lost: {feats}"


def test_authored_session_keeps_its_gw08_audit(client):
    """Eviction also deleted EditAuditRow -- undo must never lose history."""
    victim = _new(client)
    client.post(f"/edit/session/{victim}/keepout", json=_CIRCLE)
    for _ in range(6):
        client.post("/edit/session")
    st = client.get(f"/edit/session/{victim}").json()
    assert st["audit"], "the session's versioned audit tail was destroyed"


def test_empty_sessions_evict_each_other_so_the_store_stays_bounded(client):
    """The bound still holds -- an empty session is evictable, which is what makes the flood self-limiting."""
    first = _new(client)
    for _ in range(5):
        client.post("/edit/session")
    assert client.get(f"/edit/session/{first}").status_code == 404


def test_full_store_of_authored_sessions_refuses_rather_than_deleting_work(client):
    """A rejected new session is recoverable; deleted no-go geometry is not."""
    for _ in range(3):                                   # fill the bound, every one authored
        sid = _new(client)
        assert client.post(f"/edit/session/{sid}/keepout", json=_CIRCLE).status_code == 200
    r = client.post("/edit/session")
    assert r.status_code == 503, f"expected a refusal, got {r.status_code}: {r.text}"
    assert "authored" in r.text.lower()


def test_plan_refuses_an_unknown_edit_session(client):
    """The silent-corruption half: a supplied-but-unknown session must not plan without its keep-outs."""
    from stewie.server.routers.plan import _merge_session_keepouts
    payload = {"edit_session": "deadbeefdeadbeef", "anchor_xy": [0.0, 0.0], "keepouts": []}
    with pytest.raises(ValueError, match="unknown or expired"):
        _merge_session_keepouts(payload)


def test_plan_still_ignores_a_known_but_empty_session(client):
    """Back-compat: a real session with nothing drawn is legitimately a no-op, not an error."""
    from stewie.server.routers.plan import _merge_session_keepouts
    sid = _new(client)
    payload = {"edit_session": sid, "anchor_xy": [0.0, 0.0], "keepouts": []}
    _merge_session_keepouts(payload)                     # must not raise
    assert payload["keepouts"] == []


def test_plan_merges_a_live_sessions_keepouts(client):
    """The property the silent no-op was hiding: authored geometry actually reaches the plan."""
    from stewie.server.routers.plan import _merge_session_keepouts
    sid = _new(client)
    assert client.post(f"/edit/session/{sid}/keepout", json=_CIRCLE).status_code == 200
    payload = {"edit_session": sid, "anchor_xy": [0.0, 0.0], "keepouts": []}
    _merge_session_keepouts(payload)
    assert payload["keepouts"], "the session's keep-out never reached the plan payload"
