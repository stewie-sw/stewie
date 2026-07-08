"""[REQ:SD-03] The #45 resource cross-section: transect_profile + POST /world/transect return REAL per-cell
elevation/slope/bearing/sinkage/PSR along a transect (each traced to its producer), with ice-stability an
explicit data gap (never fabricated). Real Haworth DEM, no synthetic."""
import importlib

import pytest
from fastapi.testclient import TestClient

from stewie.server.gis_layers import transect_profile

_PTS = [(float(x), 100.0) for x in range(100, 600, 50)]   # 10 samples, 50 m apart along y=100


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


def test_transect_profile_real_layers_and_cumulative_distance():
    prof = transect_profile("haworth", _PTS)
    assert prof["n"] == 10
    s = prof["samples"]
    assert s[0]["dist_m"] == 0.0
    assert all(s[i]["dist_m"] <= s[i + 1]["dist_m"] for i in range(len(s) - 1))
    assert abs(s[-1]["dist_m"] - 450.0) < 1e-6            # 9 gaps of 50 m
    for smp in s:
        assert smp["in_bounds"] is True
        assert isinstance(smp["elevation_m"], (int, float))   # real DEM elevation
        assert isinstance(smp["slope_deg"], (int, float))     # real derived slope
        assert isinstance(smp["bearing_pa"], (int, float))    # real terramechanics
        assert isinstance(smp["psr"], bool)                   # real horizon-swept cold-trap bool


def test_transect_reports_the_ice_stability_gap_not_fabricated():
    prof = transect_profile("haworth", _PTS)
    assert "psr" in prof["sources"]                          # PSR is a real, cited source
    assert "ice_stability" in prof["unavailable"]            # ice-stability is an explicit gap
    assert "NOT fabricated" in prof["unavailable"]["ice_stability"]
    for smp in prof["samples"]:                              # no sample carries a fabricated ice value
        assert "ice_stability" not in smp and "ice" not in smp


def test_transect_matches_world_point_per_cell(client):
    prof = client.post("/world/transect", json={"site": "haworth", "points": [[200.0, 100.0], [250.0, 100.0]]}).json()
    assert prof["ok"] is True and prof["n"] == 2
    pt = client.get("/world/point?site=haworth&x=200&y=100").json()
    dem_val = [a["value"] for a in pt["attributes"] if a["id"] == "base.dem"][0]
    assert prof["samples"][0]["elevation_m"] == dem_val     # transect reuses point_values -> identical per cell


def test_transect_route_400_under_2_points(client):
    r = client.post("/world/transect", json={"site": "haworth", "points": [[100.0, 100.0]]})
    assert r.status_code == 400


def test_transect_route_413_over_cap(client):
    r = client.post("/world/transect", json={"site": "haworth", "points": [[0.0, 0.0]] * 513})
    assert r.status_code == 413


def test_transect_route_404_unknown_site(client):
    r = client.post("/world/transect", json={"site": "definitely_not_a_site_zzz", "points": [[0.0, 0.0], [1.0, 1.0]]})
    assert r.status_code == 404


def test_transect_lonlat_frame_round_trips_an_in_tile_point(client):
    # take an in-bounds ORDER point, convert to selenographic lon/lat (the /ide's frame), POST frame='lonlat',
    # and assert it round-trips back to real data near the order-frame /world/point (guards the lon/lat order).
    from lode import mission_planner as MP
    bundle = MP.bundle_for_site("haworth")
    lat, lon = MP.dem_origin_to_latlon(200.0, 100.0, bundle_dir=bundle)
    r = client.post("/world/transect", json={"site": "haworth", "points": [[lon, lat], [lon, lat]], "frame": "lonlat"})
    assert r.status_code == 200, r.text
    prof = r.json()
    assert prof["ok"] is True and prof["n"] == 2
    s0 = prof["samples"][0]
    assert s0["in_bounds"] is True and isinstance(s0["elevation_m"], (int, float))   # real data via the lon/lat path
    pt = client.get("/world/point?site=haworth&x=200&y=100").json()
    dem_val = [a["value"] for a in pt["attributes"] if a["id"] == "base.dem"][0]
    assert abs(s0["elevation_m"] - dem_val) < 20.0   # same cell or an adjacent one (lon/lat round-trip rounding)


def test_transect_lonlat_out_of_tile_is_422_not_503(client):
    # a lon/lat outside the Haworth tile is an honest bad-input 422 -- the conversion runs and rejects cleanly
    r = client.post("/world/transect", json={"site": "haworth", "points": [[116.56505, -88.43925], [116.6, -88.4]], "frame": "lonlat"})
    assert r.status_code == 422


def test_transect_route_400_bad_frame(client):
    r = client.post("/world/transect", json={"site": "haworth", "points": [[0.0, 0.0], [1.0, 1.0]], "frame": "wgs84"})
    assert r.status_code == 400
