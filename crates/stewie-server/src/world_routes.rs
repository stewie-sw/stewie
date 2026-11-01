//! The world read surface (RW-55b5a; Python `routers.world`): the public map-data catalog reads (the LY-01 layer
//! catalog with each layer's confidence and tier, the consumption projection, the terramechanics-derived layers,
//! the visible site markers, a site's traffic hardening), the world transaction views, and the composed terrain
//! view's per-cell provenance (counts and a coloured raster). `/world` and `/world/layer-manifest` follow with the
//! layered costmap (RW-55b5b).

use std::path::PathBuf;
use std::sync::Arc;

use axum::Router;
use axum::extract::{Query, Request, State};
use axum::http::{HeaderValue, StatusCode, header};
use axum::response::{IntoResponse, Response};
use axum::routing::get;
use serde_json::{Map, Value, json};
use stewie_twin::terrain_view::Source;
use stewie_twin::traffic_memory::{self, Hardening};

use crate::app::{ApiError, AppState, Head, blocking, err, require_auth};
use crate::operators::py_repr;
use crate::validate::{self, Field, Kind, Model};

/// The LY-01 layer catalog, the committed source of truth.
const CATALOG: &str = include_str!("../../../stewie/server/layer_catalog.json");

/// Provenance token to (confidence class, tier) (GW-03), and the tokens' grounding strength, strongest first.
const CONF_TOKEN: [(&str, &str, &str); 16] = [
    ("live", "measured", "high"),
    ("observed", "measured", "high"),
    ("measured", "measured", "high"),
    ("reconciled", "measured", "high"),
    ("sim_truth", "measured", "high"),
    ("released", "approved", "high"),
    ("derived", "derived", "medium"),
    ("estimated", "modeled", "medium"),
    ("learned", "modeled", "medium"),
    ("forecast", "predicted", "low"),
    ("belief", "predicted", "low"),
    ("prior", "reference", "medium"),
    ("user", "authored", "n/a"),
    ("sim", "evidence", "n/a"),
    ("replay", "evidence", "n/a"),
    ("evidence", "evidence", "n/a"),
];
const CONF_MEASURED: [&str; 4] = ["live", "observed", "measured", "reconciled"];
const CONF_BASELINE: [&str; 6] = [
    "prior",
    "derived",
    "estimated",
    "learned",
    "forecast",
    "belief",
];

fn tokens(source_class: &str) -> Vec<&str> {
    source_class.split('/').filter(|t| !t.is_empty()).collect()
}

/// A layer's confidence from its declared `source_class`: the class of its strongest grounding token, and whether
/// a measured class is conditional on a baseline token also present.
fn layer_confidence(source_class: &str) -> Value {
    let toks = tokens(source_class);
    let best = CONF_TOKEN.iter().position(|(t, ..)| toks.contains(t));
    match best {
        None => {
            json!({"cls": "unknown", "tier": "n/a", "basis": source_class, "conditional": false})
        }
        Some(i) => {
            let (t, cls, tier) = CONF_TOKEN[i];
            let conditional =
                CONF_MEASURED.contains(&t) && toks.iter().any(|x| CONF_BASELINE.contains(x));
            json!({"cls": cls, "tier": tier, "basis": source_class, "conditional": conditional})
        }
    }
}

/// A layer's IN-02 tier from its domain and provenance tokens, in the Python's precedence.
fn layer_tier(layer: &Value) -> &'static str {
    const BELIEF: [&str; 6] = [
        "belief",
        "forecast",
        "estimated",
        "learned",
        "prior",
        "observed",
    ];
    const RAW: [&str; 5] = ["live", "replay", "sim", "sim_truth", "measured"];
    let dom = layer["domain"].as_str().unwrap_or("");
    let id = layer["id"].as_str().unwrap_or("");
    let toks = tokens(layer["source_class"].as_str().unwrap_or(""));
    if matches!(dom, "mission" | "design")
        || matches!(id, "map.changed_terrain" | "evidence.before_after_dem")
    {
        "mission"
    } else if dom == "base" || toks.contains(&"reconciled") {
        "world"
    } else if dom == "robot" || toks.iter().any(|t| BELIEF.contains(t)) {
        "belief"
    } else if toks.contains(&"derived") {
        "derived"
    } else if !toks.is_empty() && toks.iter().all(|t| RAW.contains(t)) {
        "raw"
    } else {
        "derived"
    }
}

