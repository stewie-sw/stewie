"""ROS egress lowering (advisory, read-only): the numpy map/costmap/plan products -> the frozen
`/stewie/*` contract message shapes (nav_msgs/OccupancyGrid, nav_msgs/Path, grid_map_msgs/GridMap) +
the selenographic MapMeta georef anchor. Pure translation (rclpy-optional), tested on a REAL Haworth
DEM subsample -- no fabricated grids.
"""
import json
import math
import os

import numpy as np
import pytest

from dart import hazard_map as HM
from stewie.bridge import ros_export as RX

_REPO_SAMPLES = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "samples"))
_BUNDLE = os.path.join(_REPO_SAMPLES, "lunar_dem", "haworth_10km_5m")
_HAVE = os.path.exists(os.path.join(_BUNDLE, "heightmap.rf32"))


def _crop(n=60):
    """A REAL work-area window off the flattest Haworth anchor (no synthetic terrain)."""
    from lode import mission_planner as MP
    Z, cell = MP.load_haworth_dem()
    ox, oy = MP.flattest_anchor((Z, cell))
    r0, c0 = int(round(oy / cell)), int(round(ox / cell))
    win = np.asarray(Z[r0:r0 + n, c0:c0 + n], dtype=float).copy()
    return win, float(cell), (float(c0 * cell), float(r0 * cell))


# ---- OccupancyGrid --------------------------------------------------------------------------------
def test_occupancy_grid_msg_is_valid_nav_msgs_shape():
    if not _HAVE:
        pytest.skip("real Haworth DEM bundle absent")
    Z, cell, _origin = _crop()
    hm = HM.build_hazard_map((Z, cell), (0.0, 0.0))
    unknown = ~np.isfinite(hm.roughness_m)
    occ = RX.occupancy_values(hm.hazard_class, unknown_mask=unknown)
    msg = RX.occupancy_grid_msg(occ, resolution_m=cell)
    assert msg["header"]["frame_id"] == "map"
    info = msg["info"]
    assert info["resolution"] == pytest.approx(cell)
    assert info["width"] == occ.shape[1] and info["height"] == occ.shape[0]
    assert len(msg["data"]) == occ.shape[0] * occ.shape[1]
    # int8 range: 0 free / 100 lethal / -1 unknown, JSON-safe ints
    assert all(isinstance(v, int) and -1 <= v <= 100 for v in msg["data"])
    # carries the REAL hazard values (un-flips exactly to `occ`) and reflects terrain variation (the
    # flattest anchor's 300 m window still has 0.4-26 deg slope -> a mix of hazard bands, not a stub)
    recon = np.flipud(np.asarray(msg["data"], dtype=np.int8).reshape(info["height"], info["width"]))
    assert np.array_equal(recon, occ)
    assert len(np.unique(occ)) >= 2


def test_occupancy_values_map_hazard_classes_and_nodata():
    if not _HAVE:
        pytest.skip("real Haworth DEM bundle absent")
    Z, cell, _o = _crop()
    Znd = Z.copy()
    Znd[5:8, 5:8] = np.nan                                   # a real sensor-gap / nodata patch
    hm = HM.build_hazard_map((Znd, cell), (0.0, 0.0))
    unknown = ~np.isfinite(hm.roughness_m)
    occ = RX.occupancy_values(hm.hazard_class, unknown_mask=unknown)
    assert (occ == RX.OCC_UNKNOWN).any()                    # nodata -> -1 unknown
    # every unknown cell is exactly the nodata mask (nodata never masquerades as lethal 100)
    assert np.array_equal(occ == RX.OCC_UNKNOWN, unknown)
    # SAFE cells -> free (0); real terrain no-go (finite, class NOGO) -> lethal 100
    real_nogo = (hm.hazard_class == HM.NOGO) & ~unknown
    if real_nogo.any():
        assert np.all(occ[real_nogo] == RX.OCC_LETHAL)
    assert np.all(occ[hm.hazard_class == HM.SAFE] == RX.OCC_FREE)


