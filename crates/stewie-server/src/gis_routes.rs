//! GIS interchange (RW-55b20a; Python `routers.gis_export` over `lode.gis_export`, PRD GI-03): a plan as RFC-7946
//! `GeoJSON` in selenographic lon/lat (orders, typed footprints, keep-outs, the charger, the routed traverse from the
//! plan IR, the cockpit's markers), its inverse import back to the order frame, the offline mission package, and a
//! feature attribute query. Coordinates go through the tile's south-polar stereographic transform; a point off the
//! tile is refused, never fabricated.

#![allow(clippy::many_single_char_names)] // the Python's short names (m, p, q, h, v, e, f)

use std::sync::Arc;

use axum::Router;
use axum::extract::{Path, Query, Request, State};
use axum::http::{HeaderValue, StatusCode, header};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use serde_json::{Map, Value, json};
use stewie_plan::mission::{BuildOrder, Mission};
use stewie_traverse::costmap::Keepout;

use crate::app::{ApiError, AppState, Head, blocking, err, log, parse_body, require_auth, split};
use crate::dem_routes::{Missing, bundle};
use crate::operators::py_repr;
use crate::plan_routes::{DEFAULTS, Opts, plan_with};
use crate::state::SiteDem;
use crate::validate::{self, Field, Kind, Model};

const CRS_NAME: &str = "IAU_2015:30100";
/// Why there is no COG export on this server yet (Python `cog_available` when rasterio is absent).
const COG_UNAVAILABLE: &str = "COG export is not yet ported to the Rust server (RW-55b20b: no GeoTIFF writer in \
                               this build); the Python server serves it through rasterio.";

fn bad(e: impl Into<String>) -> ApiError {
    err(StatusCode::BAD_REQUEST, e)
}

/// Python `_xy_to_lonlat`: an order-frame point to `[lon, lat]`, 8 decimals.
fn lonlat(
    st: &AppState,
    dem: &SiteDem,
    origin: (f64, f64),
    (x, y): (f64, f64),
) -> Result<Value, ApiError> {
    let r = stewie_twin::numpy::round;
    let ll = st
        .terrain
        .dem_origin_to_latlon(dem, x + origin.0, y + origin.1)
        .map_err(bad)?;
    Ok(json!([r(ll.lon_deg, 8), r(ll.lat_deg, 8)]))
}

/// Python `_lonlat_to_xy`: `[lon, lat]` to the order frame (the pixel-centre the transform snaps to, less the anchor).
fn order_xy(
    st: &AppState,
    dem: &SiteDem,
    origin: (f64, f64),
    c: &Value,
) -> Result<(f64, f64), ApiError> {
    let (Some(lon), Some(lat)) = (
        c.get(0).and_then(Value::as_f64),
        c.get(1).and_then(Value::as_f64),
    ) else {
        return Err(bad("a coordinate must be a [lon, lat] pair of numbers"));
    };
    let (x, y) = st
        .terrain
        .latlon_to_order(dem, (0.0, 0.0), lon, lat)
        .map_err(bad)?;
    Ok((x - origin.0, y - origin.1))
}

/// A closed ring: the first point repeated last when it is not already.
fn closed(mut ring: Vec<(f64, f64)>) -> Vec<(f64, f64)> {
    if ring.first().is_some_and(|f| Some(f) != ring.last()) {
        ring.push(ring[0]);
    }
    ring
}

/// Python `_keepout_ring_xy`: a keep-out's boundary (a circle sampled at 32 points).
fn keepout_ring(k: &Keepout) -> Vec<(f64, f64)> {
    closed(match k {
        Keepout::Polygon(p) => p.clone(),
        Keepout::Rect { x0, y0, x1, y1 } => vec![(*x0, *y0), (*x1, *y0), (*x1, *y1), (*x0, *y1)],
        Keepout::Circle { x, y, r } => (0..32)
            .map(|i| {
                let a = 2.0 * std::f64::consts::PI * f64::from(i) / 32.0;
                (x + r * a.cos(), y + r * a.sin())
            })
            .collect(),
    })
}

