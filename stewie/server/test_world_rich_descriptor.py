"""[REQ:DT-05] GET /world is the authoritative RICH world descriptor: geometry + datum + provenance PLUS
the real observed/mutated enrichment and an explicit completeness/freshness declaration -- not geometry
with enrichment deferred to defaults. A consumer keys on `enrichment.complete` and reads the measured
observed_fraction / mutated rather than mistaking a bare descriptor for the full world model."""
import importlib

import pytest
from fastapi.testclient import TestClient

H = {"X-API-Key": "test-key"}
_TERRAIN_MISSION = {"name": "pad-A", "body": "moon", "charger": [0, 0],
                    "orders": [{"action": "src", "kind": "cut", "x": 5.0, "y": 5.0,
                                "footprint_m2": 36.0, "depth_m": 0.3}]}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_API_KEY", "test-key")
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")             # resolves to the operator identity for resync
    from stewie.server import objects as OBJ
    importlib.reload(OBJ)
    from stewie.server import state as S
    importlib.reload(S)
    monkeypatch.setattr(S, "_TWIN", None)
    monkeypatch.setattr(S, "_TWINS", {})
    import stewie.server.server as srv
    importlib.reload(srv)
    yield TestClient(srv.app)
    monkeypatch.undo()
    importlib.reload(srv)


def test_world_declares_completeness_and_carries_enrichment(client):
    d = client.get("/world?site=haworth", headers=H).json()
    assert d["ok"] is True
    # the descriptor declares it is complete (enrichment present, not deferred) + carries freshness.
    en = d["enrichment"]
    assert en["complete"] is True
    for k in ("observed", "twin_version", "as_built_version", "mutated", "world_committed"):
        assert k in en
    # the WorldState itself now carries the real (not default-only) observed/mutated fields.
    assert "observed_fraction" in d["world"] and "mutated" in d["world"]


def test_world_observed_fraction_reflects_the_real_observed_twin(client):
    # a bare world has zero observed coverage; a resync that patches the observed twin lifts it.
    before = client.get("/world?site=haworth", headers=H).json()
    assert before["world"]["observed_fraction"] == 0.0 and before["enrichment"]["observed"] is True
    r = client.post("/twin/resync", headers=H, json={
        "heights_m": [[1.0, 1.0], [1.0, 1.0]], "origin_rc": [100, 100], "provenance": "dt05", "site": "haworth"})
    assert r.status_code == 200, r.text
    after = client.get("/world?site=haworth", headers=H).json()
    assert after["world"]["observed_fraction"] > 0.0
    assert after["enrichment"]["twin_version"] >= 1


def test_world_mutated_reflects_a_recorded_build(client):
    assert client.get("/world?site=haworth", headers=H).json()["world"]["mutated"] is False
    r = client.post("/twin/terrain/haworth", headers=H, json={"mission": _TERRAIN_MISSION})
    assert r.status_code == 200, r.text
    d = client.get("/world?site=haworth", headers=H).json()
    assert d["world"]["mutated"] is True                    # construction recorded a build -> terrain mutated
    assert d["enrichment"]["as_built_version"] >= 1
    assert d["enrichment"]["world_committed"] is True       # the linked world transaction was committed


def test_world_404s_a_site_without_a_dem_bundle(client):
    r = client.get("/world?site=amundsen_rim", headers=H)   # a real site id whose bundle is not on disk
    assert r.status_code == 404
