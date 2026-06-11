"""The Haworth tile's globe footprint: world_bounds_m (IAU_2015:30135) -> selenographic corners."""
import pytest


def test_dem_georef_corners_are_at_the_lunar_south_pole():
    pytest.importorskip("pyproj")
    from lode.mission_planner import dem_georef_corners
    c = dem_georef_corners()
    lats = [p["lat"] for p in c["corners"]]
    assert all(-90.0 <= la <= -85.0 for la in lats)        # a south-polar tile
    assert max(lats) - min(lats) > 0.1                     # a real footprint, not a point
    assert c["center"]["lat"] == pytest.approx(sum(lats) / 4, abs=0.2)
    assert {"lat", "lon"} <= set(c["center"])


def test_dem_georef_roundtrips_with_the_forward_transform():
    # [REQ:TW-02] reprojection into the documented local metric frame (IAU_2015:30135 round-trip)
    pytest.importorskip("pyproj")
    from lode.mission_planner import dem_georef_corners, latlon_to_dem_origin
    c = dem_georef_corners()
    x, y = latlon_to_dem_origin(c["center"]["lat"], c["center"]["lon"])
    assert 0.0 <= x <= 10000.0 and 0.0 <= y <= 10000.0     # the center lands inside the 10 km tile


def test_site_xy_endpoint_roundtrips():
    pytest.importorskip("pyproj")
    import importlib

    from fastapi.testclient import TestClient
    import stewie.server.server as srv
    importlib.reload(srv)
    c = TestClient(srv.app)
    from lode.mission_planner import dem_georef_corners
    ctr = dem_georef_corners()["center"]
    r = c.get(f"/dem/site_xy?lat={ctr['lat']}&lon={ctr['lon']}")
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] and 0 <= d["x_m"] <= 10000 and 0 <= d["y_m"] <= 10000
    out = c.get("/dem/site_xy?lat=0&lon=0")                # equator: outside the tile -> honest 422
    assert out.status_code == 422
