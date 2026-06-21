"""GI-03 router: GET /export/geojson serializes a posted plan to RFC-7946 GeoJSON in lon/lat.

In-process TestClient (loopback dev-open) over the real Haworth DEM -- no synthetic terrain. Verifies the
endpoint returns a valid FeatureCollection whose coordinates are lon/lat inside the committed tile and
whose features match the mission's orders + keep-outs, and that COG availability is reported honestly."""
import json

from fastapi.testclient import TestClient

from stewie.server.server import app

_MISSION = {
    "name": "gis-route", "body": "moon", "charger": [0, 0],
    "orders": [
        {"action": "cut", "kind": "cut", "x": 20, "y": 15, "footprint_m2": 36, "depth_m": 0.1,
         "shape": {"kind": "rectangle", "w": 6, "h": 6}},
        {"action": "fill", "kind": "fill", "x": 50, "y": 15, "footprint_m2": 36, "depth_m": 0.1},
    ],
    "keepouts": [{"x": 35, "y": 40, "r": 8}],
}


def _client():
    return TestClient(app)


def test_export_geojson_returns_valid_featurecollection():
    c = _client()
    r = c.get("/export/geojson", params={"mission": json.dumps(_MISSION)})
    assert r.status_code == 200, r.text
    fc = r.json()
    assert fc["type"] == "FeatureCollection"
    assert fc["features"]
    feats = [f["properties"].get("feature") for f in fc["features"]]
    assert feats.count("order") == 2
    assert feats.count("keepout") == 1
    assert "route" in feats
    assert "footprint" in feats                                # the rectangle order carries a footprint polygon
    for f in fc["features"]:
        for lon, lat in _all_coords(f["geometry"]):
            assert -180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0   # RFC-7946 lon,lat order


def _all_coords(geom):
    t = geom["type"]
    if t == "Point":
        return [geom["coordinates"]]
    if t == "LineString":
        return geom["coordinates"]
    return [pt for ring in geom["coordinates"] for pt in ring]


def test_export_geojson_coords_inside_haworth_tile():
    from lode import mission_planner as MP
    c = _client()
    fc = c.get("/export/geojson", params={"mission": json.dumps(_MISSION)}).json()
    georef = MP.dem_georef_corners()
    lons = [cc["lon"] for cc in georef["corners"]]
    lats = [cc["lat"] for cc in georef["corners"]]
    for f in fc["features"]:
        for lon, lat in _all_coords(f["geometry"]):
            assert min(lons) - 0.5 <= lon <= max(lons) + 0.5
            assert min(lats) - 0.1 <= lat <= max(lats) + 0.1


def test_export_geojson_bad_mission_is_400():
    c = _client()
    r = c.get("/export/geojson", params={"mission": "{not json"})
    assert r.status_code == 400
    assert r.json()["ok"] is False
    r2 = c.get("/export/geojson", params={"mission": json.dumps({"body": "moon", "orders": []})})
    assert r2.status_code == 400                               # empty orders -> ValueError -> 400


def test_export_cog_availability_endpoint_is_honest():
    c = _client()
    r = c.get("/export/cog/available")
    assert r.status_code == 200
    body = r.json()
    assert "available" in body and isinstance(body["available"], bool)
    if not body["available"]:
        assert body["reason"]                                  # honest blocked reason, never a stub
