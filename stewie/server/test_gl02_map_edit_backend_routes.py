"""[REQ:GL-02] The GIS map's identify / measure / edit sessions operate on the map's REAL geometry (the
selenographic order/CRS frame the drapes render), and every mission edit is written ONLY through backend
routes -- never the map's client-side vector layer -- so a keep-out an operator draws on the map appears in
the mission request and routes the mission around it.

GL-02 is the PARENT row that GW-07 (selection/identify) and GW-08 (the edit session) each extend; its FRAMING
records that the keep-out->routes-around behavior shipped as GW-08. This file proves the three GL-02 clauses
COMPOSE into the parent contract, driven end-to-end through the real HTTP surface a client uses:

  (A) IDENTIFY on the map's real geometry -- GET /world/point resolves a clicked cell to the site DEM's
      ACTUAL per-cell value (elevation off the real LOLA Haworth DEM), and an out-of-tile click returns
      in_bounds=false with NO fabricated value. (the GW-07 selection surface)
  (B) EDIT writes ONLY through backend routes -- an authored keep-out enters the server-owned, versioned
      edit-session store via POST /edit/session/{sid}/keepout (geometry in the map CRS IAU_2015:30135, the
      frame the client draws), and the session GET is the source of truth; the map layer is never the write
      path. A fresh session is EMPTY (version 0) until a route write occurs. (the GW-08 edit session)
  (C) A keep-out drawn on the map appears in the MISSION REQUEST and routes around it -- POST /plan reads the
      session by its opaque id + order-frame anchor and folds the map-frame keep-out into the planner, so a
      circle enclosing the fill makes the haul infeasible; the same mission with no session keep-out is
      feasible. Proven on the REAL Haworth DEM via the live /plan path (no synthetic terrain).

The individual behaviors are cited by [REQ:GW-07] (test_gw07_point_inspect.py) and [REQ:GW-08]
(test_edit_session.py); this file is the GL-02 parent acceptance that they compose the map<->backend<->
mission-request contract.
"""
import math

import pytest
from fastapi.testclient import TestClient

from stewie.server import edit_session as ES


@pytest.fixture(autouse=True)
def _reset_sessions():
    """The session registry is a process-global; reset it before/after each test (conftest is off-limits)."""
    ES.reset()
    yield
    ES.reset()


@pytest.fixture()
def client():
    # conftest sets STEWIE_DEV_OPEN=1 (keyless open) + an isolated data dir; /world/point is a public map-data
    # read and /edit/* is capability-gated by the opaque session id, so a plain TestClient reaches both keyless.
    from stewie.server import server as srv
    return TestClient(srv.app)


# ---- (A) IDENTIFY operates on the map's real geometry ---------------------------------------------

def test_identify_reads_the_maps_real_cell_geometry_not_a_fabrication(client):  # [REQ:GL-02]
    """A click inside the Haworth work area resolves to the site DEM cell and returns the ACTUAL elevation
    off the real LOLA DEM (a finite metre reading), while a click far outside the tile is honestly
    in_bounds=false with no value -- the identify session reads the map's real geometry, never invents it."""
    r = client.get("/world/point?site=haworth&x=60&y=60")            # a cell inside the Haworth work area
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] is True and d["cell"]["in_bounds"] is True
    dem = {a["id"]: a for a in d["attributes"]}["base.dem"]          # elevation off the real LOLA Haworth DEM
    assert dem["available"] is True and dem["unit"] == "m"
    assert isinstance(dem["value"], float) and math.isfinite(dem["value"])

    out = client.get("/world/point?site=haworth&x=9000000&y=9000000").json()   # far outside the tile
    assert out["ok"] is True and out["cell"]["in_bounds"] is False              # honest 'no data', no value


# ---- (B) EDIT writes ONLY through backend routes (the map CRS, server-owned, versioned) -----------