/// The surfaces that consume a catalog layer (LY-02), derived from its eligibility, domain and provenance.
const CONSUMERS: [&str; 8] = [
    "display",
    "planner",
    "costmap",
    "rehearsal",
    "release",
    "execute",
    "report",
    "export",
];

fn consumers_for(layer: &Value) -> Vec<&'static str> {
    let dom = layer["domain"].as_str().unwrap_or("");
    let src = layer["source_class"].as_str().unwrap_or("");
    let mut out = vec!["display", "report"];
    if layer["planning_eligible"] == true {
        out.push("planner");
        if matches!(
            dom,
            "base" | "terrain" | "traffic" | "hazard" | "physics" | "regolith"
        ) {
            out.push("costmap");
        }
    }
    if layer["release_execute_eligible"] == true {
        out.extend(["release", "execute"]);
    }
    if matches!(dom, "runtime" | "physics" | "map" | "robot" | "mission")
        || src.contains("sim")
        || src.contains("observed")
    {
        out.push("rehearsal");
    }
    if dom != "runtime" {
        out.push("export");
    }
    CONSUMERS
        .iter()
        .copied()
        .filter(|c| out.contains(c))
        .collect()
}

fn catalog() -> Result<Value, ApiError> {
    serde_json::from_str(CATALOG).map_err(|e| {
        err(
            StatusCode::INTERNAL_SERVER_ERROR,
            format!("layer catalog: {e}"),
        )
    })
}

/// The catalog provenance of the given layer ids, read from the committed catalog.
fn catalog_provenance(cat: &Value, ids: &[&str]) -> Value {
    let rows = cat["layers"]
        .as_array()
        .map(Vec::as_slice)
        .unwrap_or_default();
    let mut out = Map::new();
    for id in ids {
        if let Some(r) = rows.iter().find(|r| r["id"] == *id) {
            out.insert((*id).to_owned(), json!({"source_class": r["source_class"],
                "planning_eligible": r["planning_eligible"], "release_execute_eligible": r["release_execute_eligible"]}));
        }
    }
    Value::Object(out)
}

/// The four PRD-named missing layer kinds (LY-04): the one with a real producer, and why the others have none.
fn missing_layer_kinds(cat: &Value) -> Value {
    json!([
        {"kind": "digital-twin-difference", "available": true, "producer": "changed_terrain",
         "catalog_ids": ["map.changed_terrain", "evidence.before_after_dem"],
         "provenance": catalog_provenance(cat, &["map.changed_terrain", "evidence.before_after_dem"]),
         "note": "the LY-07 signed as-built/observed-minus-base elevation-difference drape (render_globe \
                  'changed_terrain'): excavation (cut) negative/red, deposited material (fill/berm) positive/blue, \
                  unworked ground transparent; per-cell depth via /world/point runtime_evidence.as_built_delta_m; the \
                  drape carries the as_built/twin versions it was computed from."},
        {"kind": "ice-probability", "available": false, "catalog_ids": ["terrain.psr", "terrain.thermal"],
         "reason": "NO quantitative per-cell ice-probability producer -- terrain.thermal is catalog-only (no \
                    Diviner/LOLA thermal ice-stability raster wired). NOT fabricated. The real ice-relevant proxy that \
                    IS available is terrain.psr (permanently-shadowed cold-trap candidate, horizon-computed on the real \
                    DEM), a distinct classification rather than an ice probability; a quantitative depth-to-ice needs \
                    a Diviner/thermal dataset (the same gap transect_profile declares for ice_stability)."},
        {"kind": "localization-confidence", "available": false, "catalog_ids": ["robot.covariance", "map.uncertainty"],
         "reason": "NO producer on the static-prior GIS server -- localization covariance (robot.covariance) and \
                    map/pose uncertainty (map.uncertainty) are belief/live channels that only exist during a live \
                    run/replay (SLAM/EKF), not a per-cell raster over the fixed prior DEM. Typed + registered in the \
                    LY-01 catalog but not rendered here. NOT fabricated."},
        {"kind": "sensor-coverage", "available": false, "catalog_ids": ["robot.sensor_frustums", "terrain.los"],
         "reason": "NO viewshed/coverage producer wired -- robot.sensor_frustums is a live/sim/replay channel; the \
                    horizon-marched line-of-sight visibility producer for terrain.los/terrain.comms is tracked as LY-06 \
                    (not yet built). NOT fabricated."},
    ])
}

