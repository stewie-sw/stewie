"""ROS egress lowering: the numpy backend's ALREADY-computed map / costmap / routed-traverse products ->
the frozen `/stewie/*` autonomy-contract message shapes, as rosbridge-compatible JSON.

Fills the three outright-**Missing** ROS egress rows of the contract (`autonomy_contract.py:134,136,137`):
an occupancy grid (`nav_msgs/OccupancyGrid`), a cost-map (`nav_msgs/OccupancyGrid` + a `grid_map_msgs/
GridMap` `blocking_reason` layer that PRESERVES the reason grid), and a waypoint path (`nav_msgs/Path`),
plus the latched `MapMeta` selenographic georef anchor co-published with every map so a Nav2/RViz consumer
needs no lunar knowledge while a GIS consumer recovers IAU_2015 coordinates.

PURE translation -- rclpy-OPTIONAL, the same pattern as ``plan_lowering`` / ``ros2_bridge`` (numpy-only,
no ROS/pyproj/rasterio import): every function returns a plain, JSON-serializable message-shaped dict (the
shape the RT-04 ``rosbridge_collector``/feeder speaks: ``{"op":"publish","topic":...,"msg":{...}}``), fully
testable without a ROS2 runtime; the live node turns them into real ``nav_msgs`` / ``grid_map_msgs`` msgs.

ADVISORY / READ-ONLY: these lower authoritative world-state to the wire; they carry NO command authority
(the command seam stays behind SF-01 + AG-08). Frame convention matches the bridge: ``frame_id=map``, the
REP-103 surface frame -- an OccupancyGrid cell numpy ``(row, col)`` lands at map metres ``(col*res,
-row*res)`` (``frames.grid_pose_to_rep103``: the row-axis y sign flip), so a rover's odometry pose indexes
the right cell and the routed path shares ONE frame with the grid. This module lowers the traverse POLYLINE
only (``frames.local_xy_to_rep103``); it deliberately never touches the ROS COMMAND egress (the
motion/work action goals that ``plan_lowering`` emits, sole-sourced through the rc router, EG-06).
The MapMeta ``iau_affine`` is the NORTH-UP GeoTIFF transform (== ``interop.gridmap_geotiff._transform``);
the OccupancyGrid data is the REP-103 wire order (min-y-corner origin) -- the two encode one grid, and that
raster-vs-wire row-order distinction is real, not a bug.
"""
from __future__ import annotations

import numpy as np

from stewie.bridge import frames as _FR   # THE planner-order-frame -> REP-103 conversion site (pure geometry)

# nav_msgs/OccupancyGrid cell semantics (int8): 0 free / 100 lethal / -1 unknown.
OCC_FREE = 0
OCC_LETHAL = 100
OCC_UNKNOWN = -1

# hazard-class -> occupancy cost for the passable-but-costed bands (SAFE stays free, NOGO/keepout lethal).
_CAUTION_OCC = 50
_HAZARD_OCC = 99

_STAMP_ZERO: dict = {"sec": 0, "nanosec": 0}
_IDENTITY_QUAT: dict = {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}


def _stamp(stamp: dict | None) -> dict:
    return dict(stamp) if stamp is not None else dict(_STAMP_ZERO)


def _pose(x: float, y: float) -> dict:
    """A geometry_msgs/Pose-shaped dict on the flat surface (z=0, identity orientation)."""
    return {"position": {"x": float(x), "y": float(y), "z": 0.0},
            "orientation": dict(_IDENTITY_QUAT)}