def test_occupancy_keepout_is_lethal_and_placement_is_rep103():
    """A cell at numpy (r,c) must land at REP-103 map (c*res, -r*res) in the OccupancyGrid (frames.py
    y=-row), so a rover pose indexes the right cell; and a keep-out mask reads back as lethal there."""
    if not _HAVE:
        pytest.skip("real Haworth DEM bundle absent")
    Z, cell, _o = _crop()
    hm = HM.build_hazard_map((Z, cell), (0.0, 0.0))
    unknown = ~np.isfinite(hm.roughness_m)
    keepout = np.zeros(Z.shape, bool)
    keepout[10, 12] = True
    occ = RX.occupancy_values(hm.hazard_class, unknown_mask=unknown, keepout_mask=keepout)
    assert occ[10, 12] == RX.OCC_LETHAL
    msg = RX.occupancy_grid_msg(occ, resolution_m=cell)
    # query at the REP-103 map position of numpy cell (10, 12)
    assert RX.occupancy_at(msg, 12 * cell, -10 * cell) == RX.OCC_LETHAL
    # placement round-trips for other, differently-valued cells too (numpy (r,c) -> map (c*res, -r*res))
    assert RX.occupancy_at(msg, 0.0, 0.0) == int(occ[0, 0])
    assert RX.occupancy_at(msg, 5 * cell, -3 * cell) == int(occ[3, 5])


# ---- Costmap (OccupancyGrid + blocking_reason GridMap) --------------------------------------------
def test_costmap_msgs_collapse_to_0_100_and_preserve_reason():
    if not _HAVE:
        pytest.skip("real Haworth DEM bundle absent")
    from lode import costmap_layers as CL
    Z, cell, _o = _crop(n=24)
    keep = np.zeros(Z.shape, bool)
    keep[6, 8] = True                                        # a real operator keep-out -> a blocking reason
    ctx = CL.CostmapContext(Z=Z, cell_m=cell, keepout_mask=keep)
    cm = CL.compose(ctx)
    out = RX.costmap_msgs(cm.cost, cm.passable, cm.reason, resolution_m=cell, layer_names=CL.LAYER_NAMES)
    occ = out["occupancy"]
    assert occ["header"]["frame_id"] == "map"
    assert all(0 <= v <= 100 for v in occ["data"])          # 0-100 cost, no -1 (design: costmap has no unknown)
    gm = out["blocking_reason"]
    assert gm["layers"] == ["blocking_reason"]
    assert gm["info"]["resolution"] == pytest.approx(cell)
    # the reason grid is NOT lost (AS-11): EVERY cell's GridMap code maps back to its blocking-layer name
    # (the FIRST-blocking layer per cell; on real terrain a drop-off/slope may block before the keep-out)
    codes = RX.gridmap_layer_array(gm, "blocking_reason")
    assert codes.shape == cm.reason.shape
    legend = out["reason_legend"]
    for (rr, cc), name in np.ndenumerate(cm.reason):
        assert legend[int(round(float(codes[rr, cc])))] == str(name)
    # a passable cell has reason code 0 (empty); the operator keep-out is a known blocking layer
    if cm.passable.any():
        pr, pc = (int(v) for v in np.argwhere(cm.passable)[0])
        assert int(round(float(codes[pr, pc]))) == 0
    assert "keepout" in set(legend.values()) and not cm.passable[6, 8]


# ---- Path (nav_msgs/Path from the routed traverse) -----------------------------------------------
def test_path_from_plan_ir_is_nav_msgs_path_in_map_frame():
    # a plan-IR GoTo leg -> a concatenated nav_msgs/Path, order frame -> REP-103 map frame (y-sign flip),
    # WITHOUT the command-goal egress (no lower_plan_ir): the traverse polyline only.
    ir = {"plan_id": "p", "schema_version": "1", "feasible": True, "actions": [
        {"id": 0, "op": "GoTo", "vehicle": 0, "to": [30.0, 10.0],
         "waypoints": [[0.0, 0.0], [15.0, 5.0], [30.0, 10.0]], "reached": True},
        {"id": 1, "op": "Excavate", "site": [30.0, 10.0]}]}   # a work op contributes NO path poses
    path = RX.path_from_plan_ir(ir)
    assert path["header"]["frame_id"] == "map"
    assert len(path["poses"]) == 3                            # only the GoTo waypoints
    for ps in path["poses"]:
        assert ps["header"]["frame_id"] == "map"
        pos = ps["pose"]["position"]
        assert math.isfinite(pos["x"]) and math.isfinite(pos["y"]) and pos["z"] == 0.0
    # the SAME REP-103 y-sign flip the command lowering applies (frames.local_xy_to_rep103): (15,5)->(15,-5)
    assert path["poses"][1]["pose"]["position"]["x"] == pytest.approx(15.0)
    assert path["poses"][1]["pose"]["position"]["y"] == pytest.approx(-5.0)


