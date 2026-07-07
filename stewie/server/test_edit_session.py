"""[REQ:GW-08] Mission-feature EDIT SESSION (= ED-01): create / delete / undo keep-outs through backend
routes with a versioned audit, and the planner reads the session's current set (a session keep-out routes
the mission around it -- the same behavior a client-supplied payload.keepout had, now sourced server-side).

Real Haworth DEM only via the live /plan path (no synthetic terrain); the store tests use no data at all.
"""
import pytest
from fastapi.testclient import TestClient

from stewie.server import edit_session as ES


@pytest.fixture(autouse=True)
def _reset_sessions():
    """The session registry is a process-global; reset it before each test (conftest is off-limits)."""
    ES.reset()
    yield
    ES.reset()


@pytest.fixture()
def client():
    # conftest sets STEWIE_DEV_OPEN=1 (keyless open) + an isolated data dir; require_auth reads the env at
    # request time, so a plain TestClient over the built app authenticates keyless for /plan.
    from stewie.server import server as srv
    return TestClient(srv.app)


# ---- store: versioned audit + before/after + undo ------------------------------------------------

def test_store_create_bumps_version_and_records_before_after():
    sess = ES.new_session()
    assert sess.version == 0 and sess.current_features() == []
    f = sess.create("circle", {"cx": 10.0, "cy": 5.0, "r": 3.0})
    assert sess.version == 1 and f["kind"] == "circle" and f["fid"]
    rec = sess.audit()[-1]
    assert rec["op"] == "create" and rec["version"] == 1
    assert rec["before"] is None and rec["after"]["cx"] == 10.0     # audit carries the after-state


def test_store_undo_of_create_removes_the_feature_and_appends_history():
    sess = ES.new_session()
    f = sess.create("circle", {"cx": 1.0, "cy": 2.0, "r": 4.0})
    assert len(sess.current_features()) == 1
    undone = sess.undo()
    assert undone["reverted_op"] == "create" and undone["fid"] == f["fid"]
    assert sess.current_features() == []                            # the create is compensated
    assert sess.version == 2                                        # undo is itself a versioned edit
    assert sess.audit()[-1]["op"] == "undo"                        # history is APPENDED, not deleted


def test_store_modify_records_before_and_after():
    sess = ES.new_session()
    f = sess.create("circle", {"cx": 1.0, "cy": 1.0, "r": 2.0})
    new = sess.modify(f["fid"], "circle", {"cx": 9.0, "cy": 9.0, "r": 5.0})
    assert new["cx"] == 9.0 and sess.version == 2
    rec = sess.audit()[-1]
    assert rec["op"] == "modify" and rec["before"]["cx"] == 1.0 and rec["after"]["cx"] == 9.0
    # undo restores the prior geometry
    sess.undo()
    assert sess.current_features()[0]["cx"] == 1.0


def test_store_undo_of_delete_restores_the_feature():
    sess = ES.new_session()
    f = sess.create("polygon", {"ring": [[0, 0], [10, 0], [10, 10]]})
    sess.delete(f["fid"])
    assert sess.current_features() == []
    sess.undo()                                                    # compensate the delete
    restored = sess.current_features()
    assert len(restored) == 1 and restored[0]["fid"] == f["fid"] and restored[0]["kind"] == "polygon"


def test_store_undo_with_nothing_to_undo_raises():
    sess = ES.new_session()
    with pytest.raises(ValueError):
        sess.undo()


def test_store_rejects_bad_geometry():
    sess = ES.new_session()
    with pytest.raises(ValueError):
        sess.create("circle", {"cx": 0, "cy": 0, "r": 0})          # r must be > 0
    with pytest.raises(ValueError):
        sess.create("polygon", {"ring": [[0, 0], [1, 1]]})         # < 3 vertices


def test_to_planner_keepouts_projects_map_frame_into_the_order_frame():
    # The exact planAuthor.js _keepoutsForFrame transform: ox = X - anchorX ; oy = anchorY - Y.
    sess = ES.new_session()
    sess.create("circle", {"cx": 40.0, "cy": 0.0, "r": 18.0})
    kos = sess.to_planner_keepouts((0.0, 0.0))
    assert kos == [{"x": 40.0, "y": 0.0, "r": 18.0}]               # planner_routing {x,y,r} schema


# ---- routes: create / delete / undo through the backend ------------------------------------------