# ---- occupancy values from the DART hazard map ---------------------------------------------------
def occupancy_values(hazard_class, *, unknown_mask, keepout_mask=None,
                     caution: int = 1, hazard: int = 2, nogo: int = 3) -> np.ndarray:
    """Map a DART ``hazard_map`` per-cell hazard CLASS grid (SAFE/CAUTION/HAZARD/NOGO, `dart.hazard_map`)
    to an int8 occupancy array {-1, 0..100}: SAFE->0 free, CAUTION->50, HAZARD->99, a REAL terrain no-go
    (finite class NOGO)->100 lethal, nodata (``unknown_mask``, where slope/roughness is non-finite)->-1
    unknown, and an operator ``keepout_mask``->100 (a known no-go, always lethal even over unknown ground).

    ``hazard_class`` conflates terrain-NOGO with nodata-NOGO (both set the cost to inf), so nodata is
    separated out to -1 via ``unknown_mask`` and only real hazards become lethal 100. No fabricated values.
    """
    hc = np.asarray(hazard_class)
    unknown = np.asarray(unknown_mask, dtype=bool)
    occ = np.full(hc.shape, OCC_FREE, dtype=np.int8)
    occ[hc == caution] = _CAUTION_OCC
    occ[hc == hazard] = _HAZARD_OCC
    occ[(hc == nogo) & ~unknown] = OCC_LETHAL          # a REAL terrain no-go (not a data gap)
    occ[unknown] = OCC_UNKNOWN                          # nodata -> unknown (never a false lethal)
    if keepout_mask is not None:
        occ[np.asarray(keepout_mask, dtype=bool)] = OCC_LETHAL   # operator no-go: known + lethal, wins last
    return occ                                          # SAFE cells stay the OCC_FREE default fill


# ---- nav_msgs/OccupancyGrid ----------------------------------------------------------------------
def occupancy_grid_msg(occ, *, resolution_m: float, frame_id: str = "map",
                       stamp: dict | None = None) -> dict:
    """Lower a north-up int8 occupancy array (row 0 = north, values in {-1, 0..100}) to a nav_msgs/
    OccupancyGrid-shaped dict. The wire layout is REP-103: the grid is flipped so OccupancyGrid row index
    increases along +y while the STEWIE map frame has y = -numpy_row*res (``frames.grid_pose_to_rep103``),
    and ``info.origin`` sits at the min-y corner -- so numpy cell (r, c) reads back at map (c*res, -r*res).
    """
    a = np.asarray(occ)
    if a.ndim != 2:
        raise ValueError(f"occupancy grid must be 2-D, got shape {a.shape}")
    rows, cols = int(a.shape[0]), int(a.shape[1])
    res = float(resolution_m)
    data = np.flipud(a).astype(np.int8).reshape(-1)
    origin_y = -(rows - 1) * res if rows > 0 else 0.0
    st = _stamp(stamp)
    return {
        "header": {"frame_id": frame_id, "stamp": st},
        "info": {
            "map_load_time": dict(st),
            "resolution": res,
            "width": cols,
            "height": rows,
            "origin": {"position": {"x": 0.0, "y": float(origin_y), "z": 0.0},
                       "orientation": dict(_IDENTITY_QUAT)},
        },
        "data": [int(v) for v in data.tolist()],
    }


def occupancy_at(msg: dict, x: float, y: float):
    """Read the OccupancyGrid cell value at REP-103 map metres (x, y) (None if outside the grid). The
    inverse of the ``occupancy_grid_msg`` layout -- proves a rover pose indexes the intended cell."""
    info = msg["info"]
    res = float(info["resolution"])
    ox = float(info["origin"]["position"]["x"])
    oy = float(info["origin"]["position"]["y"])
    gc = int(round((float(x) - ox) / res))
    gr = int(round((float(y) - oy) / res))
    w, h = int(info["width"]), int(info["height"])
    if not (0 <= gc < w and 0 <= gr < h):
        return None
    return msg["data"][gr * w + gc]


# ---- cost-map: 12 FORGE layers -> one 0-100 OccupancyGrid + a blocking_reason GridMap layer -------
def costmap_values(cost, passable, *, cost_max: float | None = None) -> np.ndarray:
    """Collapse the composite cost + passable mask (`lode.costmap_layers.compose`) to an int8 0-100 grid:
    a passable cell's summed cost is normalized to 0..99 by the max passable cost, an impassable (or
    non-finite) cell is 100 lethal. No -1: a cost-map has no 'unknown' band (design row 3)."""
    c = np.asarray(cost, dtype=float)
    pas = np.asarray(passable, dtype=bool)
    finite = np.isfinite(c)
    lit = pas & finite
    cmax = float(cost_max) if cost_max is not None else (float(c[lit].max()) if lit.any() else 1.0)
    cmax = max(cmax, 1e-9)
    scaled = np.clip(np.rint(np.where(finite, c, 0.0) / cmax * float(_HAZARD_OCC)), 0, _HAZARD_OCC)
    return np.where(lit, scaled, float(OCC_LETHAL)).astype(np.int8)