/// Python `_footprint_ring_xy`: a typed footprint's outline about the order (rectangle, corridor, circle, polygon,
/// rotated by `theta_deg`), or `None` for a bare-area order.
fn footprint_ring(o: &BuildOrder) -> Option<Vec<(f64, f64)>> {
    let shape = o.shape.as_ref()?.as_object().filter(|s| !s.is_empty())?;
    let (cx, cy) = (o.x, o.y);
    let num = |k: &str| shape.get(k).and_then(Value::as_f64);
    let theta = num("theta_deg").unwrap_or(0.0).to_radians();
    let (ct, st) = (theta.cos(), theta.sin());
    let place = |pts: Vec<(f64, f64)>| -> Vec<(f64, f64)> {
        pts.into_iter()
            .map(|(lx, ly)| (cx + lx * ct - ly * st, cy + lx * st + ly * ct))
            .collect()
    };
    let kind = shape
        .get("kind")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_lowercase();
    let ring = match kind.as_str() {
        "rectangle" => {
            let (w, h) = (num("w")? / 2.0, num("h")? / 2.0);
            place(vec![(-w, -h), (w, -h), (w, h), (-w, h)])
        }
        "corridor" => {
            let (l, w) = (num("length")? / 2.0, num("width")? / 2.0);
            place(vec![(-l, -w), (l, -w), (l, w), (-l, w)])
        }
        "circle" => {
            let r = num("r")?;
            (0..32)
                .map(|i| {
                    let a = 2.0 * std::f64::consts::PI * f64::from(i) / 32.0;
                    (cx + r * a.cos(), cy + r * a.sin())
                })
                .collect()
        }
        "polygon" => place(
            shape
                .get("vertices")?
                .as_array()?
                .iter()
                .map(|v| Some((v.get(0)?.as_f64()?, v.get(1)?.as_f64()?)))
                .collect::<Option<_>>()?,
        ),
        _ => return None,
    };
    Some(closed(ring))
}

fn feature(geometry: Value, properties: Value) -> Value {
    let mut f = Map::new();
    f.insert("type".into(), json!("Feature"));
    f.insert("geometry".into(), geometry);
    f.insert("properties".into(), properties);
    Value::Object(f)
}

/// Python `plan_to_geojson`: the plan's `FeatureCollection` (orders, footprints, keep-outs, charger, the routed
/// traverse of the plan IR's `GoTo` legs, markers).
#[allow(clippy::too_many_arguments)] // the Python's keywords
fn plan_to_geojson(
    st: &AppState,
    payload: &Map<String, Value>,
    m: &Mission,
    opts: &Opts<'_>,
    markers: Option<&Value>,
) -> Result<Value, ApiError> {
    let p = plan_with(st, payload, opts)?;
    let (dem, _) = st.terrain.moon_dem(&p.site).ok_or_else(|| {
        err(
            StatusCode::SERVICE_UNAVAILABLE,
            format!("site {} DEM bundle absent", py_repr(&p.site)),
        )
    })?;
    let origin = p.origin;
    let ll = |xy: (f64, f64)| lonlat(st, &dem, origin, xy);
    let ring = |pts: Vec<(f64, f64)>| pts.into_iter().map(ll).collect::<Result<Vec<_>, _>>();
    let mut features = Vec::new();
    for o in &m.orders {
        features.push(feature(
            json!({"type": "Point", "coordinates": ll((o.x, o.y))?}),
            json!({"feature": "order", "action": o.action, "kind": o.kind.name(), "footprint_m2": o.footprint_m2,
                   "depth_m": o.depth_m}),
        ));
        if let Some(r) = footprint_ring(o) {
            features.push(feature(
                json!({"type": "Polygon", "coordinates": [ring(r)?]}),
                json!({"feature": "footprint", "action": o.action, "kind": o.kind.name()}),
            ));
        }
    }
    for (i, k) in m.keepouts.iter().enumerate() {
        features.push(feature(
            json!({"type": "Polygon", "coordinates": [ring(keepout_ring(k))?]}),
            json!({"feature": "keepout", "index": i}),
        ));
    }
    features.push(feature(
        json!({"type": "Point", "coordinates": ll(m.charger)?}),
        json!({"feature": "charger"}),
    ));
    let ir = stewie_plan::ir::plan_ir(
        &p.mission,
        &p.plan,
        &p.ctx,
        p.dem(),
        opts.max_traverse_slope_deg,
    )
    .map_err(bad)?;
    for a in ir["actions"]
        .as_array()
        .into_iter()
        .flatten()
        .filter(|a| a["op"] == "GoTo")
    {
        let wp: Vec<(f64, f64)> = a["waypoints"]
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(|w| Some((w.get(0)?.as_f64()?, w.get(1)?.as_f64()?)))
            .collect();
        if wp.len() < 2 {
            continue;
        }
        features.push(feature(
            json!({"type": "LineString", "coordinates": ring(wp)?}),
            json!({"feature": "route", "leg_id": a["id"], "vehicle": a["vehicle"],
                   "reached": a["reached"].as_bool().unwrap_or(true)}),
        ));
    }
    for mk in markers.and_then(Value::as_array).into_iter().flatten() {
        let (Some(x), Some(y)) = (
            mk.get("x").filter(|v| !v.is_null()),
            mk.get("y").filter(|v| !v.is_null()),
        ) else {
            continue;
        };
        let (Some(x), Some(y)) = (x.as_f64(), y.as_f64()) else {
            return Err(bad("a marker's x and y must be numbers"));
        };
        let str_of = |v: &Value| match v {
            Value::String(s) => s.clone(),
            other => stewie_twin::pyjson::repr(other),
        };
        let mut props = json!({"feature": "marker", "otype": mk.get("otype").filter(|v| !v.is_null()).map_or_else(|| "marker".to_owned(), str_of)});
        if let Some(l) = mk.get("label").filter(|v| !v.is_null()) {
            props["label"] = json!(str_of(l));
        }
        features.push(feature(
            json!({"type": "Point", "coordinates": ll((x, y))?}),
            props,
        ));
    }
    Ok(json!({
        "type": "FeatureCollection",
        "crs_note": format!("selenographic lon/lat ({CRS_NAME}); DEM source CRS IAU_2015:30135 (Moon south-polar \
                             stereographic, R=1737400 m). NOT Earth WGS84."),
        "properties": {"mission": m.name, "body": m.body, "algorithm": opts.algorithm, "objective": opts.objective,
                       "feasible": ir["feasible"].as_bool().unwrap_or(true)},
        "features": features,
    }))
}

