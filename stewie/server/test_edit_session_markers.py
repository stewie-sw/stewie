"""Mission-feature EDIT SESSION -- MARKER (place-object) extension. An operator drops a mission object
(beacon / cache / instrument / sample / antenna) on the IDE map; it persists through the SAME backend
edit-session store the keep-outs use (versioned audit + undo), but as a POINT feature kept SEPARATE from
the keep-out set so a marker never routes the planner around it (a marker annotates; it is not a hazard).

Store tests use no data at all; the route tests drive the built app through a keyless TestClient (conftest
sets STEWIE_DEV_OPEN=1), exactly like test_edit_session.py.
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


# ---- store: markers persist + are audited, separate from keep-outs -------------------------------

def test_marker_create_bumps_version_and_is_audited():
    sess = ES.new_session()
    assert sess.version == 0 and sess.current_markers() == []
    m = sess.create_marker({"x": 12.0, "y": -4.0, "otype": "beacon", "label": "Nav beacon"})
    assert sess.version == 1
    assert m["kind"] == "marker" and m["fid"].startswith("mk")
    assert m["x"] == 12.0 and m["y"] == -4.0 and m["otype"] == "beacon" and m["label"] == "Nav beacon"
    rec = sess.audit()[-1]
    assert rec["op"] == "marker.create" and rec["version"] == 1
    assert rec["before"] is None and rec["after"]["x"] == 12.0


def test_markerin_accepts_the_frontend_markerbody_shape_and_forbids_a_stray_kind():
    """[wiring council] planTools.markerBody now posts {x,y,otype,label}; MarkerIn is extra='forbid', so the
    OLD body that also sent kind:'marker' RequestValidationError'd -> the route 400'd EVERY marker POST and
    markers silently fell back to local-only, never entering the versioned/audited session. Pin both ways so
    the store's own tests (which bypass MarkerIn) can't hide a re-added 'kind' regression."""
    from stewie.server.routers.editsession import MarkerIn
    m = MarkerIn(x=12.0, y=-4.0, otype="beacon", label="Nav B1")   # the FIXED frontend shape validates
    assert m.otype == "beacon" and m.label == "Nav B1"
    with pytest.raises(Exception):                                 # the OLD shape (a stray 'kind') is rejected
        MarkerIn(x=1.0, y=2.0, otype="cache", kind="marker")


def test_a_persist_failure_rolls_back_the_in_memory_edit(monkeypatch):
    """[concurrency council] A mutation is ATOMIC with its write-through: if db.persist_session raises, the
    in-memory session must be UNCHANGED (version, features, audit) -- otherwise in-memory LEADS the durable
    store (the source of truth on restart) and a later GET /state returns an edit the durable store never
    accepted (a three-way client/memory/disk inconsistency)."""
    sess = ES.new_session()
    sess.create("circle", {"cx": 0.0, "cy": 0.0, "r": 5.0})     # one good keep-out (persisted)
    v0, nf0, na0 = sess.version, len(sess.current_features()), len(sess.audit())

    def _boom(*a, **k):
        raise RuntimeError("durable store down")
    monkeypatch.setattr(ES.db, "persist_session", _boom)         # the NEXT persist fails

    with pytest.raises(RuntimeError):
        sess.create("circle", {"cx": 9.0, "cy": 9.0, "r": 2.0})

    assert sess.version == v0                                    # version not bumped
    assert len(sess.current_features()) == nf0                   # the failed feature was rolled back
    assert len(sess.audit()) == na0                              # no orphan audit record left behind


def test_marker_is_kept_out_of_the_keepout_set_and_the_planner_projection():
    """A marker must NEVER become a planner keep-out (it annotates; it is not a hazard)."""
    sess = ES.new_session()
    sess.create("circle", {"cx": 0.0, "cy": 0.0, "r": 5.0})     # a real keep-out
    sess.create_marker({"x": 20.0, "y": 20.0, "otype": "cache", "label": "cache A"})
    assert len(sess.current_features()) == 1                     # only the keep-out is a "feature"
    assert len(sess.current_markers()) == 1
    ko = sess.to_planner_keepouts((0.0, 0.0))                    # the planner-frame keep-outs
    assert len(ko) == 1                                          # the marker is NOT projected as a keep-out


def test_marker_default_label_is_derived_from_the_type():
    sess = ES.new_session()
    m = sess.create_marker({"x": 1.0, "y": 2.0, "otype": "instrument"})
    assert m["label"] and "instrument" in m["label"].lower()


def test_marker_rejects_unknown_type_and_nonfinite_coords():
    sess = ES.new_session()
    with pytest.raises(ValueError):
        sess.create_marker({"x": 1.0, "y": 2.0, "otype": "death-ray"})
    with pytest.raises(ValueError):
        sess.create_marker({"x": float("nan"), "y": 2.0, "otype": "beacon"})
    with pytest.raises(ValueError):
        sess.create_marker({"x": 1.0, "y": float("inf"), "otype": "beacon"})


def test_marker_delete_and_undo():
    sess = ES.new_session()
    m = sess.create_marker({"x": 3.0, "y": 3.0, "otype": "sample"})
    assert len(sess.current_markers()) == 1
    sess.delete_marker(m["fid"])
    assert sess.current_markers() == []
    assert sess.audit()[-1]["op"] == "marker.delete"
    # undo the delete -> the marker is restored (the DT-03 compensating inverse)
    undone = sess.undo()
    assert undone["reverted_op"] == "marker.delete" and undone["fid"] == m["fid"]
    assert len(sess.current_markers()) == 1
    # undo again -> compensates the create -> the marker is gone
    undone2 = sess.undo()
    assert undone2["reverted_op"] == "marker.create"
    assert sess.current_markers() == []


def test_undo_of_markers_does_not_disturb_keepouts():
    """A mixed session: undo walks the SINGLE audit LIFO across both feature classes (keep-out + marker)."""
    sess = ES.new_session()
    ko = sess.create("circle", {"cx": 1.0, "cy": 1.0, "r": 2.0})    # v1
    sess.create_marker({"x": 5.0, "y": 5.0, "otype": "beacon"})     # v2 (last edit)
    sess.undo()                                                     # compensates the marker create only
    assert len(sess.current_markers()) == 0
    assert [f["fid"] for f in sess.current_features()] == [ko["fid"]]   # the keep-out is untouched


def test_state_includes_markers():
    sess = ES.new_session()
    sess.create_marker({"x": 7.0, "y": 8.0, "otype": "antenna", "label": "relay"})
    st = sess.state()
    assert "markers" in st and len(st["markers"]) == 1
    assert st["markers"][0]["otype"] == "antenna"


# ---- routes: the IDE creates/deletes a marker through the backend --------------------------------

def test_route_create_and_delete_marker(client):
    sid = client.post("/edit/session").json()["session"]
    r = client.post(f"/edit/session/{sid}/marker",
                    json={"x": 10.0, "y": -2.0, "otype": "beacon", "label": "B1"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["marker"]["otype"] == "beacon" and body["marker"]["fid"].startswith("mk")
    assert body["version"] == 1 and len(body["markers"]) == 1
    fid = body["marker"]["fid"]
    d = client.delete(f"/edit/session/{sid}/marker/{fid}")
    assert d.status_code == 200 and d.json()["ok"] is True
    assert d.json()["markers"] == []


def test_route_marker_bad_type_is_400(client):
    sid = client.post("/edit/session").json()["session"]
    r = client.post(f"/edit/session/{sid}/marker", json={"x": 1.0, "y": 2.0, "otype": "nope"})
    assert r.status_code == 400
    assert r.json()["ok"] is False


def test_route_marker_unknown_session_is_404(client):
    r = client.post("/edit/session/deadbeef/marker", json={"x": 1.0, "y": 2.0, "otype": "beacon"})
    assert r.status_code == 404