def reason_enum_grid(reason, layer_names) -> tuple[np.ndarray, dict[int, str]]:
    """Encode the per-cell blocking-layer-name grid (`CompositeCostmap.reason`; "" = passable) as a float
    code grid + a code->name legend, so the reason is PRESERVED (AS-11) when carried as a GridMap layer:
    "" -> 0, each named layer -> its 1-based index in ``layer_names``."""
    r = np.asarray(reason, dtype=object)
    name_to_code: dict[str, int] = {"": 0}
    for i, n in enumerate(layer_names, start=1):
        name_to_code[str(n)] = i
    codes = np.zeros(r.shape, dtype=float)
    for name, code in name_to_code.items():
        if code == 0:
            continue
        codes[r == name] = float(code)
    legend = {code: name for name, code in name_to_code.items()}
    return codes, legend


def gridmap_msg(layers: dict, *, resolution_m: float, frame_id: str = "map",
                stamp: dict | None = None) -> dict:
    """Lower a stack of named float layers to a grid_map_msgs/GridMap-shaped dict. GridMap stores each
    layer as a column-major (Eigen) Float32MultiArray over a common geometry centred on ``pose``; the
    ``interop.gridmap_geotiff.GridMap`` dataclass is the on-disk twin of this wire shape (BA-06)."""
    names = list(layers.keys())
    if not names:
        raise ValueError("gridmap_msg needs at least one layer")
    first = np.asarray(layers[names[0]])
    rows, cols = int(first.shape[0]), int(first.shape[1])
    res = float(resolution_m)
    data = []
    for n in names:
        arr = np.asarray(layers[n], dtype=float)
        if arr.shape != (rows, cols):
            raise ValueError(f"gridmap layer {n!r} shape {arr.shape} != geometry {(rows, cols)}")
        data.append({
            "layout": {"dim": [
                {"label": "column_index", "size": cols, "stride": rows * cols},
                {"label": "row_index", "size": rows, "stride": rows},
            ], "data_offset": 0},
            "data": [float(v) for v in arr.reshape(-1, order="F").tolist()],   # column-major (grid_map)
        })
    return {
        "header": {"frame_id": frame_id, "stamp": _stamp(stamp)},
        "layers": names,
        "basic_layers": [],
        "info": {"resolution": res, "length_x": cols * res, "length_y": rows * res,
                 "pose": _pose(0.0, 0.0)},
        "data": data,
        "outer_start_index": 0,
        "inner_start_index": 0,
    }


def gridmap_layer_array(gm: dict, layer: str) -> np.ndarray:
    """Reconstruct a GridMap layer back into a north-up numpy array (the inverse of ``gridmap_msg``)."""
    idx = gm["layers"].index(layer)
    block = gm["data"][idx]
    dims = {d["label"]: int(d["size"]) for d in block["layout"]["dim"]}
    cols, rows = dims["column_index"], dims["row_index"]
    return np.asarray(block["data"], dtype=float).reshape((rows, cols), order="F")


def costmap_msgs(cost, passable, reason, *, resolution_m: float, layer_names,
                 frame_id: str = "map", stamp: dict | None = None) -> dict:
    """Lower a composite cost-map to the pair the contract reserves: a 0-100 ``nav_msgs/OccupancyGrid``
    (``/stewie/costmap``) plus a ``grid_map_msgs/GridMap`` ``blocking_reason`` layer (rides on
    ``/stewie/map/dem``) so the per-cell reason a route bent/refused is not lost. Returns the two msgs +
    a code->name reason legend."""
    occ = occupancy_grid_msg(costmap_values(cost, passable), resolution_m=resolution_m,
                             frame_id=frame_id, stamp=stamp)
    codes, legend = reason_enum_grid(reason, layer_names)
    gm = gridmap_msg({"blocking_reason": codes}, resolution_m=resolution_m, frame_id=frame_id, stamp=stamp)
    return {"occupancy": occ, "blocking_reason": gm, "reason_legend": legend}


# ---- nav_msgs/Path from the routed traverse ------------------------------------------------------
def path_msg(poses, *, frame_id: str = "map", stamp: dict | None = None) -> dict:
    """Assemble a nav_msgs/Path-shaped dict. ``poses`` is a sequence of PoseStamped-shaped dicts (the
    ``plan_lowering.lower_plan_ir`` output, already in the REP-103 map frame) OR (x, y) pairs."""
    st = _stamp(stamp)
    out = []
    for p in poses:
        if isinstance(p, dict):
            pose = p.get("pose") or _pose(0.0, 0.0)
            out.append({"header": {"frame_id": frame_id, "stamp": dict(st)}, "pose": pose})
        else:
            out.append({"header": {"frame_id": frame_id, "stamp": dict(st)},
                        "pose": _pose(float(p[0]), float(p[1]))})
    return {"header": {"frame_id": frame_id, "stamp": st}, "poses": out}