const EXPORT_Q: Model = Model {
    fields: &[
        Field(
            "mission",
            Kind::Str {
                min: 0,
                max: usize::MAX,
                nullable: false,
                default: None,
            },
        ),
        Field(
            "site",
            Kind::Str {
                min: 0,
                max: 40,
                nullable: false,
                default: Some("haworth"),
            },
        ),
        Field(
            "algorithm",
            Kind::Str {
                min: 0,
                max: 40,
                nullable: false,
                default: Some("nearest"),
            },
        ),
        Field(
            "objective",
            Kind::Str {
                min: 0,
                max: 40,
                nullable: false,
                default: Some("time"),
            },
        ),
        Field(
            "lat",
            Kind::Opt(&Kind::Float {
                gt: None,
                ge: Some((-90.0, "-90")),
                le: Some((90.0, "90")),
                default: None,
            }),
        ),
        Field(
            "lon",
            Kind::Opt(&Kind::Float {
                gt: None,
                ge: Some((-360.0, "-360")),
                le: Some((360.0, "360")),
                default: None,
            }),
        ),
        Field(
            "max_traverse_slope_deg",
            Kind::Float {
                gt: None,
                ge: Some((5.0, "5")),
                le: Some((45.0, "45")),
                default: Some(25.0),
            },
        ),
    ],
    forbid_extra: false,
};

/// The export query's mission (parsed, validated, on the Moon) and the plan options.
struct Export {
    payload: Map<String, Value>,
    mission: Mission,
    site: String,
    algorithm: String,
    objective: String,
    lonlat: Option<(f64, f64)>,
    slope: f64,
}