def test_edit_writes_only_through_the_backend_route_not_the_map_layer(client):  # [REQ:GL-02]
    """A fresh edit session is EMPTY at version 0 -- the map layer cannot seed it. A keep-out enters ONLY by
    posting a map-frame (IAU_2015:30135 metres) geometry through /edit/session/{sid}/keepout; the server-owned
    session GET is then the source of truth (the drawn frame preserved: cx/cy/r as authored), and the versioned
    audit records the create. The write path is the backend route, never a direct map-layer mutation."""
    sid = client.post("/edit/session").json()["session"]
    fresh = client.get(f"/edit/session/{sid}").json()
    assert fresh["version"] == 0 and fresh["features"] == []          # empty until a ROUTE write occurs

    cr = client.post(f"/edit/session/{sid}/keepout",                  # the ONLY write path: the backend route
                     json={"kind": "circle", "cx": 40.0, "cy": 0.0, "r": 18.0})
    assert cr.status_code == 200, cr.text
    body = cr.json()
    assert body["version"] == 1                                       # a versioned edit
    feat = body["feature"]
    assert feat["kind"] == "circle" and (feat["cx"], feat["cy"], feat["r"]) == (40.0, 0.0, 18.0)

    got = client.get(f"/edit/session/{sid}").json()                  # the session store is the source of truth
    assert got["version"] == 1 and len(got["features"]) == 1
    assert got["features"][0]["fid"] == feat["fid"]
    assert got["audit"][-1]["op"] == "create"                        # the edit is on the versioned audit trail


# ---- (C) a keep-out drawn on the map appears in the mission request and routes around it -----------

_ORDERS = [{"action": "cut", "kind": "cut", "x": 0, "y": 0, "footprint_m2": 36, "depth_m": 0.1},
           {"action": "fill", "kind": "fill", "x": 40, "y": 0, "footprint_m2": 36, "depth_m": 0.1}]


def test_map_keepout_enters_the_mission_request_and_routes_around_it(client):  # [REQ:GL-02]
    """CONTROL: the cut->fill mission on real Haworth is feasible with no keep-out. Then an operator draws a
    keep-out on the map (a map-frame circle at (40,0) r18 enclosing the fill) through the backend edit route;
    POST /plan reads that session by its opaque id + the order-frame anchor, folds the map-frame keep-out into
    the mission request, and the planner routes the haul around it -- the mission is now infeasible with a
    blocked leg. The keep-out drawn on the map appeared in the mission request and changed the plan."""
    ctl = client.post("/plan", json={"name": "gl02-ctl", "body": "moon", "site": "haworth", "orders": _ORDERS})
    assert ctl.status_code == 200, ctl.text
    assert ctl.json()["feasible"] is True                            # baseline: the haul is feasible

    sid = client.post("/edit/session").json()["session"]
    cr = client.post(f"/edit/session/{sid}/keepout",                 # draw the keep-out on the map (map frame)
                     json={"kind": "circle", "cx": 40, "cy": 0, "r": 18})
    assert cr.status_code == 200 and cr.json()["version"] == 1

    r = client.post("/plan", json={"name": "gl02-ko", "body": "moon", "site": "haworth", "orders": _ORDERS,
                                   "edit_session": sid, "anchor_xy": [0.0, 0.0]})   # anchor projects map->order
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan["feasible"] is False                                 # the map keep-out routed the mission out
    assert plan["totals"]["blocked_legs"] >= 1


def test_session_keepout_without_an_anchor_is_an_honest_400(client):  # [REQ:GL-02]
    """A session carrying map-frame features but no anchor_xy cannot be projected into the order frame the
    planner consumes -- the mission request refuses with an honest 400 rather than dropping the keep-out."""
    sid = client.post("/edit/session").json()["session"]
    client.post(f"/edit/session/{sid}/keepout", json={"kind": "circle", "cx": 40, "cy": 0, "r": 18})
    r = client.post("/plan", json={"name": "gl02-noanchor", "body": "moon", "site": "haworth",
                                   "orders": _ORDERS, "edit_session": sid})
    assert r.status_code == 400 and "anchor_xy" in r.json()["error"]
