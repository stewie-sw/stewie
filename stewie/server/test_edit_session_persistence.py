"""[REQ:GW-08] The GW-08 edit session is DURABLE (Phase 0 persistence): a session's keep-outs, markers,
versioned before/after audit, and undo state SURVIVE a server restart.

Before this, the registry was a process-wide dict lost on every restart (the single clearest persistence
defect in ``design/STEWIE_persistence_db_design_2026-07-07.md``). The store now write-throughs to
``server.db`` -- Postgres/PostGIS in production, a per-``$STEWIE_DATA_DIR`` SQLite file in CI/dev (which is
why this runs with NO Postgres). ``drop_in_memory_cache()`` simulates the restart: it forgets every cached
EditSession instance AND drops the DB engine + connection pool, so ``get_session`` MUST reload from the
durable rows -- the must-fix proof.

Uses no data at all (the store holds only operator-drawn geometry, exactly like ``test_edit_session.py``).
"""
import pytest
from fastapi.testclient import TestClient

from stewie.server import edit_session as ES


@pytest.fixture(autouse=True)
def _reset_sessions():
    ES.reset()
    yield
    ES.reset()


@pytest.fixture()
def client():
    from stewie.server import server as srv
    return TestClient(srv.app)


# ---- the must-fix: a full session (keep-outs + markers + audit + undo) survives a restart ----------

def test_session_survives_a_simulated_restart():
    # author a session: two keep-outs, a marker, then a modify and an undo (a non-trivial audit + undo state)
    sess = ES.new_session()
    sid = sess.id
    ko1 = sess.create("circle", {"cx": 10.0, "cy": 5.0, "r": 3.0})
    sess.create("polygon", {"ring": [[0, 0], [10, 0], [10, 10]]})
    sess.create_marker({"x": 12.0, "y": -4.0, "otype": "beacon", "label": "Nav beacon"})
    sess.modify(ko1["fid"], "circle", {"cx": 99.0, "cy": 99.0, "r": 7.0})
    sess.undo()   # revert the modify -> ko1 back to (10,5,3); version now 5 (3 creates + modify + undo)

    before_features = sess.current_features()
    before_markers = sess.current_markers()
    before_audit = sess.audit()
    before_version = sess.version
    assert before_version == 5 and len(before_features) == 2 and len(before_markers) == 1
    assert before_features[0]["cx"] == 10.0   # the undo restored the pre-modify geometry

    # --- SIMULATE A RESTART: all in-memory state (cache + engine/pool) gone; durable rows persist ---
    ES.drop_in_memory_cache()

    reloaded = ES.get_session(sid)
    assert reloaded is not None, "session was LOST across the restart (the must-fix defect)"
    assert reloaded is not sess, "a fresh instance was reconstructed from the store, not the old object"

    # keep-outs, markers, version, and the full audit trail all round-trip exactly
    assert reloaded.version == before_version
    assert reloaded.current_features() == before_features
    assert reloaded.current_markers() == before_markers
    assert reloaded.audit() == before_audit

    # undo still WORKS after the reload (walks the reconstructed audit LIFO, no redo) and itself persists.
    # The modify (v4) is ALREADY undone, so the reconstructed undone-targets set correctly skips it and the
    # next undo reverts the next-prior live edit -- the marker.create (v3).
    undone = reloaded.undo()
    assert undone["reverted_op"] == "marker.create"
    assert reloaded.version == before_version + 1
    assert reloaded.current_markers() == []               # the marker is compensated away
    assert reloaded.current_features()[0]["cx"] == 10.0   # ko1 keeps its undo-restored geometry


def test_audit_before_after_survives_restart_byte_identical():
    sess = ES.new_session()
    sid = sess.id
    f = sess.create("circle", {"cx": 1.0, "cy": 2.0, "r": 4.0})
    sess.delete(f["fid"])
    expected = sess.audit()
    assert expected[0]["op"] == "create" and expected[0]["before"] is None
    assert expected[1]["op"] == "delete" and expected[1]["after"] is None

    ES.drop_in_memory_cache()

    reloaded = ES.get_session(sid)
    assert reloaded is not None
    assert reloaded.audit() == expected               # before/after JSON round-trips exactly


def test_marker_fields_survive_restart():
    sess = ES.new_session()
    sid = sess.id
    sess.create_marker({"x": 7.0, "y": 8.0, "otype": "antenna", "label": "relay"})

    ES.drop_in_memory_cache()

    reloaded = ES.get_session(sid)
    assert reloaded is not None
    m = reloaded.current_markers()
    assert len(m) == 1 and m[0]["otype"] == "antenna" and m[0]["label"] == "relay"
    assert m[0]["fid"].startswith("mk")


def test_empty_session_row_survives_restart():
    """An empty session (minted, no edits) is persisted at v0, so a restart before any edit still finds it."""
    sid = ES.new_session().id

    ES.drop_in_memory_cache()

    reloaded = ES.get_session(sid)
    assert reloaded is not None and reloaded.version == 0
    assert reloaded.current_features() == [] and reloaded.current_markers() == []


def test_fid_sequence_survives_restart_so_new_fids_do_not_collide():
    sess = ES.new_session()
    sid = sess.id
    sess.create("circle", {"cx": 0.0, "cy": 0.0, "r": 1.0})   # ko1

    ES.drop_in_memory_cache()

    reloaded = ES.get_session(sid)
    assert reloaded is not None
    new = reloaded.create("circle", {"cx": 5.0, "cy": 5.0, "r": 1.0})
    assert new["fid"] == "ko2"                       # the fid counter reloaded (not reset to ko1)
    assert len(reloaded.current_features()) == 2


def test_unknown_session_after_restart_is_none():
    ES.drop_in_memory_cache()
    assert ES.get_session("deadbeefdeadbeef") is None


# ---- the ROUTE path benefits too: a session authored via the backend routes reloads after a restart --

def test_route_state_survives_restart(client):
    sid = client.post("/edit/session").json()["session"]
    cr = client.post(f"/edit/session/{sid}/keepout", json={"kind": "circle", "cx": 5, "cy": 5, "r": 2})
    assert cr.status_code == 200 and cr.json()["version"] == 1

    ES.drop_in_memory_cache()                        # restart: the router's in-memory registry is gone

    got = client.get(f"/edit/session/{sid}")
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["version"] == 1 and len(body["features"]) == 1
    assert body["features"][0]["cx"] == 5.0
    assert body["audit"][-1]["op"] == "create"