fn export_request(st: &AppState, q: &[(String, String)], what: &str) -> Result<Export, ApiError> {
    let raw = crate::spec_routes::query(q, EXPORT_Q)?;
    let s = |k: &str, d: &str| raw.get(k).and_then(Value::as_str).unwrap_or(d).to_owned();
    let f = |k: &str| raw.get(k).and_then(|v| validate::as_float(v).ok());
    let text = s("mission", "");
    let parsed: Value =
        serde_json::from_str(&text).map_err(|e| bad(format!("mission is not valid JSON: {e}")))?;
    let Value::Object(payload) = parsed else {
        return Err(bad("mission must be a JSON object"));
    };
    let mission = st
        .planning
        .mission(&Value::Object(payload.clone()))
        .map_err(|e| bad(format!("bad mission: {e}")))?;
    if mission.body != "moon" {
        return Err(bad(format!(
            "{what} needs a georeferenced lunar DEM; body {} has none",
            py_repr(&mission.body)
        )));
    }
    Ok(Export {
        payload,
        mission,
        site: s("site", "haworth"),
        algorithm: s("algorithm", "nearest"),
        objective: s("objective", "time"),
        lonlat: f("lon").zip(f("lat")),
        slope: f("max_traverse_slope_deg").unwrap_or(25.0),
    })
}

/// Python `_resolve_origin`'s refusals: no DEM (503), no bundle (404); `site` set on the payload so the plan uses it.
fn resolve_site(st: &AppState, e: &mut Export, absent: &str) -> Result<(), ApiError> {
    if st.terrain.moon_dem(&e.site).is_none() {
        return Err(err(
            StatusCode::SERVICE_UNAVAILABLE,
            format!(
                "site {} DEM bundle absent; cannot {absent}",
                py_repr(&e.site)
            ),
        ));
    }
    bundle(st, &e.site).map_err(|m| match m {
        Missing::Unknown(x) | Missing::NotImported(x) => err(StatusCode::NOT_FOUND, x),
    })?;
    e.payload.insert("site".into(), json!(e.site));
    Ok(())
}

fn opts(e: &Export) -> Opts<'_> {
    Opts {
        algorithm: &e.algorithm,
        objective: &e.objective,
        max_traverse_slope_deg: e.slope,
        lonlat: e.lonlat,
        raw_terrain: true,
        ..DEFAULTS
    }
}

/// The plan as `GeoJSON` (any authenticated caller).
async fn export_geojson(
    State(st): State<Arc<AppState>>,
    Query(q): Query<Vec<(String, String)>>,
    req: Request,
) -> Response {
    let h = Head::of(&req);
    blocking(st, move |st| {
        require_auth(st, &h)?;
        let mut e = export_request(st, &q, "GeoJSON export")?;
        resolve_site(st, &mut e, "georeference the export")?;
        let markers = e.payload.get("markers").cloned();
        let fc = plan_to_geojson(st, &e.payload, &e.mission, &opts(&e), markers.as_ref())?;
        Ok((
            [(
                header::CONTENT_TYPE,
                HeaderValue::from_static("application/geo+json"),
            )],
            axum::Json(fc),
        )
            .into_response())
    })
    .await
}

/// The offline mission package (any authenticated caller): the plan's `GeoJSON` and the manifest a field operator
/// re-imports it with, without the live DEM.
async fn mission_package(
    State(st): State<Arc<AppState>>,
    Query(q): Query<Vec<(String, String)>>,
    req: Request,
) -> Response {
    let h = Head::of(&req);
    blocking(st, move |st| {
        require_auth(st, &h)?;
        let mut e = export_request(st, &q, "mission package")?;
        resolve_site(st, &mut e, "anchor the order frame")?;
        let fc = plan_to_geojson(st, &e.payload, &e.mission, &opts(&e), None)?;
        let p = plan_with(st, &e.payload, &opts(&e))?;
        let n = fc["features"].as_array().map_or(0, Vec::len);
        Ok(axum::Json(json!({
            "format": "stewie.mission_package/1.0",
            "manifest": {"mission": e.mission.name, "body": e.mission.body, "crs": CRS_NAME, "crs_note": fc["crs_note"],
                         "dem_origin": [p.origin.0, p.origin.1], "algorithm": e.algorithm, "objective": e.objective,
                         "feature_count": n, "raster_cog_available": false},
            "geojson": fc,
        }))
        .into_response())
    })
    .await
}

const IMPORT: Model = Model {
    fields: &[
        Field("featurecollection", Kind::DictRequired),
        Field(
            "site",
            Kind::Str {
                min: 0,
                max: 40,
                nullable: false,
                default: Some("haworth"),
            },
        ),
        Field(
            "lat",
            Kind::Opt(&Kind::Float {
                gt: None,
                ge: Some((-90.0, "-90.0")),
                le: Some((90.0, "90.0")),
                default: None,
            }),
        ),
        Field(
            "lon",
            Kind::Opt(&Kind::Float {
                gt: None,
                ge: Some((-360.0, "-360.0")),
                le: Some((360.0, "360.0")),
                default: None,
            }),
        ),
    ],
    forbid_extra: false,
};

