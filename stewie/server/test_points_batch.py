"""[REQ:GW-07] The batch /world/points endpoint (the #45 cross-section / transect reader) resolves the site
DEM + composes the CurrentTerrainView ONCE per batch, and must return per-cell values BYTE-IDENTICAL to N
/world/point calls. Real Haworth DEM, no synthetic data."""
import importlib
import json

import pytest
from fastapi.testclient import TestClient

from stewie.server.gis_layers import point_values, points_values

_COORDS = [(60.0, 60.0), (2500.0, 3000.0), (500.0, 1200.0), (1234.0, 5678.0), (-100.0, -100.0)]


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_API_KEY", "test-key")
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")
    from stewie.server import state as S
    importlib.reload(S)
    monkeypatch.setattr(S, "_TWIN", None)
    monkeypatch.setattr(S, "_TWINS", {})
    import stewie.server.server as srv
    importlib.reload(srv)
    yield TestClient(srv.app)
    monkeypatch.undo()
    importlib.reload(srv)


def test_points_values_is_byte_identical_to_n_singles():
    batch = points_values("haworth", _COORDS)
    singles = [point_values("haworth", float(x), float(y)) for (x, y) in _COORDS]
    assert json.dumps(batch, sort_keys=True, default=str) == json.dumps(singles, sort_keys=True, default=str)


def test_points_values_empty_batch_is_empty():
    assert points_values("haworth", []) == []


def test_world_points_route_matches_world_point(client):
    coords = [[60.0, 60.0], [2500.0, 3000.0], [500.0, 1200.0]]
    r = client.post("/world/points", json={"site": "haworth", "points": coords})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["site"] == "haworth" and len(body["points"]) == 3
    for (x, y), got in zip(coords, body["points"]):
        one = client.get(f"/world/point?site=haworth&x={x}&y={y}").json()
        assert got == one, f"batch cell ({x},{y}) diverged from /world/point"


def test_world_points_413_over_cap(client):
    r = client.post("/world/points", json={"site": "haworth", "points": [[0.0, 0.0]] * 513})
    assert r.status_code == 413


def test_world_points_rejects_extra_fields(client):
    r = client.post("/world/points", json={"site": "haworth", "points": [[0.0, 0.0]], "junk": 1})
    assert r.status_code == 400 and "junk" in r.text   # extra="forbid" -> app validation handler returns 400


def test_world_points_404_unknown_site(client):
    r = client.post("/world/points", json={"site": "definitely_not_a_site_zzz", "points": [[0.0, 0.0]]})
    assert r.status_code == 404


def test_world_points_valueerror_maps_to_422_not_503(client, monkeypatch):
    # F23: a ValueError from the producer is honest BAD INPUT (4xx), like the sibling reads /world/point
    # (line 338) and /world/transect (line 444) -- NOT a 503 (which means a missing [planner] extra /
    # ImportError). Split the except so ValueError -> 422 (parity), ImportError -> 503.
    import stewie.server.gis_layers as GL

    def _boom(site, coords):
        raise ValueError("order coord outside the mapped tile")

    monkeypatch.setattr(GL, "points_values", _boom)
    r = client.post("/world/points", json={"site": "haworth", "points": [[60.0, 60.0]]})
    assert r.status_code == 422, f"ValueError must map to 422 (parity with /world/transect), got {r.status_code}: {r.text}"