def test_edit_session_routes_create_delete_undo(client):
    mk = client.post("/edit/session")
    assert mk.status_code == 200, mk.text
    sid = mk.json()["session"]
    assert sid and mk.json()["version"] == 0

    cr = client.post(f"/edit/session/{sid}/keepout", json={"kind": "circle", "cx": 5, "cy": 5, "r": 2})
    assert cr.status_code == 200, cr.text
    d = cr.json()
    assert d["version"] == 1 and len(d["features"]) == 1
    fid = d["feature"]["fid"]
    assert d["audit"][-1]["op"] == "create"                        # versioned audit surfaced on the route

    # the session is the source of truth -- GET returns the same live set
    got = client.get(f"/edit/session/{sid}").json()
    assert got["version"] == 1 and got["features"][0]["fid"] == fid

    dele = client.delete(f"/edit/session/{sid}/keepout/{fid}")
    assert dele.status_code == 200 and dele.json()["features"] == [] and dele.json()["version"] == 2

    un = client.post(f"/edit/session/{sid}/undo")
    assert un.status_code == 200, un.text
    assert un.json()["undone"]["reverted_op"] == "delete"
    assert len(un.json()["features"]) == 1 and un.json()["features"][0]["fid"] == fid   # undo restored it


def test_edit_session_modify_route(client):
    sid = client.post("/edit/session").json()["session"]
    fid = client.post(f"/edit/session/{sid}/keepout",
                      json={"kind": "circle", "cx": 1, "cy": 1, "r": 2}).json()["feature"]["fid"]
    mod = client.patch(f"/edit/session/{sid}/keepout/{fid}",
                       json={"kind": "circle", "cx": 8, "cy": 8, "r": 4})
    assert mod.status_code == 200, mod.text
    d = mod.json()
    assert d["version"] == 2 and d["feature"]["cx"] == 8.0 and d["features"][0]["r"] == 4.0
    assert client.patch(f"/edit/session/{sid}/keepout/nope",
                        json={"kind": "circle", "cx": 0, "cy": 0, "r": 1}).status_code == 404


def test_edit_session_unknown_is_404(client):
    assert client.get("/edit/session/deadbeef").status_code == 404
    assert client.post("/edit/session/deadbeef/keepout",
                       json={"kind": "circle", "cx": 0, "cy": 0, "r": 1}).status_code == 404


# ---- the planner READS the session's keep-outs (regression: a session keep-out reroutes the plan) --

_ORDERS = [{"action": "cut", "kind": "cut", "x": 0, "y": 0, "footprint_m2": 36, "depth_m": 0.1},
           {"action": "fill", "kind": "fill", "x": 40, "y": 0, "footprint_m2": 36, "depth_m": 0.1}]


def test_plan_without_a_session_keepout_is_feasible(client):
    """Control: the cut->fill mission is feasible with no keep-out (mirrors test_route_geometry)."""
    r = client.post("/plan", json={"name": "ctl", "body": "moon", "site": "haworth", "orders": _ORDERS})
    assert r.status_code == 200, r.text
    assert r.json()["feasible"] is True


def test_plan_reads_edit_session_keepout_and_routes_around_it(client):
    """The planner READS the edit session's current keep-out set: a session circle enclosing the fill
    (order-frame {x:40,y:0,r:18}) makes the haul infeasible -- the SAME outcome a client-supplied
    payload.keepout produced (behavior preserved, source moved to the server-owned session)."""
    sid = client.post("/edit/session").json()["session"]
    # map-frame circle at (40,0) r18; anchor_xy=(0,0) projects it to order-frame {x:40,y:0,r:18}
    cr = client.post(f"/edit/session/{sid}/keepout", json={"kind": "circle", "cx": 40, "cy": 0, "r": 18})
    assert cr.status_code == 200 and cr.json()["version"] == 1

    r = client.post("/plan", json={"name": "es", "body": "moon", "site": "haworth", "orders": _ORDERS,
                                   "edit_session": sid, "anchor_xy": [0.0, 0.0]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["feasible"] is False                              # the session keep-out blocked the haul
    assert body["totals"]["blocked_legs"] >= 1


def test_plan_with_session_but_no_anchor_is_400(client):
    """A session WITH features but no anchor_xy cannot be projected into the order frame -> honest 400."""
    sid = client.post("/edit/session").json()["session"]
    client.post(f"/edit/session/{sid}/keepout", json={"kind": "circle", "cx": 40, "cy": 0, "r": 18})
    r = client.post("/plan", json={"name": "noanchor", "body": "moon", "site": "haworth",
                                   "orders": _ORDERS, "edit_session": sid})
    assert r.status_code == 400 and "anchor_xy" in r.json()["error"]