/// The features of a `FeatureCollection`, or the Python's refusal of anything else.
fn features_of<'a>(fc: &'a Value, what: &str) -> Result<Vec<&'a Value>, ApiError> {
    if fc.get("type").and_then(Value::as_str) != Some("FeatureCollection") {
        return Err(bad(format!("{what} expects an RFC-7946 FeatureCollection")));
    }
    Ok(fc
        .get("features")
        .and_then(Value::as_array)
        .map(|a| a.iter().collect())
        .unwrap_or_default())
}

/// `GeoJSON` back to the order frame (any authenticated caller): the inverse of the export.
async fn gis_import(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let (h, bytes) = split(req, st.settings.max_body).await;
    blocking(st, move |st| {
        let body = parse_body(&bytes?)?;
        let identity = require_auth(st, &h)?;
        let v = crate::app::body_model(body.as_ref(), IMPORT)?;
        let site = v["site"].as_str().unwrap_or("haworth").to_owned();
        let f = |k: &str| v.get(k).and_then(Value::as_f64);
        let Some((dem, mut origin)) = st.terrain.moon_dem(&site) else {
            return Err(err(
                StatusCode::SERVICE_UNAVAILABLE,
                format!("site {} DEM bundle absent; cannot anchor the order frame", py_repr(&site)),
            ));
        };
        bundle(st, &site).map_err(|m| match m {
            Missing::Unknown(x) | Missing::NotImported(x) => err(StatusCode::NOT_FOUND, x),
        })?;
        if let (Some(lat), Some(lon)) = (f("lat"), f("lon")) {
            origin = st.terrain.latlon_to_order(&dem, (0.0, 0.0), lon, lat).map_err(bad)?;
        }
        let fc = &v["featurecollection"];
        let (mut orders, mut keepouts, mut charger, mut route) = (Vec::new(), Vec::new(), Value::Null, Vec::new());
        for f in features_of(fc, "geojson_to_features")? {
            let props = f.get("properties").filter(|p| p.is_object()).cloned().unwrap_or(json!({}));
            let geom = f.get("geometry").filter(|g| g.is_object()).cloned().unwrap_or(json!({}));
            let Some(coords) = geom.get("coordinates").filter(|c| !c.is_null()) else {
                continue;
            };
            let at = |c: &Value| order_xy(st, &dem, origin, c);
            let num = |k: &str| props.get(k).and_then(Value::as_f64).unwrap_or(0.0);
            match (props.get("feature").and_then(Value::as_str), geom.get("type").and_then(Value::as_str)) {
                (Some("order"), Some("Point")) => {
                    let (x, y) = at(coords)?;
                    orders.push(json!({"action": props.get("action"), "kind": props.get("kind"), "x": x, "y": y,
                                       "footprint_m2": num("footprint_m2"), "depth_m": num("depth_m")}));
                }
                (Some("keepout"), Some("Polygon")) => {
                    let ring = coords.get(0).and_then(Value::as_array).cloned().unwrap_or_default();
                    let pts = ring.iter().map(|c| at(c).map(|(x, y)| json!([x, y]))).collect::<Result<Vec<_>, _>>()?;
                    keepouts.push(json!({"points": pts, "index": props.get("index")}));
                }
                (Some("charger"), Some("Point")) => {
                    let (x, y) = at(coords)?;
                    charger = json!([x, y]);
                }
                (Some("route"), Some("LineString")) => {
                    let line = coords.as_array().cloned().unwrap_or_default();
                    let wp = line.iter().map(|c| at(c).map(|(x, y)| json!([x, y]))).collect::<Result<Vec<_>, _>>()?;
                    route.push(json!({"leg_id": props.get("leg_id"), "vehicle": props.get("vehicle"), "waypoints": wp}));
                }
                _ => {}
            }
        }
        log(st, &h, &identity, "gis.import", &site);
        Ok(axum::Json(json!({"ok": true, "orders": orders, "keepouts": keepouts, "charger": charger, "route": route}))
            .into_response())
    })
    .await
}

