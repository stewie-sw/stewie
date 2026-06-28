"""W3 (Terrain Memory): GET /twin/terrain/{site} exposes a site's authoritative world-model summary.
Never 500 for an unrecorded site; returns the real persisted state once a mission is recorded. No synthetic
data -- the recorded state comes from a REAL mission folded through the conserved authority."""
import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_API_KEY", "test-key")
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    import stewie.server.server as srv
    importlib.reload(srv)
    yield TestClient(srv.app), "test-key", str(tmp_path)
    monkeypatch.undo()
    importlib.reload(srv)


def test_terrain_route_empty_site_is_not_an_error(client):
    c, key, _dd = client
    r = c.get("/twin/terrain/haworth", headers={"X-API-Key": key})
    assert r.status_code == 200
    j = r.json()
    assert j["recorded"] is False and j["version"] == 0 and j["missions"] == []


def test_terrain_route_returns_recorded_world_state(client):
    c, key, dd = client
    import lode.mission_planner as MP
    from lode.planner_acceptance import record_mission
    from stewie.twin import terrain_memory as TM
    # fold a REAL recorded mission into the site's terrain memory, persist it, then read it via the route
    mem = TM.TerrainMemory(site="haworth", rows=120, cols=120, cell_m=0.5, origin=(-10.0, -10.0))
    m = MP.mission_from_dict({"name": "pad-A", "body": "moon", "charger": [0, 0],
                              "orders": [{"action": "src", "kind": "cut", "x": 5.0, "y": 5.0,
                                          "footprint_m2": 36.0, "depth_m": 0.3}]})
    record_mission(mem, m)
    TM.save_site(dd, mem)
    j = c.get("/twin/terrain/haworth", headers={"X-API-Key": key}).json()
    assert j["recorded"] is True and j["version"] == 1 and j["chain_valid"] is True
    assert j["missions"] == ["pad-A"] and j["max_cut_m"] > 0.0


def test_terrain_route_requires_auth(client):
    c, _key, _dd = client
    assert c.get("/twin/terrain/haworth").status_code in (401, 403)


def test_terrain_record_populates_then_reads_back(client):
    c, key, _dd = client
    mission = {"name": "pad-A", "body": "moon", "charger": [0, 0],
               "orders": [{"action": "src", "kind": "cut", "x": 5.0, "y": 5.0, "footprint_m2": 36.0, "depth_m": 0.3}]}
    r = c.post("/twin/terrain/haworth", headers={"X-API-Key": key}, json={"mission": mission})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["recorded"] is True and j["version"] == 1 and j["max_cut_m"] > 0.0 and j["chain_valid"] is True
    # GET reads back the now-persisted authoritative world state
    g = c.get("/twin/terrain/haworth", headers={"X-API-Key": key}).json()
    assert g["version"] == 1 and g["missions"] == ["pad-A"]
    # a SECOND recorded mission ACCUMULATES (the terrain remembers)
    r2 = c.post("/twin/terrain/haworth", headers={"X-API-Key": key}, json={"mission": {**mission, "name": "pad-B"}})
    assert r2.json()["version"] == 2 and r2.json()["missions"] == ["pad-A", "pad-B"]


def test_terrain_record_requires_operator(client):
    c, _key, _dd = client
    r = c.post("/twin/terrain/haworth",
               json={"mission": {"name": "x", "body": "moon", "charger": [0, 0], "orders": []}})
    assert r.status_code in (401, 403)


def test_terrain_record_rejects_bad_mission(client):
    c, key, _dd = client
    r = c.post("/twin/terrain/haworth", headers={"X-API-Key": key}, json={"mission": {"nonsense": True}})
    assert r.status_code == 400