def path_from_plan_ir(ir: dict, *, frame_id: str = "map", stamp: dict | None = None) -> dict:
    """Assemble ONE nav_msgs/Path from the routed traverse in a plan IR (``mission_planner.plan_ir``): the
    GoTo legs' DEM-aware waypoint polylines, each order-frame vertex converted to the REP-103 map frame at
    the seam (``frames.local_xy_to_rep103`` -- the SAME y-sign flip the command lowering applies), then
    concatenated in leg order. This is the traverse POLYLINE only -- pure geometry, no motion/work command
    goals -- so the advisory path export never crosses the ROS command egress (EG-06)."""
    poses: list = []
    for a in ir.get("actions", []) or []:
        if a.get("op") != "GoTo":
            continue
        for p in a.get("waypoints") or []:
            poses.append(_FR.local_xy_to_rep103(float(p[0]), float(p[1])))
    return path_msg(poses, frame_id=frame_id, stamp=stamp)


# ---- MapMeta selenographic georef anchor ---------------------------------------------------------
def map_meta_msg(*, dem_name: str, dem_sha256: str, cell_m: float, order_origin_xy,
                 tile_x0: float, tile_y1: float, origin_lonlat=None,
                 iau_code: str = "IAU_2015:30135", iau_geographic: str = "IAU_2015:30100",
                 frame_id: str = "map", stamp: dict | None = None) -> dict:
    """The latched ``stewie_msgs/MapMeta`` co-published with every map/occupancy/costmap so a consumer
    recovers WHERE ON THE MOON the grid sits (no standard ROS type carries a planetary affine).

    ``order_origin_xy`` = the order-frame metres of the map (0,0) cell (the work-area anchor); ``tile_x0``/
    ``tile_y1`` = the DEM tile's IAU_2015:30135 north-up bounds (``metadata.json`` world_bounds_m). The
    ``iau_affine`` is the rasterio Affine 6-tuple (a,b,c,d,e,f) = (res,0,west,0,-res,north) of the window's
    NORTH-UP raster -- exactly the transform ``interop.gridmap_geotiff._transform`` writes -- so the same
    grid round-trips to a georeferenced GeoTIFF. ``origin_lonlat`` (deg, from ``dem_origin_to_latlon``) is
    carried when pyproj resolved it, else NaN (honest; never fabricated)."""
    ox, oy = float(order_origin_xy[0]), float(order_origin_xy[1])
    res = float(cell_m)
    west = float(tile_x0) + ox
    north = float(tile_y1) - oy
    iau_affine = [res, 0.0, west, 0.0, -res, north]      # rasterio Affine(a,b,c,d,e,f); == gridmap_geotiff
    lon = float("nan")
    lat = float("nan")
    if origin_lonlat is not None:
        lon, lat = float(origin_lonlat[0]), float(origin_lonlat[1])
    return {
        "header": {"frame_id": frame_id, "stamp": _stamp(stamp)},
        "dem_name": str(dem_name),
        "dem_sha256": str(dem_sha256),
        "iau_code": iau_code,
        "iau_geographic": iau_geographic,
        "resolution_m": res,
        "iau_affine": iau_affine,
        "map_origin_xy_m": [ox, oy],
        "origin_lon_deg": lon,
        "origin_lat_deg": lat,
    }


# ---- the rosbridge record wrapper (the RT-04 collector/feeder ingest shape) -----------------------
def rosbridge_record(topic: str, msg_type: str, msg: dict, *, qos: str | None = None) -> dict:
    """Wrap a lowered message in the rosbridge-compatible record the RT-04 feeder speaks (``{"topic",
    "type", "msg"}`` + the contract QoS class), ready to publish to ``/stewie/*``. Advisory only -- a
    record is data, never a command emission."""
    rec: dict = {"topic": str(topic), "type": str(msg_type), "msg": msg}
    if qos is not None:
        rec["qos"] = str(qos)
    return rec
