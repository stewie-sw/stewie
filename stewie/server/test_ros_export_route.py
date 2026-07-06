"""ROS egress export routes (advisory, read-only): POST /ros/export/{occupancy,costmap,path} lower the
numpy backend's ALREADY-computed hazard / 12-layer costmap / routed-traverse products onto the frozen
`/stewie/*` contract message shapes, each with a latched MapMeta selenographic georef anchor. In-process
TestClient over the REAL Haworth DEM -- no synthetic grids. These NEVER command (require_auth, not a
command gate); they mint contract-shaped messages a Nav2/RViz consumer reads.
"""
import os

import pytest
from fastapi.testclient import TestClient

from stewie.bridge import autonomy_contract as AC
from stewie.server.server import app

_REPO_SAMPLES = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "samples"))
_HAVE = os.path.exists(os.path.join(_REPO_SAMPLES, "lunar_dem", "haworth_10km_5m", "heightmap.rf32"))

_MISSION = {
    "name": "ros-path", "body": "moon", "charger": [0, 0],
    "orders": [
        {"action": "borrow", "kind": "cut", "x": 20.0, "y": 10.0, "footprint_m2": 16.0, "depth_m": 0.3},
        {"action": "pad", "kind": "fill", "x": 45.0, "y": 10.0, "footprint_m2": 16.0, "depth_m": 0.3},
    ],
}


def _client():
    return TestClient(app)


def _tile_lonlat_bounds():
    from lode import mission_planner as MP
    georef = MP.dem_georef_corners()
    lons = [c["lon"] for c in georef["corners"]]
    lats = [c["lat"] for c in georef["corners"]]
    return min(lons), max(lons), min(lats), max(lats)


def test_export_occupancy_returns_valid_occupancygrid_with_georef():
    if not _HAVE:
        pytest.skip("real Haworth DEM bundle absent")
    c = _client()
    r = c.post("/ros/export/occupancy", json={"site": "haworth", "window_m": 200.0})
    assert r.status_code == 200, r.text
    body = r.json()
    # the contract topic + type, latched (QOS_STATE) -- read from the FROZEN contract, not hard-coded
    assert body["topic"] == "/stewie/map/occupancy"
    assert body["type"] == AC.TOPICS["/stewie/map/occupancy"].msg == "nav_msgs/OccupancyGrid"
    assert body["qos"] == AC.TOPICS["/stewie/map/occupancy"].qos
    msg = body["msg"]
    assert msg["header"]["frame_id"] == "map"
    info = msg["info"]
    assert info["width"] > 0 and info["height"] > 0
    assert len(msg["data"]) == info["width"] * info["height"] > 0        # a real, non-empty grid
    assert all(-1 <= v <= 100 for v in msg["data"])
    assert len(set(msg["data"])) >= 2                                    # real varied terrain, not a constant stub
    # the latched MapMeta georef anchor places the map on the Moon
    mm = body["map_meta"]
    assert mm["msg"]["iau_code"] == "IAU_2015:30135"
    lon, lat = mm["msg"]["origin_lon_deg"], mm["msg"]["origin_lat_deg"]
    lo, hi, la, ha = _tile_lonlat_bounds()
    assert lo - 0.5 <= lon <= hi + 0.5 and la - 0.1 <= lat <= ha + 0.1   # inside the committed tile


def test_export_costmap_returns_occupancy_and_blocking_reason():
    if not _HAVE:
        pytest.skip("real Haworth DEM bundle absent")
    c = _client()
    r = c.post("/ros/export/costmap", json={"site": "haworth", "window_m": 60.0,
                                            "keepouts": [[20.0, 20.0, 6.0]]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["topic"] == "/stewie/costmap"
    assert body["type"] == AC.TOPICS["/stewie/costmap"].msg == "nav_msgs/OccupancyGrid"
    occ = body["msg"]
    assert all(0 <= v <= 100 for v in occ["data"])                      # 0-100 collapsed cost
    # the blocking_reason GridMap layer rides on /stewie/map/dem (the reason grid is preserved, AS-11)
    br = body["blocking_reason"]
    assert br["type"] == "grid_map_msgs/GridMap"
    assert br["msg"]["layers"] == ["blocking_reason"]
    assert body["reason_legend"]                                         # code -> layer-name legend present
    # the operator keep-out produced at least one lethal cell whose reason is a real layer
    assert any(v == 100 for v in occ["data"])
    names = set(body["reason_legend"].values())
    assert "keepout" in names


def test_export_path_lowers_routed_traverse_to_nav_msgs_path():
    if not _HAVE:
        pytest.skip("real Haworth DEM bundle absent")
    c = _client()
    r = c.post("/ros/export/path", json={"mission": _MISSION, "site": "haworth"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["topic"] == "/stewie/plan/path"
    assert body["type"] == AC.TOPICS["/stewie/plan/path"].msg == "nav_msgs/Path"
    path = body["msg"]
    assert path["header"]["frame_id"] == "map"
    assert len(path["poses"]) >= 2                                       # the real routed polyline
    for ps in path["poses"]:
        assert ps["header"]["frame_id"] == "map"
        assert isinstance(ps["pose"]["position"]["x"], (int, float))
    assert body["map_meta"]["msg"]["iau_code"] == "IAU_2015:30135"


def test_export_path_rejects_non_lunar_body():
    c = _client()
    bad = dict(_MISSION, body="mars")
    r = c.post("/ros/export/path", json={"mission": bad, "site": "haworth"})
    assert r.status_code == 400 and r.json()["ok"] is False              # no lunar DEM -> cannot georeference


def test_export_occupancy_unknown_site_is_honest_error():
    c = _client()
    r = c.post("/ros/export/occupancy", json={"site": "no-such-site"})
    assert r.status_code in (400, 404)
    assert r.json()["ok"] is False                                       # honest, never a stub grid


def test_exports_are_advisory_read_only():
    """The export routes are require_auth (evidence tier), NOT a command gate: they mint messages, never
    emit motion. Assert the served topic is a STEWIE->ROS state/plan topic, never a COMMAND topic."""
    if not _HAVE:
        pytest.skip("real Haworth DEM bundle absent")
    c = _client()
    for ep, topic in (("/ros/export/occupancy", "/stewie/map/occupancy"),
                      ("/ros/export/costmap", "/stewie/costmap")):
        body = c.post(ep, json={"site": "haworth", "window_m": 40.0}).json()
        assert body["topic"] == topic
        assert topic not in AC.COMMAND_TOPICS                            # never a command/actuation topic
