"""[REQ:AR-003] Command authority is WITHHELD when the signed release is not durably persisted.

The Phase-0 containment for AR-003: ``_command_authority`` returned ``authorized:True`` / ``namespace:live``
whenever an in-memory release object existed, regardless of whether the durable write succeeded. A
best-effort persist failure (surfaced honestly as ``revision_persisted:false``) therefore still claimed live
command authority for a release that cannot be bound or recovered by a later run/RC -- the "released but
unrecoverable" defect. These gates prove the card now tracks durability.

Real endpoint + a real prepared mission's orders (no synthetic plan data); the durable write is failed by
injecting an exception into the db persist call, which is exactly how a real disk/store outage surfaces.
"""
from fastapi.testclient import TestClient

from stewie.server.server import app


def _release(c: TestClient, mission_id: str):
    sm = c.get("/sample_mission/01_flatten_pad").json()          # a REAL prepared mission (cut/fill orders)
    return c.post("/executive/release-plan",
                  json={"orders": sm["orders"], "mission_id": mission_id, "body": sm.get("body", "moon")})


def test_ar003_persisted_release_grants_live_authority(monkeypatch, tmp_path):  # [REQ:AR-003]
    """Baseline: a release whose durable write SUCCEEDS carries live, authorized command authority."""
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))         # a real, writable durable store
    c = TestClient(app, base_url="http://127.0.0.1")
    r = _release(c, "ar003-ok")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["revision_persisted"] is True
    ca = j["command_authority"]
    assert ca["authorized"] is True and ca["namespace"] == "live"


def test_ar003_unpersisted_release_withholds_command_authority(monkeypatch, tmp_path):  # [REQ:AR-003]
    """A durable-store failure surfaces ``revision_persisted:false`` AND withholds command authority: the
    card is ``authorized:False``, non-live, with a reason -- never a live/authorized card on an unpersisted
    release. This is the containment: an unrecoverable release cannot grant authority."""
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    from stewie.server import db

    def _boom(*a, **k):
        raise RuntimeError("injected durable-store failure (disk full / permission / rotation)")

    monkeypatch.setattr(db, "persist_release_revision", _boom)   # the real persist path now fails
    c = TestClient(app, base_url="http://127.0.0.1")
    r = _release(c, "ar003-fail")
    assert r.status_code == 200, r.text                          # signing is authoritative; release still returns
    j = r.json()
    assert j["revision_persisted"] is False                      # ...but honestly flags the persist failure...
    ca = j["command_authority"]
    assert ca is not None
    assert ca["authorized"] is False                             # ...and WITHHOLDS live command authority
    assert ca["namespace"] != "live"
    assert ca.get("reason")                                      # names why authority is withheld
    # the descriptive fields are still present (the card is honest, not empty)
    assert ca["plan_hash"] and ca["signed_by"]
