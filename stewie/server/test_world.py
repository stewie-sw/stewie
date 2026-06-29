"""FS-02 / TW-05 / §25 Phase 1: the /world route returns the typed WorldState descriptor whose payload
matches the contract spine -- grid geometry from the REAL bundled Haworth DEM, lunar datum, provenance.
404 when a site's bundle is absent. TestClient.

Run: <venv>/bin/python -m pytest stewie/server/test_world.py -q
"""
import importlib

import pytest
from fastapi.testclient import TestClient

from stewie.contracts import WorldState


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_API_KEY", "test-key")
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    import stewie.server.server as srv
    importlib.reload(srv)
    # /world is auth-gated (#246); this fixture configures a key, so the client must send it.
    yield TestClient(srv.app, headers={"X-API-Key": "test-key"})
    monkeypatch.undo()
    importlib.reload(srv)


def test_world_payload_matches_contract(client):
    r = client.get("/world?site=haworth")
    assert r.status_code == 200, r.text
    w = WorldState.model_validate(r.json()["world"])           # payload matches the spine
    assert w.rows > 0 and w.cols > 0 and w.cell_m > 0
    assert w.dem_source == "haworth_10km_5m" and w.datum_radius_m == 1737400 and w.body == "moon"


def test_unknown_site_is_404(client):
    r = client.get("/world?site=nonesuch")                     # absent bundle -> degraded 404
    assert r.status_code == 404 and r.json()["ok"] is False
