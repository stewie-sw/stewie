"""GI-03: GeoJSON export of a plan (orders, keep-outs, route, footprints) to RFC-7946 in lon/lat.

Real Haworth LOLA DEM only -- the order-frame (x, y) -> selenographic lon/lat transform is the same
IAU_2015:30135 south-polar stereographic projection the cockpit georef uses (no synthetic terrain, no
fabricated coordinates). Geometry is validated to be inside the committed tile's globe footprint."""
import json

from lode import gis_export as GE
from lode import mission_planner as MP


def _dem_origin():
    dem = MP.load_haworth_dem()
    return dem, MP.flattest_anchor(dem)


def _mission():
    pay = {"name": "gis", "body": "moon", "charger": [0, 0],
           "orders": [{"action": "cut", "kind": "cut", "x": 20, "y": 15, "footprint_m2": 36, "depth_m": 0.1,
                       "shape": {"kind": "rectangle", "w": 6, "h": 6}},
                      {"action": "fill", "kind": "fill", "x": 50, "y": 15, "footprint_m2": 36, "depth_m": 0.1}],
           "keepouts": [{"x": 35, "y": 40, "r": 8}]}
    return MP.mission_from_dict(pay)


def test_export_is_valid_rfc7946_featurecollection_that_parses_back():
    dem, o = _dem_origin()
    fc = GE.plan_to_geojson(_mission(), dem=dem, dem_origin=o)
    # round-trips through json (no numpy floats / sets leak into the document)
    fc = json.loads(json.dumps(fc))
    assert fc["type"] == "FeatureCollection"
    assert isinstance(fc["features"], list) and fc["features"]
    for f in fc["features"]:
        assert f["type"] == "Feature"
        assert f["geometry"]["type"] in ("Point", "LineString", "Polygon")
        assert isinstance(f["properties"], dict)


def test_coords_are_lonlat_inside_the_haworth_tile():
    dem, o = _dem_origin()
    fc = GE.plan_to_geojson(_mission(), dem=dem, dem_origin=o)
    georef = MP.dem_georef_corners()                       # the committed tile's selenographic footprint
    lons = [c["lon"] for c in georef["corners"]]
    lats = [c["lat"] for c in georef["corners"]]
    lo_min, lo_max = min(lons), max(lons)
    la_min, la_max = min(lats), max(lats)

    def _coords(geom):
        t = geom["type"]
        if t == "Point":
            return [geom["coordinates"]]
        if t == "LineString":
            return geom["coordinates"]
        return [pt for ring in geom["coordinates"] for pt in ring]

    seen = 0
    for f in fc["features"]:
        for lon, lat in _coords(f["geometry"]):
            assert -180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0   # RFC-7946 lon,lat ordering
            assert lo_min - 0.5 <= lon <= lo_max + 0.5               # inside the tile footprint (+slack)
            assert la_min - 0.1 <= lat <= la_max + 0.1
            seen += 1
    assert seen > 0


def test_features_match_the_plan_orders_keepouts_and_route():
    dem, o = _dem_origin()
    m = _mission()
    fc = GE.plan_to_geojson(m, dem=dem, dem_origin=o)
    kinds = [f["properties"].get("feature") for f in fc["features"]]
    # one order Point per build order (cut + fill = 2), one keep-out Polygon, at least one route LineString
    assert kinds.count("order") == len(m.orders)
    assert kinds.count("keepout") == len(m.keepouts)
    assert "route" in kinds
    # a typed-shape order carries its footprint Polygon; the rectangle order does
    assert "footprint" in kinds
    # the order Points carry their action + kind so a GIS client can label them
    order_feats = [f for f in fc["features"] if f["properties"].get("feature") == "order"]
    actions = {f["properties"]["action"] for f in order_feats}
    assert actions == {o.action for o in m.orders}


def test_polygons_are_closed_rings_lonlat():
    # RFC-7946 7.1.6: a Polygon's linear ring is closed (first == last) and lon,lat ordered.
    dem, o = _dem_origin()
    fc = GE.plan_to_geojson(_mission(), dem=dem, dem_origin=o)
    polys = [f for f in fc["features"] if f["geometry"]["type"] == "Polygon"]
    assert polys
    for f in polys:
        for ring in f["geometry"]["coordinates"]:
            assert len(ring) >= 4
            assert ring[0] == ring[-1]


def test_cog_availability_is_reported_honestly():
    # COG export ships only when a real raster backend (rasterio/GDAL) is importable; otherwise it is
    # honestly marked unavailable -- never a stub raster.
    ok, reason = GE.cog_available()
    assert isinstance(ok, bool)
    if not ok:
        assert isinstance(reason, str) and reason