async fn layer_catalog() -> Response {
    let run = || -> Result<Response, ApiError> {
        let mut cat = catalog()?;
        let missing = missing_layer_kinds(&cat);
        if let Some(layers) = cat["layers"].as_array_mut() {
            for ly in layers.iter_mut() {
                let conf = layer_confidence(ly["source_class"].as_str().unwrap_or(""));
                let tier = layer_tier(ly);
                ly["confidence"] = conf;
                ly["tier"] = json!(tier);
            }
        }
        cat["missing_layer_kinds"] = missing;
        Ok(axum::Json(cat).into_response())
    };
    run().unwrap_or_else(IntoResponse::into_response)
}

async fn layer_consumption() -> Response {
    let run = || -> Result<Response, ApiError> {
        let cat = catalog()?;
        let rows: Vec<Value> = cat["layers"]
            .as_array()
            .map(Vec::as_slice)
            .unwrap_or_default()
            .iter()
            .map(|ly| json!({"id": ly["id"], "domain": ly["domain"], "consumers": consumers_for(ly)}))
            .collect();
        Ok(axum::Json(
            json!({"ok": true, "consumers": CONSUMERS, "count": rows.len(), "layers": rows}),
        )
        .into_response())
    };
    run().unwrap_or_else(IntoResponse::into_response)
}

/// Each derived catalog layer and the TM-02 spine terms it is computed from, and which of those a solver computes
/// (the rest are terrain inputs).
async fn terramechanics_layers() -> Response {
    const DERIVED: [(&str, &[&str]); 12] = [
        ("terrain.slope", &["slope"]),
        ("terrain.roughness", &["roughness"]),
        ("physics.bearing", &["contact_pressure"]),
        ("physics.sinkage", &["sinkage"]),
        ("physics.slip_risk", &["slip", "slope"]),
        ("physics.traction_margin", &["traction", "slip"]),
        ("physics.energy_cost", &["drive_energy"]),
        ("physics.excavation_resistance", &["excavation_draft"]),
        ("physics.compaction", &["compaction_resistance", "sinkage"]),
        ("traffic.traversability", &["slip", "slope", "traction"]),
        ("traffic.cost_global", &["drive_energy", "slope"]),
        ("traffic.compaction", &["contact_pressure", "sinkage"]),
    ];
    const SOLVED: [&str; 7] = [
        "contact_pressure",
        "sinkage",
        "slip",
        "traction",
        "compaction_resistance",
        "excavation_draft",
        "drive_energy",
    ];
    let rows: Vec<Value> = DERIVED
        .iter()
        .map(|(layer, terms)| {
            let computed: Vec<&str> = terms.iter().copied().filter(|t| SOLVED.contains(t)).collect();
            json!({"layer": layer, "from_terms": terms, "backend": "tier2_numpy", "computed_terms": computed})
        })
        .collect();
    axum::Json(
        json!({"ok": true, "backend": "tier2_numpy", "count": rows.len(), "derived_layers": rows}),
    )
    .into_response()
}

