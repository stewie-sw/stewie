"""Loop: visualize CurrentTerrainView provenance. GET /world/terrain_view returns the per-cell
observed/as-built/pristine breakdown + provenance counters; GET /world/terrain_view.png renders the
source map as a colored raster. Real Haworth DEM (skipped if absent); real TerrainMemory + twin -- no
synthetic terrain."""
from __future__ import annotations

import importlib
import os

import pytest
from fastapi.testclient import TestClient

_BUNDLE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                       "samples", "lunar_dem", "haworth_10km_5m")
H = {"X-API-Key": "test-key"}
_MISSION = {"name": "prov-pad", "body": "moon", "charger": [0, 0],
            "orders": [{"action": "src", "kind": "cut", "x": 5.0, "y": 5.0,
                        "footprint_m2": 36.0, "depth_m": 0.3}]}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_API_KEY", "test-key")
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")
    from stewie.server import state as S
    monkeypatch.setattr(S, "_TWIN", None)
    monkeypatch.setattr(S, "_WSS", None)
    import stewie.server.server as srv
    importlib.reload(srv)
    yield TestClient(srv.app)
    monkeypatch.undo()
    importlib.reload(srv)


@pytest.mark.skipif(not os.path.isdir(_BUNDLE), reason="Haworth DEM bundle absent")
def test_terrain_view_starts_all_pristine(client):
    d = client.get("/world/terrain_view?site=haworth", headers=H).json()
    assert d["ok"] is True
    p = d["provenance"]
    assert p["as_built_version"] == 0 and p["twin_version"] == 0 and p["observed_fraction"] == 0.0
    assert p["cells"]["as_built"] == 0 and p["cells"]["observed"] == 0
    assert p["cells"]["pristine"] == p["rows"] * p["cols"]     # everything pristine before any build/resync


@pytest.mark.skipif(not os.path.isdir(_BUNDLE), reason="Haworth DEM bundle absent")
def test_terrain_view_reflects_recorded_build_and_resync(client):
    # record a conserved build (as-built) and a measured resync (observed)
    assert client.post("/twin/terrain/haworth", headers=H, json={"mission": _MISSION}).status_code == 200
    assert client.post("/twin/resync", headers=H, json={
        "heights_m": [[0.2, 0.2], [0.2, 0.2]], "origin_rc": [100, 200], "provenance": "COLMAP"}).status_code == 200
    d = client.get("/world/terrain_view?site=haworth", headers=H).json()
    p = d["provenance"]
    assert p["as_built_version"] >= 1                          # the recorded build folded in
    assert p["twin_version"] >= 1 and p["observed_fraction"] > 0.0
    assert p["cells"]["observed"] >= 4                         # the 2x2 measured patch
    assert p["cells"]["as_built"] >= 1                         # at least one imprinted cell
    # provenance conserves: the three classes partition the grid exactly
    assert (p["cells"]["pristine"] + p["cells"]["as_built"] + p["cells"]["observed"]
            == p["rows"] * p["cols"])


@pytest.mark.skipif(not os.path.isdir(_BUNDLE), reason="Haworth DEM bundle absent")
def test_terrain_view_png_is_a_real_png(client):
    r = client.get("/world/terrain_view.png?site=haworth&max_px=256", headers=H)
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n" and len(r.content) > 0   # PNG magic


def test_terrain_view_requires_auth(client, monkeypatch):
    monkeypatch.delenv("STEWIE_DEV_OPEN", raising=False)
    assert client.get("/world/terrain_view?site=haworth").status_code in (401, 403)
