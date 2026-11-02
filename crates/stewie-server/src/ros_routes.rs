//! The ROS egress export (RW-55b23; Python `routers/nav` `/ros/export/*` over `stewie.bridge.ros_export`): the
//! backend's already-computed hazard grid, 12-layer costmap and routed traverse lowered onto the frozen
//! `/stewie/*` contract message shapes, each with a latched `MapMeta` selenographic anchor. Advisory and read-only:
//! these records are data a Nav2/RViz consumer reads, never a command (the command seam stays behind SF-01/AG-08).

use std::sync::Arc;

use axum::Router;
use axum::extract::{Request, State};
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::routing::post;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};

use crate::app::{
    ApiError, AppState, blocking, body_model, err, log, parse_body, require_auth, split,
};
use crate::operators::py_repr;
use crate::validate::{Field, Kind, Model};

const OCC_FREE: i8 = 0;
const OCC_LETHAL: i8 = 100;
const OCC_UNKNOWN: i8 = -1;
const CAUTION_OCC: i8 = 50;
const HAZARD_OCC: i8 = 99;

const fn float(
    gt: Option<(f64, &'static str)>,
    ge: Option<(f64, &'static str)>,
    le: (f64, &'static str),
    default: f64,
) -> Kind {
    Kind::Float {
        gt,
        ge,
        le: Some(le),
        default: Some(default),
    }
}

const fn text(max: usize, default: &'static str) -> Kind {
    Kind::Str {
        min: 0,
        max,
        nullable: false,
        default: Some(default),
    }
}

/// Python `RosGridRequest` (`extra="forbid"`).
const GRID_REQUEST: Model = Model {
    fields: &[
        Field("site", text(64, "haworth")),
        Field(
            "window_m",
            float(Some((0.0, "0")), None, (2000.0, "2000"), 300.0),
        ),
        Field(
            "max_slope_deg",
            float(Some((0.0, "0")), None, (89.0, "89"), 20.0),
        ),
        Field("keepouts", Kind::FloatTripleList { max: 512 }),
    ],
    forbid_extra: true,
};

/// Python `RosPathRequest` (`extra="forbid"`).
const PATH_REQUEST: Model = Model {
    fields: &[
        Field("mission", Kind::DictRequired),
        Field("site", text(64, "haworth")),
        Field("algorithm", text(40, "nearest")),
        Field("objective", text(40, "time")),
        Field(
            "max_traverse_slope_deg",
            float(None, Some((5.0, "5")), (45.0, "45"), 25.0),
        ),
    ],
    forbid_extra: true,
};

/// The work-area window of a site's real DEM at its flattest anchor (Python `_dem_window`).
struct Window {
    z: Vec<f64>,
    rows: usize,
    cols: usize,
    cell: f64,
    /// The order-frame metres of the window's (0, 0) cell.
    origin: (f64, f64),
    tile_x0: f64,
    tile_y1: f64,
    sha256: String,
    lonlat: Option<(f64, f64)>,
}

/// Crop the site's DEM to `window_m` from its flattest anchor and resolve the anchor's selenographic position: a
/// 404 for an unknown or unimported site (the Python's `KeyError` repr or `FileNotFoundError` text).
#[allow(
    clippy::cast_possible_truncation,
    clippy::cast_sign_loss,
    clippy::cast_precision_loss
)] // grid indices
fn dem_window(st: &AppState, site: &str, window_m: f64) -> Result<Window, ApiError> {
    let bundle = crate::dem_routes::bundle(st, site).map_err(|m| match m {
        crate::dem_routes::Missing::Unknown(e) | crate::dem_routes::Missing::NotImported(e) => {
            err(StatusCode::NOT_FOUND, e)
        }
    })?;
    let Some((dem, anchor)) = st.terrain.moon_dem(site) else {
        return Err(err(
            StatusCode::BAD_REQUEST,
            format!("no DEM bundle for site {}", py_repr(site)),
        ));
    };
    let cell = dem.cell_m;
    let (r0, c0) = (
        (anchor.1 / cell).round_ties_even() as usize,
        (anchor.0 / cell).round_ties_even() as usize,
    );
    let npx = ((window_m / cell).round_ties_even() as usize + 1).max(2);
    let (r1, c1) = ((r0 + npx).min(dem.rows), (c0 + npx).min(dem.cols));
    let (rows, cols) = (r1.saturating_sub(r0), c1.saturating_sub(c0));
    let z: Vec<f64> = (r0..r1)
        .flat_map(|r| dem.z[r * dem.cols + c0..r * dem.cols + c1].iter().copied())
        .collect();
    let origin = (c0 as f64 * cell, r0 as f64 * cell);
    let tile_bounds = crate::dem_routes::metadata(&bundle)
        .ok()
        .and_then(|m| {
            Some((
                m["world_bounds_m"]["x0"].as_f64()?,
                m["world_bounds_m"]["y1"].as_f64()?,
            ))
        })
        .unwrap_or((0.0, 0.0));
    // DT-01 provenance of the crop: the sha256 of its float32 bytes
    let bytes: Vec<u8> = z.iter().flat_map(|v| (*v as f32).to_le_bytes()).collect();
    let sha256 = Sha256::digest(&bytes)
        .iter()
        .fold(String::new(), |mut s, b| {
            use std::fmt::Write as _;
            let _ = write!(s, "{b:02x}");
            s
        });
    let lonlat = st
        .terrain
        .dem_origin_to_latlon(&dem, origin.0, origin.1)
        .ok()
        .map(|l| (l.lon_deg, l.lat_deg));
    Ok(Window {
        z,
        rows,
        cols,
        cell,
        origin,
        tile_x0: tile_bounds.0,
        tile_y1: tile_bounds.1,
        sha256,
        lonlat,
    })
}

/// Operator keep-out circles `(x, y, r)` [order metres in the window] rasterised (Python `_keepout_mask`).
#[allow(clippy::cast_precision_loss)] // grid indices
fn keepout_mask(rows: usize, cols: usize, cell: f64, keepouts: &[Value]) -> Vec<bool> {
    let mut m = vec![false; rows * cols];
    for k in keepouts {
        let f = |i: usize| k[i].as_f64().unwrap_or(0.0);
        let (kc, kr, rr) = (f(0) / cell, f(1) / cell, f(2) / cell);
        for r in 0..rows {
            for c in 0..cols {
                if (r as f64 - kr).powi(2) + (c as f64 - kc).powi(2) <= rr.powi(2) {
                    m[r * cols + c] = true;
                }
            }
        }
    }
    m
}

fn stamp() -> Value {
    json!({"sec": 0, "nanosec": 0})
}

fn pose(x: f64, y: f64) -> Value {
    json!({"position": {"x": x, "y": y, "z": 0.0}, "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}})
}

/// A north-up occupancy array as a `nav_msgs/OccupancyGrid` (REP-103: rows flipped so the row index grows along
/// +y, the origin at the min-y corner).
#[allow(clippy::cast_precision_loss)] // a grid height
fn occupancy_grid_msg(occ: &[i8], rows: usize, cols: usize, res: f64) -> Value {
    let data: Vec<i8> = (0..rows)
        .rev()
        .flat_map(|r| occ[r * cols..(r + 1) * cols].iter().copied())
        .collect();
    let origin_y = if rows > 0 {
        -((rows - 1) as f64) * res
    } else {
        0.0
    };
    json!({
        "header": {"frame_id": "map", "stamp": stamp()},
        "info": {"map_load_time": stamp(), "resolution": res, "width": cols, "height": rows,
                 "origin": {"position": {"x": 0.0, "y": origin_y, "z": 0.0},
                            "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}}},
        "data": data,
    })
}

fn record(topic: &str, msg_type: &str, msg: Value, qos: &str) -> Value {
    let mut rec = serde_json::Map::new();
    rec.insert("topic".into(), json!(topic));
    rec.insert("type".into(), json!(msg_type));
    rec.insert("msg".into(), msg);
    rec.insert("qos".into(), json!(qos));
    Value::Object(rec)
}

/// The latched `stewie_msgs/MapMeta` georef record: the window's `IAU_2015:30135` north-up affine and its anchor's
/// selenographic position (Python `map_meta_msg`).
fn map_meta(site: &str, w: &Window) -> Value {
    let (ox, oy) = w.origin;
    let (lon, lat) = w.lonlat.unwrap_or((f64::NAN, f64::NAN));
    let msg = json!({
        "header": {"frame_id": "map", "stamp": stamp()},
        "dem_name": site, "dem_sha256": w.sha256, "iau_code": "IAU_2015:30135", "iau_geographic": "IAU_2015:30100",
        "resolution_m": w.cell, "iau_affine": [w.cell, 0.0, w.tile_x0 + ox, 0.0, -w.cell, w.tile_y1 - oy],
        "map_origin_xy_m": [ox, oy], "origin_lon_deg": lon, "origin_lat_deg": lat,
    });
    record("/stewie/map/meta", "stewie_msgs/MapMeta", msg, "state")
}

/// AS-10: the hazard and keep-out grid as a `nav_msgs/OccupancyGrid` on `/stewie/map/occupancy` (0 free, 50
/// caution, 99 hazard, 100 lethal terrain or keep-out, -1 nodata).
#[allow(clippy::many_single_char_names)] // h, v, w as the other routes name the head, body and window
async fn export_occupancy(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let (h, bytes) = split(req, st.settings.max_body).await;
    blocking(st, move |st| {
        let body = parse_body(&bytes?)?;
        let who = require_auth(st, &h)?;
        let v = body_model(body.as_ref(), GRID_REQUEST)?;
        let site = v["site"].as_str().unwrap_or("haworth").to_owned();
        let w = dem_window(st, &site, v["window_m"].as_f64().unwrap_or(300.0))?;
        let max_slope = v["max_slope_deg"].as_f64().unwrap_or(20.0);
        let (slope, rough) = crate::raster::hazard_layers(&w.z, w.cols, w.rows, w.cell);
        let keep = keepout_mask(
            w.rows,
            w.cols,
            w.cell,
            v["keepouts"].as_array().map_or(&[][..], Vec::as_slice),
        );
        let occ: Vec<i8> = (0..w.z.len())
            .map(|i| {
                let (s, r) = (slope[i], rough[i]);
                let unknown = !r.is_finite();
                let nogo = s >= max_slope || !s.is_finite() || unknown;
                let mut o = if nogo {
                    if unknown { OCC_UNKNOWN } else { OCC_LETHAL }
                } else if s >= 15.0 || r >= 0.075 {
                    HAZARD_OCC
                } else if s >= 10.0 || r >= 0.0375 {
                    CAUTION_OCC
                } else {
                    OCC_FREE
                };
                if keep[i] {
                    o = OCC_LETHAL;
                }
                o
            })
            .collect();
        let mut rec = record(
            "/stewie/map/occupancy",
            "nav_msgs/OccupancyGrid",
            occupancy_grid_msg(&occ, w.rows, w.cols, w.cell),
            "state",
        );
        rec["map_meta"] = map_meta(&site, &w);
        rec["ok"] = json!(true);
        log(
            st,
            &h,
            &who,
            "ros.export.occupancy",
            &format!("{site}: {}x{}", w.rows, w.cols),
        );
        Ok(axum::Json(rec).into_response())
    })
    .await
}

/// AS-11: the 12-layer costmap as a 0-100 `nav_msgs/OccupancyGrid` on `/stewie/costmap`, with a
/// `grid_map_msgs/GridMap` `blocking_reason` layer on `/stewie/map/dem` that keeps why each cell blocks.
#[allow(
    clippy::many_single_char_names,
    clippy::cast_possible_truncation,
    clippy::cast_precision_loss
)] // a 0-99 band; layer codes
async fn export_costmap(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let (h, bytes) = split(req, st.settings.max_body).await;
    blocking(st, move |st| {
        let body = parse_body(&bytes?)?;
        let who = require_auth(st, &h)?;
        let v = body_model(body.as_ref(), GRID_REQUEST)?;
        let site = v["site"].as_str().unwrap_or("haworth").to_owned();
        let w = dem_window(st, &site, v["window_m"].as_f64().unwrap_or(300.0))?;
        let keep = keepout_mask(w.rows, w.cols, w.cell, v["keepouts"].as_array().map_or(&[][..], Vec::as_slice));
        let ise = |e: String| err(StatusCode::INTERNAL_SERVER_ERROR, e);
        let spine = crate::point::Spine::ipex(&st.planning).map_err(ise)?;
        // the Python's CostmapContext defaults beyond the window, the slope cap and the keep-outs
        let cm = stewie_traverse::layers::compose(&stewie_traverse::layers::Context {
            z: &w.z,
            width: w.cols,
            height: w.rows,
            cell_m: w.cell,
            max_slope_deg: v["max_slope_deg"].as_f64().unwrap_or(20.0),
            slip_alpha: 2.0,
            max_drop_m: 0.15,
            sun_az_deg: 200.0,
            sun_el_deg: 12.0,
            payload_kg: 0.0,
            max_sinkage_m: 0.10,
            gravity_ms2: spine.gravity_ms2,
            soil: spine.soil,
            rover: spine.rover,
            keepout: Some(&keep),
            reserved: None,
            clasts: &[],
        })
        .map_err(ise)?;
        // costmap_values: a passable cell's cost scaled to 0..99 by the passable maximum, else 100
        let lit: Vec<bool> = cm.cost.iter().zip(&cm.passable).map(|(c, p)| *p && c.is_finite()).collect();
        let cmax = cm
            .cost
            .iter()
            .zip(&lit)
            .filter(|(_, l)| **l)
            .map(|(c, _)| *c)
            .fold(None, |m: Option<f64>, c| Some(m.map_or(c, |m| m.max(c))))
            .unwrap_or(1.0)
            .max(1e-9);
        let occ: Vec<i8> = cm
            .cost
            .iter()
            .zip(&lit)
            .map(|(c, l)| {
                if *l {
                    let x = if c.is_finite() { *c } else { 0.0 };
                    (x / cmax * f64::from(HAZARD_OCC)).round_ties_even().clamp(0.0, f64::from(HAZARD_OCC)) as i8
                } else {
                    OCC_LETHAL
                }
            })
            .collect();
        let names = stewie_traverse::layers::LAYER_NAMES;
        let code = |r: Option<&str>| {
            r.and_then(|n| names.iter().position(|x| *x == n)).map_or(0.0, |i| (i + 1) as f64)
        };
        // the GridMap layer is column-major (Eigen)
        let column_major: Vec<f64> =
            (0..w.cols).flat_map(|c| (0..w.rows).map(move |r| (r, c))).map(|(r, c)| code(cm.reason[r * w.cols + c])).collect();
        let grid_map = json!({
            "header": {"frame_id": "map", "stamp": stamp()},
            "layers": ["blocking_reason"], "basic_layers": [],
            "info": {"resolution": w.cell, "length_x": w.cols as f64 * w.cell, "length_y": w.rows as f64 * w.cell,
                     "pose": pose(0.0, 0.0)},
            "data": [{"layout": {"dim": [
                          {"label": "column_index", "size": w.cols, "stride": w.rows * w.cols},
                          {"label": "row_index", "size": w.rows, "stride": w.rows}], "data_offset": 0},
                      "data": column_major}],
            "outer_start_index": 0, "inner_start_index": 0,
        });
        let mut legend = serde_json::Map::new();
        legend.insert("0".into(), json!(""));
        for (i, n) in names.iter().enumerate() {
            legend.insert((i + 1).to_string(), json!(n));
        }
        let mut rec =
            record("/stewie/costmap", "nav_msgs/OccupancyGrid", occupancy_grid_msg(&occ, w.rows, w.cols, w.cell), "state");
        rec["blocking_reason"] = record("/stewie/map/dem", "grid_map_msgs/GridMap", grid_map, "state");
        rec["reason_legend"] = Value::Object(legend);
        rec["map_meta"] = map_meta(&site, &w);
        rec["ok"] = json!(true);
        log(st, &h, &who, "ros.export.costmap", &format!("{site}: {}x{}", w.rows, w.cols));
        Ok(axum::Json(rec).into_response())
    })
    .await
}

/// NV-11: the routed traverse (the plan IR's DEM-aware `GoTo` polylines, each vertex in the REP-103 map frame) as a
/// `nav_msgs/Path` on `/stewie/plan/path`; the polyline only, never a command goal (EG-06).
#[allow(clippy::many_single_char_names)] // h, v, w as the other routes name the head, body and window
async fn export_path(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let (h, bytes) = split(req, st.settings.max_body).await;
    blocking(st, move |st| {
        let body = parse_body(&bytes?)?;
        let who = require_auth(st, &h)?;
        let v = body_model(body.as_ref(), PATH_REQUEST)?;
        let bad = |e: String| err(StatusCode::BAD_REQUEST, e);
        let m = st
            .planning
            .mission(&v["mission"])
            .map_err(|e| bad(format!("bad mission: {e}")))?;
        if m.body != "moon" {
            return Err(bad(format!(
                "path export needs a georeferenced lunar DEM; body {} has none",
                py_repr(&m.body)
            )));
        }
        let site = v["site"].as_str().unwrap_or("haworth").to_owned();
        let w = dem_window(st, &site, 100.0)?;
        let mission = v["mission"].as_object().cloned().unwrap_or_default();
        let slope = v["max_traverse_slope_deg"].as_f64().unwrap_or(25.0);
        let opts = crate::plan_routes::Opts {
            algorithm: v["algorithm"].as_str().unwrap_or("nearest"),
            objective: v["objective"].as_str().unwrap_or("time"),
            max_traverse_slope_deg: slope,
            raw_terrain: true,
            site: Some(&site),
            ..crate::plan_routes::DEFAULTS
        };
        let p = crate::plan_routes::plan_with(st, &mission, &opts)?;
        let ir =
            stewie_plan::ir::plan_ir(&p.mission, &p.plan, &p.ctx, p.dem(), slope).map_err(bad)?;
        let poses: Vec<Value> = ir["actions"]
            .as_array()
            .into_iter()
            .flatten()
            .filter(|a| a["op"] == "GoTo")
            .flat_map(|a| a["waypoints"].as_array().cloned().unwrap_or_default())
            .map(|p| {
                let (x, y) = (p[0].as_f64().unwrap_or(0.0), p[1].as_f64().unwrap_or(0.0));
                json!({"header": {"frame_id": "map", "stamp": stamp()}, "pose": pose(x, -y)})
            })
            .collect();
        let n = poses.len();
        let msg = json!({"header": {"frame_id": "map", "stamp": stamp()}, "poses": poses});
        let mut rec = record("/stewie/plan/path", "nav_msgs/Path", msg, "default");
        rec["map_meta"] = map_meta(&site, &w);
        rec["feasible"] = json!(ir.get("feasible").and_then(Value::as_bool).unwrap_or(true));
        rec["ok"] = json!(true);
        log(
            st,
            &h,
            &who,
            "ros.export.path",
            &format!("{site}: {n} poses"),
        );
        Ok(axum::Json(rec).into_response())
    })
    .await
}

/// The ROS egress export routes.
pub fn routes() -> Router<Arc<AppState>> {
    Router::new()
        .route("/ros/export/occupancy", post(export_occupancy))
        .route("/ros/export/costmap", post(export_costmap))
        .route("/ros/export/path", post(export_path))
}