/// The visible-pin `GeoJSON`: `STEWIE_SITE_VECTORS`, else `STEWIE_GIS_DATA_DIR/vectors/`, else the checkout's
/// `data/gis/vectors/` beside the code (the Python's order).
fn site_vectors_path() -> Option<PathBuf> {
    let mut cands: Vec<PathBuf> = Vec::new();
    if let Ok(p) = std::env::var("STEWIE_SITE_VECTORS")
        && !p.is_empty()
    {
        cands.push(PathBuf::from(p));
    }
    if let Ok(g) = std::env::var("STEWIE_GIS_DATA_DIR")
        && !g.is_empty()
    {
        cands.push(
            PathBuf::from(g)
                .join("vectors")
                .join("artemis_sites.geojson"),
        );
    }
    cands.push(
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../../data/gis/vectors/artemis_sites.geojson"),
    );
    cands.into_iter().find(|c| c.is_file())
}

/// One public marker per visible pin (a Point feature): name, label, lon, lat, extent; nothing else.
fn site_markers() -> Vec<Value> {
    let Some(doc) = site_vectors_path()
        .and_then(|p| std::fs::read_to_string(p).ok())
        .and_then(|t| serde_json::from_str::<Value>(&t).ok())
    else {
        return Vec::new();
    };
    let mut out = Vec::new();
    for feat in doc["features"]
        .as_array()
        .map(Vec::as_slice)
        .unwrap_or_default()
    {
        let geom = &feat["geometry"];
        if geom["type"] != "Point" {
            continue;
        }
        let Some(c) = geom["coordinates"].as_array().filter(|c| c.len() >= 2) else {
            continue;
        };
        let props = &feat["properties"];
        let Some(key) = props["site"]
            .as_str()
            .or_else(|| props["name"].as_str())
            .filter(|k| !k.is_empty())
        else {
            continue;
        };
        let (Some(lon), Some(lat)) = (c[0].as_f64(), c[1].as_f64()) else {
            continue;
        };
        let extent = props["extent_m"]
            .as_array()
            .filter(|e| e.len() == 4)
            .and_then(|e| e.iter().map(Value::as_f64).collect::<Option<Vec<f64>>>());
        let label = props["label"]
            .as_str()
            .or_else(|| props["name"].as_str())
            .unwrap_or(key);
        out.push(json!({"name": key, "label": label, "lon": lon, "lat": lat, "extent_m": extent}));
    }
    out
}

async fn world_site_markers() -> Response {
    axum::Json(json!({"ok": true, "sites": site_markers()})).into_response()
}

fn site_of(q: &[(String, String)]) -> String {
    q.iter()
        .rev()
        .find(|(k, _)| k == "site")
        .map_or_else(|| "haworth".to_owned(), |(_, v)| v.clone())
}

/// A site's traffic hardening (TW-11): the summary, grid and provenance of its persisted traffic memory.
async fn traffic_layer(
    State(st): State<Arc<AppState>>,
    Query(q): Query<Vec<(String, String)>>,
) -> Response {
    let site = site_of(&q);
    blocking(st, move |st| {
        let internal = |e: String| err(StatusCode::INTERNAL_SERVER_ERROR, e);
        let Some(mem) = traffic_memory::load_site(&st.cfg.data_dir, &site).map_err(|e| internal(e.to_string()))? else {
            return Ok(axum::Json(json!({"ok": true, "site": site, "committed": false,
                                        "note": "no traffic hardening recorded for this site yet"}))
            .into_response());
        };
        let p = &st.planning;
        let soil = stewie_physics::soil::SoilParams::for_body(&p.bodies, &p.soil_base, "moon", false)
            .map_err(|e| internal(e.to_string()))?;
        let material = stewie_physics::material::MaterialModel::for_soil(&soil, &p.soil_base);
        let contact_len_m = p.fleet.vehicles.get("ipex").map_or(0.10, |v| v.contact_len_m);
        let gravity_ms2 = p.bodies.get("moon").map_or(1.62, |b| b.g);
        let h = Hardening { soil: &soil, contact_len_m, material: &material, gravity_ms2 };
        // the Python summary's bearing readout: a 0.30 m footing at a factor of safety of 3
        let s = mem.summary(&h, 0.30, 3.0);
        let head = mem.chain().last().map_or_else(String::new, |r| r.hash.clone());
        Ok(axum::Json(json!({
            "ok": true, "site": site, "committed": true,
            "summary": {"site": s.site, "version": s.version, "cells_trafficked": s.cells_trafficked,
                        "max_passes": s.max_passes, "max_load_cycles_n": s.max_load_cycles_n,
                        "peak_relative_density": s.peak_relative_density, "cells_firm_dr_gt_0p5": s.cells_firm_dr_gt_0p5,
                        "peak_bearing_uplift_pa": s.peak_bearing_uplift_pa, "missions": s.missions},
            "grid": {"rows": mem.rows, "cols": mem.cols, "cell_m": mem.cell_m, "origin": [mem.origin.0, mem.origin.1]},
            "provenance": {"version": mem.version(), "chain_head": head, "verified": mem.verify_chain(),
                           "sigma_c_n": mem.params.sigma_c_n, "mass_areal_kg_m2": mem.params.mass_areal,
                           "calibration": {"sigma_c_n": "[CALIB]", "road_layer_mass_areal": "[CALIB]"}},
        }))
        .into_response())
    })
    .await
}

