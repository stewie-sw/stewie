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


def test_transect_lonlat_fully_out_of_tile_is_honest_all_out_rows(client):
    # council #55 [3]: a transect entirely outside the tile no longer 422s the whole request -- it returns 200
    # with every sample in_bounds=False + null fields (the chart shows its 'drawn outside the tile' empty-state).
    r = client.post("/world/transect", json={"site": "haworth", "points": [[116.56505, -88.43925], [116.6, -88.4]], "frame": "lonlat"})
    assert r.status_code == 200, r.text
    s = r.json()["samples"]
    assert len(s) == 2 and all(x["in_bounds"] is False and x["elevation_m"] is None for x in s)


def test_transect_lonlat_partial_tile_returns_mixed_rows_not_422(client):
    # council #55 [3]: a transect that only PARTIALLY crosses the tile returns its in-tile samples + honest
    # out-of-bounds rows for the rest, not a 422 for the whole draw.
    from stewie.terrain.site_dem import dem_origin_to_latlon
    lat_in, lon_in = dem_origin_to_latlon(200 * 5.0, 200 * 5.0)   # in-tile (pixel 200,200)
    r = client.post("/world/transect", json={"site": "haworth", "frame": "lonlat",
                    "points": [[lon_in, lat_in], [116.56505, -88.43925]]})   # 2nd point far outside the tile
    assert r.status_code == 200, r.text
    s = r.json()["samples"]
    assert any(x["in_bounds"] for x in s) and any(not x["in_bounds"] for x in s)   # mixed in + out rows
    inb = next(x for x in s if x["in_bounds"])
    assert isinstance(inb["elevation_m"], (int, float))   # the in-tile sample carries real data


def test_point_non_finite_coord_is_out_of_bounds_not_500(client):
    # council #55 pass2 [2]: pydantic accepts x=inf; the raw int(round((ox+x)/cell)) would OverflowError -> HTTP
    # 500. The finiteness guard turns a non-finite order coord into an honest out-of-tile 200 (in_bounds=False,
    # no fabricated values), the same as a far-off cell.
    r = client.get("/world/point?site=haworth&x=inf&y=1")
    assert r.status_code == 200, r.text
    assert r.json()["cell"]["in_bounds"] is False
    assert all(a["available"] is False for a in r.json()["attributes"])


def test_transect_route_400_bad_frame(client):
    r = client.post("/world/transect", json={"site": "haworth", "points": [[0.0, 0.0], [1.0, 1.0]], "frame": "wgs84"})
    assert r.status_code == 400


def test_latlon_resolves_true_interior_cell_not_anchor_offset(client):
    """[council #55, HIGH] An interior lat/lon must resolve to its TRUE DEM cell, NOT a cell offset by the
    flattest-anchor origin. latlon_to_dem_origin returns ABSOLUTE pixel-metres while point_values adds the
    anchor, so feeding one into the other double-counts the anchor (interior clicks land ~anchor/cell cells
    off -- usually out of bounds). Independent ground truth: pixel (1000,1000)'s real lat/lon (via
    dem_origin_to_latlon of its absolute pixel-metres) must resolve back to cell (1000,1000) -- BOTH through
    /world/point (the GW-07 inspector) and the frame='lonlat' transect (the #45 cross-section)."""
    from stewie.terrain.site_dem import dem_origin_to_latlon
    lat, lon = dem_origin_to_latlon(1000 * 5.0, 1000 * 5.0)   # centre of pixel (1000,1000) @ 5 m/cell
    pt = client.get(f"/world/point?site=haworth&lat={lat}&lon={lon}")
    assert pt.status_code == 200, pt.text
    cell = pt.json()["cell"]
    assert cell["in_bounds"] is True, "interior lat/lon resolved out of bounds -- anchor double-counted"
    assert cell["row"] == 1000 and cell["col"] == 1000, f"resolved r{cell['row']} c{cell['col']}, want r1000 c1000"
    dem_val = [a["value"] for a in pt.json()["attributes"] if a["id"] == "base.dem"][0]
    tr = client.post("/world/transect", json={"site": "haworth", "frame": "lonlat", "points": [[lon, lat], [lon, lat]]})
    assert tr.status_code == 200, tr.text
    s0 = tr.json()["samples"][0]
    assert s0["in_bounds"] is True and s0["elevation_m"] == dem_val   # same true cell -> same DEM value