def test_path_msg_from_xy_pairs():
    path = RX.path_msg([(0.0, 0.0), (2.0, 3.0)])
    assert path["header"]["frame_id"] == "map" and len(path["poses"]) == 2
    assert path["poses"][1]["pose"]["position"]["x"] == pytest.approx(2.0)


# ---- MapMeta georef anchor -----------------------------------------------------------------------
def test_map_meta_affine_round_trips_lunar_coords():
    if not _HAVE:
        pytest.skip("real Haworth DEM bundle absent")
    pyproj = pytest.importorskip("pyproj")
    from stewie.terrain import site_dem as SD
    meta = json.load(open(os.path.join(_BUNDLE, "metadata.json")))
    b, g = meta["world_bounds_m"], meta["grid"]
    cell = float(g["cell_m"])
    _Z, _c, (ox, oy) = _crop()
    lat, lon = SD.dem_origin_to_latlon(ox, oy, bundle_dir=_BUNDLE)
    mm = RX.map_meta_msg(dem_name="haworth", dem_sha256="deadbeef", cell_m=cell,
                         order_origin_xy=(ox, oy), tile_x0=b["x0"], tile_y1=b["y1"],
                         origin_lonlat=(lon, lat))
    assert mm["header"]["frame_id"] == "map"
    assert mm["iau_code"] == "IAU_2015:30135" and mm["iau_geographic"] == "IAU_2015:30100"
    a = mm["iau_affine"]                                     # rasterio Affine (a,b,c,d,e,f)
    assert a[0] == pytest.approx(cell) and a[4] == pytest.approx(-cell)
    assert a[2] == pytest.approx(b["x0"] + ox) and a[5] == pytest.approx(b["y1"] - oy)
    # inverse-project the affine's pixel(0,0) CENTER -> the same lunar lon/lat as dem_origin_to_latlon
    crs = pyproj.CRS.from_user_input("IAU_2015:30135")
    inv = pyproj.Transformer.from_crs(crs, crs.geodetic_crs, always_xy=True)
    cx, cy = a[2] + cell / 2.0, a[5] - cell / 2.0
    glon, glat = inv.transform(cx, cy)
    assert glon == pytest.approx(mm["origin_lon_deg"], abs=1e-6)
    assert glat == pytest.approx(mm["origin_lat_deg"], abs=1e-6)


def test_map_meta_degrades_without_pyproj_projection():
    """The affine (metadata-only) is always produced; lon/lat degrade to NaN when unavailable -- honest,
    never fabricated."""
    mm = RX.map_meta_msg(dem_name="haworth", dem_sha256="x", cell_m=5.0,
                         order_origin_xy=(100.0, 200.0), tile_x0=-52900.0, tile_y1=105400.0,
                         origin_lonlat=None)
    assert mm["iau_affine"][2] == pytest.approx(-52900.0 + 100.0)
    assert math.isnan(mm["origin_lon_deg"]) and math.isnan(mm["origin_lat_deg"])


# ---- rosbridge record wrapper (the shape the RT-04 collector/feeder speaks) -----------------------
def test_rosbridge_record_is_json_serializable_contract_shape():
    msg = RX.path_msg([(0.0, 0.0), (1.0, 1.0)])
    rec = RX.rosbridge_record("/stewie/plan/path", "nav_msgs/Path", msg, qos="state")
    assert rec["topic"] == "/stewie/plan/path" and rec["type"] == "nav_msgs/Path"
    assert rec["qos"] == "state" and rec["msg"] is msg
    json.dumps(rec)                                          # must be wire-serializable