async fn transaction(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let h = Head::of(&req);
    blocking(st, move |st| {
        require_auth(st, &h)?;
        let n = st.world.transaction_count();
        let out = match st.world.latest() {
            None => json!({"ok": true, "committed": false, "count": 0}),
            Some(t) => {
                json!({"ok": true, "committed": true, "count": n, "transaction": t.record()})
            }
        };
        Ok(axum::Json(out).into_response())
    })
    .await
}

const ANY_INT: Kind = Kind::Int {
    ge: i64::MIN,
    le: i64::MAX,
    default: 0,
};
const LIMIT_Q: Model = Model {
    fields: &[Field("limit", ANY_INT)],
    forbid_extra: false,
};
const MAX_PX_Q: Model = Model {
    fields: &[Field("max_px", ANY_INT)],
    forbid_extra: false,
};

/// A query integer with Pydantic's rule and message (`name: Input should be a valid integer, ...`); `model` holds
/// the one field `name`.
fn query_int(
    q: &[(String, String)],
    name: &str,
    model: Model,
    default: i64,
) -> Result<i64, ApiError> {
    match q.iter().rev().find(|(k, _)| k == name) {
        None => Ok(default),
        Some((_, v)) => {
            let m = validate::model(Some(&json!({name: v})), model)
                .map_err(|e| err(StatusCode::BAD_REQUEST, e))?;
            Ok(m[name].as_i64().unwrap_or(default))
        }
    }
}

async fn transactions(
    State(st): State<Arc<AppState>>,
    Query(q): Query<Vec<(String, String)>>,
    req: Request,
) -> Response {
    let h = Head::of(&req);
    blocking(st, move |st| {
        require_auth(st, &h)?;
        let limit = query_int(&q, "limit", LIMIT_Q, 50)?.clamp(1, 500);
        let recent = st.world.recent(usize::try_from(limit).unwrap_or(1));
        Ok(axum::Json(
            json!({"ok": true, "count": st.world.transaction_count(), "transactions": recent}),
        )
        .into_response())
    })
    .await
}

fn no_dem(site: &str) -> ApiError {
    err(
        StatusCode::NOT_FOUND,
        format!("no DEM bundle for site {}", py_repr(site)),
    )
}

