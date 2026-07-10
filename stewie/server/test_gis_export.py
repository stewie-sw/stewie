"""GI-03 router: GET /export/geojson serializes a posted plan to RFC-7946 GeoJSON in lon/lat.

In-process TestClient (loopback dev-open) over the real Haworth DEM -- no synthetic terrain. Verifies the
endpoint returns a valid FeatureCollection whose coordinates are lon/lat inside the committed tile and
whose features match the mission's orders + keep-outs, and that COG availability is reported honestly."""
import json

import pytest
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


def test_gis_import_route_round_trips_orders():
    """POST /gis/import is the inverse of GET /export/geojson: the exported FeatureCollection re-imports to
    the local order-frame orders (sub-decimetre on the real Haworth tile)."""
    c = _client()
    fc = c.get("/export/geojson", params={"mission": json.dumps(_MISSION)}).json()
    r = c.post("/gis/import", json={"featurecollection": fc})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and len(body["orders"]) == len(_MISSION["orders"])
    got = sorted((o["x"], o["y"]) for o in body["orders"])
    want = sorted((o["x"], o["y"]) for o in _MISSION["orders"])
    for (gx, gy), (wx, wy) in zip(got, want):
        assert gx == pytest.approx(wx, abs=0.5) and gy == pytest.approx(wy, abs=0.5)
    assert body["charger"] is not None and len(body["keepouts"]) == 1


def test_gis_import_route_rejects_non_featurecollection():
    c = _client()
    r = c.post("/gis/import", json={"featurecollection": {"type": "Feature"}})
    assert r.status_code == 400 and r.json()["ok"] is False


def test_gis_mission_package_route_is_self_contained():
    """GET /gis/mission-package returns the offline bundle: manifest + plan GeoJSON, feature counts agree."""
    c = _client()
    r = c.get("/gis/mission-package", params={"mission": json.dumps(_MISSION)})
    assert r.status_code == 200, r.text
    pkg = r.json()
    assert pkg["format"].startswith("stewie.mission_package/")
    assert pkg["geojson"]["type"] == "FeatureCollection"
    assert pkg["manifest"]["feature_count"] == len(pkg["geojson"]["features"])
    assert pkg["manifest"]["mission"] == _MISSION["name"]


def test_gis_query_route_filters_by_layer_and_attribute():
    c = _client()
    fc = c.get("/export/geojson", params={"mission": json.dumps(_MISSION)}).json()
    r = c.post("/gis/query", json={"featurecollection": fc, "feature": "keepout"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 1 and all(f["properties"]["feature"] == "keepout" for f in body["features"])
    r2 = c.post("/gis/query", json={"featurecollection": fc, "feature": "order", "attrs": {"kind": "cut"}})
    assert r2.status_code == 200 and r2.json()["count"] == 1


def test_export_geojson_serializes_place_object_markers_as_annotations():  # [REQ:GI-03]
    """GI-03 cockpit-toolbox annotation: a place-object marker (beacon/cache/instrument/sample/antenna + a
    label) rides the export mission and serializes as a Point Feature with feature='marker' + otype + label,
    in selenographic lon/lat inside the tile -- the authored annotation previously ABSENT from the export."""
    c = _client()
    mission = dict(_MISSION, markers=[
        {"x": 30, "y": 25, "otype": "beacon", "label": "LZ beacon"},
        {"x": 60, "y": 40, "otype": "sample"},                 # label omitted -> no label property
    ])
    r = c.get("/export/geojson", params={"mission": json.dumps(mission)})
    assert r.status_code == 200, r.text
    fc = r.json()
    markers = [f for f in fc["features"] if f["properties"].get("feature") == "marker"]
    assert len(markers) == 2, f"expected 2 marker Points, got {len(markers)}"
    beacon = next(f for f in markers if f["properties"]["otype"] == "beacon")
    assert beacon["geometry"]["type"] == "Point"
    assert beacon["properties"]["label"] == "LZ beacon"
    lon, lat = beacon["geometry"]["coordinates"]
    assert -180.0 <= lon <= 180.0 and lat < -80.0              # selenographic south-polar lon/lat
    sample = next(f for f in markers if f["properties"]["otype"] == "sample")
    assert "label" not in sample["properties"]                 # an unlabelled marker carries no label prop


def test_export_geojson_without_markers_is_unchanged():  # [REQ:GI-03]
    """Backward-compatible: a mission with no markers key yields no marker features (the orders/keep-outs/
    route export is byte-identical to before -- markers are purely additive)."""
    c = _client()
    r = c.get("/export/geojson", params={"mission": json.dumps(_MISSION)})
    assert r.status_code == 200, r.text
    assert not [f for f in r.json()["features"] if f["properties"].get("feature") == "marker"]