const QUERY: Model = Model {
    fields: &[
        Field("featurecollection", Kind::DictRequired),
        Field(
            "feature",
            Kind::Str {
                min: 0,
                max: 64,
                nullable: true,
                default: None,
            },
        ),
        Field("attrs", Kind::Dict),
    ],
    forbid_extra: false,
};

/// Python `==` between two JSON values: numbers by value (a bool as 0/1), containers element-wise.
fn py_eq(a: &Value, b: &Value) -> bool {
    let num = |v: &Value| match v {
        Value::Bool(x) => Some(f64::from(u8::from(*x))),
        Value::Number(n) => n.as_f64(),
        _ => None,
    };
    match (a, b) {
        (Value::Array(x), Value::Array(y)) => {
            x.len() == y.len() && x.iter().zip(y).all(|(p, q)| py_eq(p, q))
        }
        (Value::Object(x), Value::Object(y)) => {
            x.len() == y.len() && x.iter().all(|(k, v)| y.get(k).is_some_and(|w| py_eq(v, w)))
        }
        _ => match (num(a), num(b)) {
            (Some(p), Some(q)) => p == q,
            _ => a == b,
        },
    }
}

/// The features of a layer and with given attributes (any authenticated caller).
async fn gis_query(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let (h, bytes) = split(req, st.settings.max_body).await;
    blocking(st, move |st| {
        let body = parse_body(&bytes?)?;
        let identity = require_auth(st, &h)?;
        let v = crate::app::body_model(body.as_ref(), QUERY)?;
        let attrs = v.get("attrs").and_then(Value::as_object).cloned().unwrap_or_default();
        // the Python passes the attributes as keywords beside its own `fc` and `feature`
        if let Some(k) = ["fc", "feature"].iter().find(|k| attrs.contains_key(**k)) {
            return Err(bad(format!(
                "bad query attrs: lode.gis_export.query_features() got multiple values for keyword argument '{k}'"
            )));
        }
        let layer = v.get("feature").and_then(Value::as_str);
        let matches: Vec<Value> = features_of(&v["featurecollection"], "query_features")?
            .into_iter()
            .filter(|f| {
                let p = f.get("properties").filter(|p| p.is_object()).cloned().unwrap_or(json!({}));
                layer.is_none_or(|l| p.get("feature").and_then(Value::as_str) == Some(l))
                    && attrs.iter().all(|(k, want)| py_eq(p.get(k).unwrap_or(&Value::Null), want))
            })
            .cloned()
            .collect();
        log(st, &h, &identity, "gis.query", &format!("{} features matched", matches.len()));
        Ok(axum::Json(json!({"ok": true, "count": matches.len(), "features": matches})).into_response())
    })
    .await
}

/// Whether the COG export is available (public): not on this server yet (RW-55b20b).
async fn cog_available() -> Response {
    axum::Json(
        json!({"ok": true, "available": false, "reason": COG_UNAVAILABLE,
                      "format": "cloud-optimized GeoTIFF (IAU_2015:30135)"}),
    )
    .into_response()
}

/// A value raster as a COG (under the heavy quota): the kind is checked, then the missing writer reported (503).
async fn cog(State(st): State<Arc<AppState>>, Path(file): Path<String>, req: Request) -> Response {
    let Some(kind) = file.strip_suffix(".tif").map(str::to_owned) else {
        return crate::app::no_route_for(&axum::http::Method::GET, &format!("/export/cog/{file}"));
    };
    let h = Head::of(&req);
    blocking(st, move |st| {
        st.heavy(&h)?;
        if kind != "slope" {
            return Err(bad(format!(
                "unknown value-raster kind {}; supported: ['slope']",
                py_repr(&kind)
            )));
        }
        Err(err(StatusCode::SERVICE_UNAVAILABLE, COG_UNAVAILABLE))
    })
    .await
}

/// The GIS routes.
pub fn routes() -> Router<Arc<AppState>> {
    Router::new()
        .route("/export/geojson", get(export_geojson))
        .route("/export/cog/available", get(cog_available))
        .route("/export/cog/{file}", get(cog))
        .route("/gis/import", post(gis_import))
        .route("/gis/mission-package", get(mission_package))
        .route("/gis/query", post(gis_query))
}