async fn terrain_view(
    State(st): State<Arc<AppState>>,
    Query(q): Query<Vec<(String, String)>>,
    req: Request,
) -> Response {
    let h = Head::of(&req);
    blocking(st, move |st| {
        require_auth(st, &h)?;
        let site = site_of(&q);
        let (dem, origin) = st.terrain.moon_dem(&site).ok_or_else(|| no_dem(&site))?;
        let view = st.terrain.current_terrain_view(&site, &dem, origin);
        let count = |s: Source| view.source.iter().filter(|x| **x == s).count();
        Ok(axum::Json(json!({"ok": true, "site": site, "provenance": {
            "as_built_version": view.as_built_version, "twin_version": view.twin_version,
            "observed_fraction": view.observed_fraction, "cell_m": view.cell_m, "rows": dem.rows, "cols": dem.cols,
            "cells": {"pristine": count(Source::Pristine), "as_built": count(Source::AsBuilt),
                      "observed": count(Source::Observed)}}}))
        .into_response())
    })
    .await
}

/// The source map downsampled to at most `max_px` on its long side by block maximum (so a small measured or built
/// region survives), padded with pristine.
fn block_max(src: &[u8], rows: usize, cols: usize, max_px: usize) -> (Vec<u8>, usize, usize) {
    let factor = rows.max(cols).div_ceil(max_px.max(1)).max(1);
    if factor == 1 {
        return (src.to_vec(), rows, cols);
    }
    let (out_r, out_c) = (rows.div_ceil(factor), cols.div_ceil(factor));
    let mut out = vec![Source::Pristine as u8; out_r * out_c];
    for r in 0..rows {
        for c in 0..cols {
            let o = &mut out[(r / factor) * out_c + c / factor];
            *o = (*o).max(src[r * cols + c]);
        }
    }
    (out, out_r, out_c)
}

async fn terrain_view_png(
    State(st): State<Arc<AppState>>,
    Query(q): Query<Vec<(String, String)>>,
    req: Request,
) -> Response {
    let h = Head::of(&req);
    blocking(st, move |st| {
        require_auth(st, &h)?;
        let site = site_of(&q);
        let max_px =
            usize::try_from(query_int(&q, "max_px", MAX_PX_Q, 512)?.clamp(16, 2048)).unwrap_or(512);
        let (dem, origin) = st.terrain.moon_dem(&site).ok_or_else(|| no_dem(&site))?;
        let view = st.terrain.current_terrain_view(&site, &dem, origin);
        let src: Vec<u8> = view.source.iter().map(|s| *s as u8).collect();
        let (small, out_rows, out_cols) = block_max(&src, dem.rows, dem.cols, max_px);
        let rgb: Vec<u8> = small
            .iter()
            .flat_map(|k| COLORS[usize::from((*k).min(2))])
            .collect();
        let mut png = Vec::new();
        {
            let mut enc = png::Encoder::new(
                &mut png,
                u32::try_from(out_cols).unwrap_or(0),
                u32::try_from(out_rows).unwrap_or(0),
            );
            enc.set_color(png::ColorType::Rgb);
            enc.set_depth(png::BitDepth::Eight);
            let mut w = enc
                .write_header()
                .map_err(|e| err(StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;
            w.write_image_data(&rgb)
                .map_err(|e| err(StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;
        }
        let mut resp = png.into_response();
        resp.headers_mut()
            .insert(header::CONTENT_TYPE, HeaderValue::from_static("image/png"));
        resp.headers_mut()
            .insert(header::CACHE_CONTROL, HeaderValue::from_static("no-cache"));
        Ok(resp)
    })
    .await
}

/// The provenance raster's colours: pristine gray (modelled), as-built blue (remembered build), observed green
/// (measured).
const COLORS: [[u8; 3]; 3] = [[90, 90, 90], [40, 110, 220], [40, 190, 90]];

/// The world read routes.
pub fn routes() -> Router<Arc<AppState>> {
    Router::new()
        .route("/world/layer-catalog", get(layer_catalog))
        .route("/world/layer-consumption", get(layer_consumption))
        .route("/world/terramechanics-layers", get(terramechanics_layers))
        .route("/world/site-markers", get(world_site_markers))
        .route("/world/traffic-layer", get(traffic_layer))
        .route("/world/transaction", get(transaction))
        .route("/world/transactions", get(transactions))
        .route("/world/terrain_view", get(terrain_view))
        .route("/world/terrain_view.png", get(terrain_view_png))
}
