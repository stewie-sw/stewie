//! The DEM read surface (RW-55b6a; Python `routers.dem`): the tile's selenographic footprint and its
//! lat/lon <-> site-frame transforms, the tile's georeference metadata, the lunar DEM source catalog, the decimated
//! work-area and globe height grids, the settled boulder scene, and the bundled preview images. All behind
//! `require_auth`, as the Python. A site's DEM is its real bundle; nothing is fabricated for an absent one.

use std::path::PathBuf;
use std::sync::Arc;

use axum::Router;
use axum::extract::{Path, Query, Request, State};
use axum::http::{HeaderValue, StatusCode, header};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use serde_json::{Map, Value, json};
use stewie_twin::numpy::round;

use crate::app::{
    ApiError, AppState, Head, blocking, body_model, err, log, parse_body, require_auth, split,
};
use crate::operators::py_repr;
use crate::point::Spine;
use crate::state::SiteDem;
use crate::validate::{self, Field, Kind, Model};

const DEM_SOURCES: &str = include_str!("../../stewie-contracts/fixtures/dem_sources.json");

pub(crate) fn site_of(q: &[(String, String)]) -> String {
    q.iter()
        .rev()
        .find(|(k, _)| k == "site")
        .map_or_else(|| "haworth".to_owned(), |(_, v)| v.clone())
}

/// A site's bundle, or why not: an unknown site (the Python's `KeyError`, whose text is the message's repr), or
/// a known site with no bundle (its `FileNotFoundError`, plain).
pub(crate) enum Missing {
    Unknown(String),
    NotImported(String),
}

pub(crate) fn bundle(st: &AppState, site: &str) -> Result<PathBuf, Missing> {
    st.terrain.bundle_for_site(site).map_err(|e| {
        if st.terrain.is_known(site) {
            Missing::NotImported(e)
        } else {
            Missing::Unknown(py_repr(&e))
        }
    })
}

/// The 404 most routes give for either kind of missing bundle.
fn bundle_404(st: &AppState, site: &str) -> Result<PathBuf, ApiError> {
    bundle(st, site).map_err(|m| match m {
        Missing::Unknown(e) | Missing::NotImported(e) => err(StatusCode::NOT_FOUND, e),
    })
}

pub(crate) fn metadata(dir: &std::path::Path) -> Result<Value, String> {
    let path = dir.join("metadata.json");
    let text = std::fs::read_to_string(&path).map_err(|e| format!("{}: {e}", path.display()))?;
    serde_json::from_str(&text).map_err(|e| format!("{}: {e}", path.display()))
}

fn f(v: &Value) -> f64 {
    v.as_f64().unwrap_or(f64::NAN)
}

/// The query's named values, validated as Pydantic does (the last of a repeated key wins).
fn query(q: &[(String, String)], model: Model) -> Result<Map<String, Value>, ApiError> {
    let raw: Map<String, Value> = model
        .fields
        .iter()
        .filter_map(|Field(k, _)| {
            q.iter()
                .rev()
                .find(|(n, _)| n == k)
                .map(|(_, v)| ((*k).to_owned(), json!(v)))
        })
        .collect();
    validate::model(Some(&Value::Object(raw.clone())), model)
        .map_err(|e| err(StatusCode::BAD_REQUEST, e))?;
    Ok(raw)
}

pub(crate) const REQ_FLOAT: Kind = Kind::Float {
    gt: None,
    ge: None,
    le: None,
    default: None,
};

/// A validated query number read raw (a NaN stays a value).
fn num(raw: &Map<String, Value>, k: &str, default: f64) -> f64 {
    raw.get(k)
        .and_then(|v| validate::as_float(v).ok())
        .unwrap_or(default)
}

/// `numpy.linspace(start, stop, n)`: `i * step + start`, the last exactly `stop`.
#[allow(clippy::cast_precision_loss, clippy::similar_names)] // sample counts; numpy's start, stop, step
pub(crate) fn linspace(start: f64, stop: f64, n: usize) -> Vec<f64> {
    let step = (stop - start) / (n - 1) as f64;
    let mut v: Vec<f64> = (0..n).map(|i| i as f64 * step + start).collect();
    if n > 1 {
        v[n - 1] = stop;
    }
    v
}

/// `np.clip(np.round(v).astype(int), 0, hi)`.
#[allow(
    clippy::cast_possible_truncation,
    clippy::cast_sign_loss,
    clippy::cast_precision_loss
)] // in-grid indices
fn index(v: f64, hi: usize) -> usize {
    v.round_ties_even().clamp(0.0, hi as f64) as usize
}

/// The settled boulder scene (#147): the Chrono solve's `clasts_scene.json`, or an empty scene.
async fn clasts_scene(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let h = Head::of(&req);
    blocking(st, move |st| {
        require_auth(st, &h)?;
        let empty = json!({"present": false, "n": 0, "clasts": []});
        let doc = std::fs::read_to_string(st.cfg.data_dir.join("clasts_scene.json"))
            .ok()
            .and_then(|t| serde_json::from_str::<Value>(&t).ok());
        let out = match doc {
            None => empty,
            Some(Value::Object(mut m)) => {
                m.insert("present".into(), json!(true));
                Value::Object(m)
            }
            Some(_) => {
                return Err(err(
                    StatusCode::INTERNAL_SERVER_ERROR,
                    "clasts_scene.json is not an object",
                ));
            }
        };
        Ok(axum::Json(out).into_response())
    })
    .await
}

/// The tile's globe footprint (Python `site_dem.dem_georef_corners`): its projected corners and centre as
/// selenographic lat/lon, its CRS label and width [km].
fn georef_corners(st: &AppState, dir: &std::path::Path) -> Result<Map<String, Value>, String> {
    let meta = metadata(dir)?;
    let b = &meta["world_bounds_m"];
    let (x0, y0, x1, y1) = (f(&b["x0"]), f(&b["y0"]), f(&b["x1"]), f(&b["y1"]));
    let proj = st.terrain.projection();
    let ll = |x: f64, y: f64| {
        let p = proj.inverse(x, y);
        json!({"lat": p.lat_deg, "lon": p.lon_deg})
    };
    let mut out = Map::new();
    out.insert(
        "corners".into(),
        json!([ll(x0, y0), ll(x1, y0), ll(x1, y1), ll(x0, y1)]),
    );
    #[allow(clippy::manual_midpoint)] // the Python's (x0 + x1) / 2.0, bit for bit
    let centre = ll((x0 + x1) / 2.0, (y0 + y1) / 2.0);
    out.insert("center".into(), centre);
    out.insert(
        "crs".into(),
        meta["georeference"]["crs_kind"]
            .as_str()
            .filter(|s| !s.is_empty())
            .map_or_else(|| json!("IAU_2015:30135"), |s| json!(s)),
    );
    out.insert("tile_km".into(), json!(round((x1 - x0).abs() / 1000.0, 3)));
    Ok(out)
}

async fn dem_georef(
    State(st): State<Arc<AppState>>,
    Query(q): Query<Vec<(String, String)>>,
    req: Request,
) -> Response {
    let h = Head::of(&req);
    blocking(st, move |st| {
        require_auth(st, &h)?;
        let site = site_of(&q);
        let dir = bundle(st, &site).map_err(|m| match m {
            Missing::Unknown(e) => err(StatusCode::NOT_FOUND, e),
            Missing::NotImported(e) => err(StatusCode::SERVICE_UNAVAILABLE, e),
        })?;
        let corners =
            georef_corners(st, &dir).map_err(|e| err(StatusCode::SERVICE_UNAVAILABLE, e))?;
        let origin = st.terrain.moon_dem(&site).map_or((0.0, 0.0), |(_, o)| o);
        let mut out = Map::new();
        out.insert("ok".into(), json!(true));
        out.insert("site".into(), json!(site));
        out.extend(corners);
        out.insert("anchor_xy".into(), json!([origin.0, origin.1]));
        Ok(axum::Json(Value::Object(out)).into_response())
    })
    .await
}

/// The loaded DEM of a site whose bundle exists, else the route's 404.
fn site_dem(st: &AppState, site: &str) -> Result<(Arc<SiteDem>, (f64, f64)), ApiError> {
    st.terrain.moon_dem(site).ok_or_else(|| {
        err(
            StatusCode::NOT_FOUND,
            format!("no DEM for site {}", py_repr(site)),
        )
    })
}

/// A transform route's bundle: 404 for an unknown site, 503 (the Python's "absent" text) for an unimported one.
fn transform_bundle(st: &AppState, site: &str) -> Result<(), ApiError> {
    bundle(st, site).map(|_| ()).map_err(|m| match m {
        Missing::Unknown(e) => err(StatusCode::NOT_FOUND, e),
        Missing::NotImported(e) => err(
            StatusCode::SERVICE_UNAVAILABLE,
            format!("DEM/pyproj absent: {e}"),
        ),
    })
}

const LATLON_Q: Model = Model {
    fields: &[Field("lat", REQ_FLOAT), Field("lon", REQ_FLOAT)],
    forbid_extra: false,
};
const XY_Q: Model = Model {
    fields: &[Field("x", REQ_FLOAT), Field("y", REQ_FLOAT)],
    forbid_extra: false,
};

/// Selenographic lat/lon to the site's pixel-metre frame (Python `site_dem.latlon_to_dem_origin`).
async fn dem_site_xy(
    State(st): State<Arc<AppState>>,
    Query(q): Query<Vec<(String, String)>>,
    req: Request,
) -> Response {
    let h = Head::of(&req);
    blocking(st, move |st| {
        require_auth(st, &h)?;
        let raw = query(&q, LATLON_Q)?;
        let site = site_of(&q);
        transform_bundle(st, &site)?;
        let (dem, _) = site_dem(st, &site)?;
        let (x, y) = st
            .terrain
            .latlon_to_order(
                &dem,
                (0.0, 0.0),
                num(&raw, "lon", f64::NAN),
                num(&raw, "lat", f64::NAN),
            )
            .map_err(|e| err(StatusCode::UNPROCESSABLE_ENTITY, e))?;
        Ok(
            axum::Json(json!({"ok": true, "site": site, "x_m": round(x, 1), "y_m": round(y, 1)}))
                .into_response(),
        )
    })
    .await
}

/// The site's pixel-metre frame to selenographic lat/lon (Python `site_dem.dem_origin_to_latlon`).
async fn dem_site_lonlat(
    State(st): State<Arc<AppState>>,
    Query(q): Query<Vec<(String, String)>>,
    req: Request,
) -> Response {
    let h = Head::of(&req);
    blocking(st, move |st| {
        require_auth(st, &h)?;
        let raw = query(&q, XY_Q)?;
        let site = site_of(&q);
        transform_bundle(st, &site)?;
        let (dem, _) = site_dem(st, &site)?;
        let ll = st
            .terrain
            .dem_origin_to_latlon(&dem, num(&raw, "x", f64::NAN), num(&raw, "y", f64::NAN))
            .map_err(|e| err(StatusCode::UNPROCESSABLE_ENTITY, e))?;
        Ok(axum::Json(
            json!({"ok": true, "site": site, "lat": round(ll.lat_deg, 6),
                             "lon": round(ll.lon_deg, 6)}),
        )
        .into_response())
    })
    .await
}

/// The tile's georeference metadata for the 3D viewer's frame manager, every field from the bundle.
async fn dem_site_meta(
    State(st): State<Arc<AppState>>,
    Query(q): Query<Vec<(String, String)>>,
    req: Request,
) -> Response {
    let h = Head::of(&req);
    blocking(st, move |st| {
        require_auth(st, &h)?;
        let site = site_of(&q);
        let dir = bundle_404(st, &site)?;
        if !dir.join("metadata.json").is_file() {
            return Err(err(
                StatusCode::NOT_FOUND,
                format!("no DEM metadata for site {}", py_repr(&site)),
            ));
        }
        let meta = metadata(&dir).map_err(|e| err(StatusCode::INTERNAL_SERVER_ERROR, e))?;
        let (g, wb, prov) = (&meta["grid"], &meta["world_bounds_m"], &meta["dem_provenance"]);
        let cell = f(&g["cell_m"]);
        let (w, hgt) = (
            g["width"].as_u64().unwrap_or(0),
            g["height"].as_u64().unwrap_or(0),
        );
        let crs = meta["georeference"]["crs_kind"]
            .as_str()
            .filter(|s| !s.is_empty())
            .unwrap_or("IAU_2015:30135");
        let nodata = [&meta["nodata"], &meta["fields"]["heightmap"]["nodata"]]
            .into_iter()
            .find(|v| !v.is_null())
            .cloned()
            .unwrap_or_else(|| json!("NaN"));
        #[allow(clippy::cast_precision_loss)] // grid sizes
        let tile = json!({"x": (w.saturating_sub(1)) as f64 * cell, "y": (hgt.saturating_sub(1)) as f64 * cell});
        let origin = site_dem(st, &site)
            .ok()
            .and_then(|(dem, _)| st.terrain.dem_origin_to_latlon(&dem, 0.0, 0.0).ok())
            .map_or(Value::Null, |ll| {
                json!({"lon": round(ll.lon_deg, 6), "lat": round(ll.lat_deg, 6)})
            });
        Ok(axum::Json(json!({
            "ok": true, "site": site, "crs": crs,
            "bounds_m": {"x0": f(&wb["x0"]), "y0": f(&wb["y0"]), "x1": f(&wb["x1"]), "y1": f(&wb["y1"])},
            "pixel_size_m": cell, "width": w, "height": hgt, "tile_m": tile, "nodata": nodata,
            "vertical_datum": {"name": "MOON_ME",
                "sphere_radius_m": prov["sphere_radius_m"].as_f64().unwrap_or(1_737_400.0),
                "z_semantics": prov.get("z_semantics").cloned().unwrap_or_else(|| json!("height above sphere [m]"))},
            "origin_lonlat": origin,
        }))
        .into_response())
    })
    .await
}

/// The catalog fields the route serves, in the Python's order.
const SOURCE_KEYS: [&str; 13] = [
    "id",
    "name",
    "instrument",
    "resolution_m",
    "coverage",
    "crs",
    "fmt",
    "bundled",
    "planning_grade",
    "ingest",
    "access_url",
    "license",
    "notes",
];

/// The lunar DEM source catalog (#150): every selectable base layer with provenance, licence and readiness.
async fn dem_sources(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let h = Head::of(&req);
    blocking(st, move |st| {
        require_auth(st, &h)?;
        let cat: Value = serde_json::from_str(DEM_SOURCES)
            .map_err(|e| err(StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;
        let sources: Vec<Value> = cat["sources"]
            .as_array()
            .map(|a| {
                a.iter()
                    .map(|s| {
                        Value::Object(
                            SOURCE_KEYS
                                .iter()
                                .map(|k| ((*k).to_owned(), s[*k].clone()))
                                .collect(),
                        )
                    })
                    .collect()
            })
            .unwrap_or_default();
        Ok(axum::Json(json!({"ok": true, "sources": sources})).into_response())
    })
    .await
}

const HEIGHTFIELD_Q: Model = Model {
    fields: &[
        Field(
            "n",
            Kind::Int {
                ge: i64::MIN,
                le: i64::MAX,
                default: 129,
            },
        ),
        Field(
            "window_m",
            Kind::Float {
                gt: None,
                ge: None,
                le: None,
                default: Some(300.0),
            },
        ),
    ],
    forbid_extra: false,
};

/// The decimated work-area height grid (#165): `n` x `n` samples over the order frame `[0, window_m]^2` with the
/// planner's nearest-cell convention, row-major y then x.
#[allow(clippy::many_single_char_names)] // the Python's q, h, n, z
async fn dem_heightfield(
    State(st): State<Arc<AppState>>,
    Query(q): Query<Vec<(String, String)>>,
    req: Request,
) -> Response {
    let h = Head::of(&req);
    blocking(st, move |st| {
        require_auth(st, &h)?;
        let raw = query(&q, HEIGHTFIELD_Q)?;
        let site = site_of(&q);
        bundle_404(st, &site)?;
        let (dem, (ox, oy)) = site_dem(st, &site)?;
        let n = raw
            .get("n")
            .and_then(|v| v.as_str())
            .and_then(|s| s.trim().parse::<f64>().ok())
            .unwrap_or(129.0)
            .clamp(2.0, 257.0);
        #[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)] // clamped
        let n = n as usize;
        let win = num(&raw, "window_m", 300.0).clamp(10.0, 2000.0);
        let xs = linspace(0.0, win, n);
        let cols: Vec<usize> = xs
            .iter()
            .map(|x| index((ox + x) / dem.cell_m, dem.cols - 1))
            .collect();
        let rows: Vec<usize> = xs
            .iter()
            .map(|y| index((oy + y) / dem.cell_m, dem.rows - 1))
            .collect();
        let grid: Vec<f64> = rows
            .iter()
            .flat_map(|&r| {
                let (z, w) = (&dem.z, dem.cols);
                cols.iter().map(move |&c| z[r * w + c])
            })
            .collect();
        let (lo, hi) = (
            grid.iter().copied().fold(f64::INFINITY, f64::min),
            grid.iter().copied().fold(f64::NEG_INFINITY, f64::max),
        );
        Ok(axum::Json(
            json!({"ok": true, "site": site, "n": n, "window_m": win, "cell_m": dem.cell_m,
            "dem_origin": [ox, oy], "z": grid.iter().map(|v| round(*v, 3)).collect::<Vec<_>>(),
            "z_min": lo, "z_max": hi}),
        )
        .into_response())
    })
    .await
}

const TERRAIN_GRID_Q: Model = Model {
    fields: &[Field(
        "n",
        Kind::Int {
            ge: i64::MIN,
            le: i64::MAX,
            default: 64,
        },
    )],
    forbid_extra: false,
};

/// The globe 3D layer's georeferenced height grid (Python `site_dem.dem_terrain_grid`): `n` x `n` nodes across
/// the whole tile, each with its selenographic lat/lon and real elevation.
#[allow(clippy::many_single_char_names)] // the Python's q, h, n, p, z
async fn dem_terrain_grid(
    State(st): State<Arc<AppState>>,
    Query(q): Query<Vec<(String, String)>>,
    req: Request,
) -> Response {
    let h = Head::of(&req);
    blocking(st, move |st| {
        require_auth(st, &h)?;
        let raw = query(&q, TERRAIN_GRID_Q)?;
        let site = site_of(&q);
        bundle_404(st, &site)?;
        let (dem, _) = site_dem(st, &site)?;
        let n = raw
            .get("n")
            .and_then(|v| v.as_str())
            .and_then(|s| s.trim().parse::<f64>().ok())
            .unwrap_or(64.0)
            .clamp(2.0, 192.0);
        #[allow(
            clippy::cast_possible_truncation,
            clippy::cast_sign_loss,
            clippy::cast_precision_loss
        )] // clamped sizes
        let (n, w1, h1) = (n as usize, (dem.cols - 1) as f64, (dem.rows - 1) as f64);
        let ci: Vec<usize> = linspace(0.0, w1, n)
            .iter()
            .map(|v| index(*v, dem.cols - 1))
            .collect();
        let ri: Vec<usize> = linspace(0.0, h1, n)
            .iter()
            .map(|v| index(*v, dem.rows - 1))
            .collect();
        let (ax0, ay0) = dem.pixel0_m;
        let proj = st.terrain.projection();
        let (mut lat, mut lon, mut z) = (Vec::new(), Vec::new(), Vec::new());
        for &r in &ri {
            for &c in &ci {
                #[allow(clippy::cast_precision_loss)] // grid indices
                let p = proj.inverse(ax0 + c as f64 * dem.cell_m, ay0 - r as f64 * dem.cell_m);
                lat.push(round(p.lat_deg, 6));
                lon.push(round(p.lon_deg, 6));
                z.push(dem.z[r * dem.cols + c]);
            }
        }
        let (lo, hi) = (
            z.iter().copied().fold(f64::INFINITY, f64::min),
            z.iter().copied().fold(f64::NEG_INFINITY, f64::max),
        );
        #[allow(clippy::cast_precision_loss)] // grid sizes
        let tile = json!([
            round(dem.cols as f64 * dem.cell_m, 1),
            round(dem.rows as f64 * dem.cell_m, 1)
        ]);
        Ok(axum::Json(
            json!({"ok": true, "site": site, "n": n, "cell_m": dem.cell_m, "tile_m": tile,
            "lat": lat, "lon": lon, "z": z.iter().map(|v| round(*v, 2)).collect::<Vec<_>>(),
            "z_min": lo, "z_max": hi}),
        )
        .into_response())
    })
    .await
}

/// The bundle's LOLA preview images (`hillshade.png`, `height.png`).
async fn dem_preview(
    State(st): State<Arc<AppState>>,
    Path(name): Path<String>,
    Query(q): Query<Vec<(String, String)>>,
    req: Request,
) -> Response {
    let h = Head::of(&req);
    blocking(st, move |st| {
        require_auth(st, &h)?;
        let base = name.rsplit('/').next().unwrap_or("");
        let file = match base {
            "hillshade.png" => "preview_hillshade.png",
            "height.png" => "preview_height.png",
            _ => return Err(err(StatusCode::NOT_FOUND, format!("no dem {base}"))),
        };
        let dir = bundle_404(st, &site_of(&q))?;
        let bytes = std::fs::read(dir.join(file)).map_err(|_| {
            err(
                StatusCode::NOT_FOUND,
                format!("dem preview not available: {file}"),
            )
        })?;
        let mut r = bytes.into_response();
        r.headers_mut()
            .insert(header::CONTENT_TYPE, HeaderValue::from_static("image/png"));
        Ok(r)
    })
    .await
}

/// The full-resolution sampling plan over a square order-frame window (Python `heightfield_full.full_grid_spec`):
/// the window clamped to the tile, the native and emitted sample counts (an LOD stride past `max_dim`), and the
/// row and column of each sample.
#[derive(Debug, Clone)]
struct FullSpec {
    x0: f64,
    y0: f64,
    window_m: f64,
    n: usize,
    native_n: usize,
    step_m: f64,
    stride: f64,
    cols: Vec<usize>,
    rows: Vec<usize>,
    lod: bool,
}

#[allow(
    clippy::cast_precision_loss,
    clippy::cast_possible_truncation,
    clippy::cast_sign_loss
)] // grid sizes and clamped counts
fn full_grid_spec(dem: &SiteDem, x0: f64, y0: f64, window_m: f64, max_dim: i64) -> FullSpec {
    let cell = dem.cell_m;
    let max_dim = usize::try_from(max_dim.max(2)).unwrap_or(usize::MAX);
    let (tile_x, tile_y) = ((dem.cols - 1) as f64 * cell, (dem.rows - 1) as f64 * cell);
    let win = (2.0 * cell).max(window_m.min(tile_x).min(tile_y));
    let x0 = x0.max(0.0).min(tile_x - win);
    let y0 = y0.max(0.0).min(tile_y - win);
    let native_n = ((win / cell).round_ties_even() as usize + 1).max(2);
    let n = native_n.min(max_dim);
    let xs = linspace(0.0, win, n);
    FullSpec {
        x0,
        y0,
        window_m: win,
        n,
        native_n,
        step_m: win / (n - 1) as f64,
        stride: (native_n - 1) as f64 / (n - 1) as f64,
        cols: xs
            .iter()
            .map(|x| index((x0 + x) / cell, dem.cols - 1))
            .collect(),
        rows: xs
            .iter()
            .map(|y| index((y0 + y) / cell, dem.rows - 1))
            .collect(),
        lod: native_n > max_dim,
    }
}

/// The largest square window sampling the whole tile at native resolution (Python `native_full_window_m`).
#[allow(clippy::cast_precision_loss)] // grid sizes
fn native_full_window_m(dem: &SiteDem) -> f64 {
    (dem.cols.min(dem.rows) - 1) as f64 * dem.cell_m
}

const FULL_Q: Model = Model {
    fields: &[
        Field(
            "window_m",
            Kind::Float {
                gt: None,
                ge: None,
                le: None,
                default: Some(-1.0),
            },
        ),
        Field(
            "x0",
            Kind::Float {
                gt: None,
                ge: None,
                le: None,
                default: Some(0.0),
            },
        ),
        Field(
            "y0",
            Kind::Float {
                gt: None,
                ge: None,
                le: None,
                default: Some(0.0),
            },
        ),
        Field(
            "max_dim",
            Kind::Int {
                ge: i64::MIN,
                le: i64::MAX,
                default: 2048,
            },
        ),
        Field(
            "target_lines",
            Kind::Int {
                ge: i64::MIN,
                le: i64::MAX,
                default: 6,
            },
        ),
    ],
    forbid_extra: false,
};

/// An integer query value as validated (a whole number, possibly written as a float).
#[allow(clippy::cast_possible_truncation)] // validated integers
fn int(raw: &Map<String, Value>, k: &str, default: i64) -> i64 {
    raw.get(k)
        .and_then(|v| v.as_str())
        .and_then(|s| s.trim().parse::<f64>().ok())
        .map_or(default, |v| v as i64)
}

/// A viz route's site DEM: 404 for an unknown or unimported site, or one whose DEM does not load.
fn full_load(st: &AppState, site: &str) -> Result<Arc<SiteDem>, ApiError> {
    bundle_404(st, site)?;
    site_dem(st, site).map(|(d, _)| d)
}

/// The full-resolution grid (float32, row-major y then x) and its metadata.
fn heightfield_full(dem: &SiteDem, spec: &FullSpec) -> (Vec<f32>, Map<String, Value>) {
    #[allow(clippy::cast_possible_truncation)] // the bundle's heights are float32
    let grid: Vec<f32> = spec
        .rows
        .iter()
        .flat_map(|&r| spec.cols.iter().map(move |&c| (r, c)))
        .map(|(r, c)| dem.z[r * dem.cols + c] as f32)
        .collect();
    let lo = grid.iter().copied().fold(f32::INFINITY, f32::min);
    let hi = grid.iter().copied().fold(f32::NEG_INFINITY, f32::max);
    let meta = json!({
        "x0": round(spec.x0, 3), "y0": round(spec.y0, 3), "window_m": round(spec.window_m, 3),
        "cell_m": dem.cell_m, "n": spec.n, "native_n": spec.native_n, "step_m": round(spec.step_m, 6),
        "stride": round(spec.stride, 6), "lod": spec.lod, "width": dem.cols, "height": dem.rows,
        "z_min": f64::from(lo), "z_max": f64::from(hi),
    });
    let Value::Object(m) = meta else {
        unreachable!("a JSON object literal")
    };
    (grid, m)
}

fn full_spec_of(dem: &SiteDem, raw: &Map<String, Value>, max_dim: i64) -> FullSpec {
    let w = num(raw, "window_m", -1.0);
    let win = if w <= 0.0 {
        native_full_window_m(dem)
    } else {
        w
    };
    full_grid_spec(dem, num(raw, "x0", 0.0), num(raw, "y0", 0.0), win, max_dim)
}

/// The full-resolution height grid's metadata (sized before the binary fetch). Public, under the viz quota.
async fn dem_heightfield_full_meta(
    State(st): State<Arc<AppState>>,
    Query(q): Query<Vec<(String, String)>>,
    req: Request,
) -> Response {
    let h = Head::of(&req);
    blocking(st, move |st| {
        st.viz_quota(&h)?;
        let raw = query(&q, FULL_Q)?;
        let site = site_of(&q);
        let dem = full_load(st, &site)?;
        let spec = full_spec_of(&dem, &raw, int(&raw, "max_dim", 2048));
        let (_, mut meta) = heightfield_full(&dem, &spec);
        meta.insert("ok".into(), json!(true));
        meta.insert("site".into(), json!(site));
        Ok(axum::Json(Value::Object(meta)).into_response())
    })
    .await
}

/// A float as Python's `repr` (the `X-Dem-*` headers).
fn py_float(x: f64) -> String {
    stewie_twin::pyjson::float_repr(x).unwrap_or_else(|_| format!("{x}"))
}

/// The full-resolution height grid as little-endian float32, its metadata in `X-Dem-*` headers. Public, under the
/// viz quota.
async fn dem_heightfield_full_bin(
    State(st): State<Arc<AppState>>,
    Query(q): Query<Vec<(String, String)>>,
    req: Request,
) -> Response {
    let h = Head::of(&req);
    blocking(st, move |st| {
        st.viz_quota(&h)?;
        let raw = query(&q, FULL_Q)?;
        let site = site_of(&q);
        let dem = full_load(st, &site)?;
        let spec = full_spec_of(&dem, &raw, int(&raw, "max_dim", 2048));
        let (grid, meta) = heightfield_full(&dem, &spec);
        let body: Vec<u8> = grid.iter().flat_map(|v| v.to_le_bytes()).collect();
        let f = |k: &str| py_float(meta[k].as_f64().unwrap_or(f64::NAN));
        let headers = [
            ("x-dem-site", site.clone()),
            ("x-dem-n", spec.n.to_string()),
            ("x-dem-native-n", spec.native_n.to_string()),
            ("x-dem-cell-m", f("cell_m")),
            ("x-dem-window-m", f("window_m")),
            ("x-dem-step-m", f("step_m")),
            ("x-dem-stride", f("stride")),
            ("x-dem-x0", f("x0")),
            ("x-dem-y0", f("y0")),
            ("x-dem-z-min", f("z_min")),
            ("x-dem-z-max", f("z_max")),
            ("x-dem-width", dem.cols.to_string()),
            ("x-dem-height", dem.rows.to_string()),
            ("x-dem-lod", if spec.lod { "1" } else { "0" }.to_owned()),
        ];
        let mut r = body.into_response();
        let hm = r.headers_mut();
        hm.insert(
            header::CONTENT_TYPE,
            HeaderValue::from_static("application/octet-stream"),
        );
        hm.insert(
            header::CACHE_CONTROL,
            HeaderValue::from_static("public, max-age=3600"),
        );
        for (k, v) in headers {
            if let Ok(v) = HeaderValue::from_str(&v) {
                hm.insert(k, v);
            }
        }
        Ok(r)
    })
    .await
}

/// graticule.js `_range`: an inclusive float range rounded to 1e-6, capped at 100000 steps.
fn frange(a: f64, b: f64, step: f64) -> Vec<f64> {
    if step.is_nan() || step <= 0.0 || !a.is_finite() || !b.is_finite() {
        return if a.is_finite() {
            vec![round(a, 6)]
        } else {
            Vec::new()
        };
    }
    let (mut out, mut v) = (Vec::new(), a);
    while v <= b + 1e-9 && out.len() < 100_000 {
        out.push(round(v, 6));
        v += step;
    }
    out
}

/// A degree label as graticule.js writes it: whole degrees as `30°`, else the value rounded to 3 places.
#[allow(clippy::cast_possible_truncation)] // whole degrees
fn fmt_deg(v: f64) -> String {
    let r = v.round_ties_even();
    if (v - r).abs() < 1e-6 {
        format!("{}°", r as i64)
    } else {
        format!("{}°", py_float(round(v, 3)))
    }
}

/// A round 1/2/5 x 10^k line step for a span (Python `graticule_order.auto_steps._round_step`).
fn round_step(span: f64, n: i64) -> f64 {
    #[allow(clippy::cast_precision_loss)] // a line count
    let raw = span.max(1e-9) / n.max(1) as f64;
    #[allow(clippy::cast_possible_truncation)] // a decade exponent
    let k = if raw > 0.0 {
        raw.log10().floor() as i32
    } else {
        -3
    };
    let decade = 10_f64.powf(f64::from(k));
    let base = raw / decade;
    let mult = if base < 1.5 {
        1.0
    } else if base < 3.5 {
        2.0
    } else {
        5.0
    };
    mult * decade
}

/// One sampled line's runs of consecutive finite points inside the padded window, rounded to the millimetre.
fn line_runs(pts: &[(f64, f64)], win: f64, pad: f64) -> Vec<Vec<[f64; 2]>> {
    let (lo, hi) = (-pad, win + pad);
    let (mut runs, mut cur) = (Vec::new(), Vec::new());
    for &(x, y) in pts {
        let inside =
            x.is_finite() && y.is_finite() && (lo..=hi).contains(&x) && (lo..=hi).contains(&y);
        if inside {
            cur.push([round(x, 3), round(y, 3)]);
        } else if !cur.is_empty() {
            if cur.len() >= 2 {
                runs.push(std::mem::take(&mut cur));
            }
            cur.clear();
        }
    }
    if cur.len() >= 2 {
        runs.push(cur);
    }
    runs
}

/// The selenographic graticule in order-local metres over the viewer's window (Python `graticule_order`),
/// meridians then parallels, curved through the tile's polar stereographic frame. Public, under the viz quota.
#[allow(clippy::too_many_lines)] // one route, as the Python
async fn dem_graticule(
    State(st): State<Arc<AppState>>,
    Query(q): Query<Vec<(String, String)>>,
    req: Request,
) -> Response {
    let h = Head::of(&req);
    blocking(st, move |st| {
        st.viz_quota(&h)?;
        let raw = query(&q, FULL_Q)?;
        let site = site_of(&q);
        let dem = full_load(st, &site)?;
        #[allow(clippy::cast_possible_wrap)] // grid sizes
        let spec = full_spec_of(&dem, &raw, (dem.cols + dem.rows) as i64);
        let dir = bundle_404(st, &site)?;
        let geo = georef_corners(st, &dir).map_err(|e| err(StatusCode::NOT_FOUND, e))?;
        let corners = geo["corners"].as_array().cloned().unwrap_or_default();
        let lons: Vec<f64> = corners.iter().map(|c| f(&c["lon"])).collect();
        let lats: Vec<f64> = corners.iter().map(|c| f(&c["lat"])).collect();
        let ext = |v: &[f64], max: bool| {
            v.iter()
                .copied()
                .reduce(if max { f64::max } else { f64::min })
                .unwrap_or(f64::NAN)
        };
        let (lon_min, lon_max, lat_min, lat_max) = (
            ext(&lons, false),
            ext(&lons, true),
            ext(&lats, false),
            ext(&lats, true),
        );
        let target = int(&raw, "target_lines", 6).clamp(2, 20);
        let (lon_step, lat_step) = (
            round_step(lon_max - lon_min, target),
            round_step(lat_max - lat_min, target),
        );
        let (lon_sample, lat_sample) = (lon_step / 12.0, lat_step / 12.0);
        let proj = st.terrain.projection();
        let (ax0, ay0) = dem.pixel0_m;
        let reproject = |lon: f64, lat: f64| -> (f64, f64) {
            proj.forward(lunar_frames::LatLon {
                lat_deg: lat,
                lon_deg: lon,
            })
            .map_or((f64::NAN, f64::NAN), |(xs, ys)| {
                (xs - ax0 - spec.x0, ay0 - ys - spec.y0)
            })
        };
        let pad = spec.window_m * 0.02;
        let mut lines = Vec::new();
        let mut emit = |pts: Vec<(f64, f64)>, v: f64, kind: &str| {
            for run in line_runs(&pts, spec.window_m, pad) {
                lines.push(json!({"coords": run, "label": fmt_deg(v), "value": v, "kind": kind}));
            }
        };
        for lon in frange(lon_min, lon_max, lon_step) {
            let ls = frange(lat_min, lat_max, lat_sample);
            if ls.len() >= 2 {
                emit(
                    ls.iter().map(|&lat| reproject(lon, lat)).collect(),
                    lon,
                    "meridian",
                );
            }
        }
        for lat in frange(lat_min, lat_max, lat_step) {
            let ls = frange(lon_min, lon_max, lon_sample);
            if ls.len() >= 2 {
                emit(
                    ls.iter().map(|&lon| reproject(lon, lat)).collect(),
                    lat,
                    "parallel",
                );
            }
        }
        Ok(axum::Json(
            json!({"ok": true, "site": site, "x0": spec.x0, "y0": spec.y0,
            "window_m": spec.window_m, "crs": geo["crs"], "lines": lines}),
        )
        .into_response())
    })
    .await
}

const WORKAREA_Q: Model = Model {
    fields: &[
        Field(
            "window_m",
            Kind::Float {
                gt: None,
                ge: None,
                le: None,
                default: Some(640.0),
            },
        ),
        Field(
            "sun_az",
            Kind::Float {
                gt: None,
                ge: None,
                le: None,
                default: Some(315.0),
            },
        ),
        Field(
            "sun_el",
            Kind::Float {
                gt: None,
                ge: None,
                le: None,
                default: Some(45.0),
            },
        ),
        Field("lat", Kind::Opt(&REQ_FLOAT)),
        Field("lon", Kind::Opt(&REQ_FLOAT)),
    ],
    forbid_extra: false,
};

/// Python `round(x) % 360` and the clamped elevation: the quantised sun the work-area drape renders under.
#[allow(clippy::cast_possible_truncation)] // whole degrees
pub(crate) fn quantised_sun(az: f64, el: f64) -> (f64, f64) {
    let az = (az.round_ties_even() as i64).rem_euclid(360);
    let el = (el.round_ties_even() as i64).clamp(-90, 90);
    #[allow(clippy::cast_precision_loss)] // whole degrees
    (az as f64, el as f64)
}

/// The work-area layer raster (GIS-WA1/WA2): the order-frame window `[0, window_m]^2` sampled from the site DEM at
/// native resolution, drawn by the chosen layer, north up. An optional lat/lon re-anchors the window.
async fn dem_workarea_png(
    State(st): State<Arc<AppState>>,
    Query(q): Query<Vec<(String, String)>>,
    req: Request,
) -> Response {
    let h = Head::of(&req);
    blocking(st, move |st| {
        require_auth(st, &h)?;
        let raw = query(&q, WORKAREA_Q)?;
        let site = site_of(&q);
        let kind = q
            .iter()
            .rev()
            .find(|(k, _)| k == "kind")
            .map_or_else(|| "dem".to_owned(), |(_, v)| v.clone());
        let win = num(&raw, "window_m", 640.0).clamp(10.0, 2000.0);
        let (az, el) = quantised_sun(num(&raw, "sun_az", 315.0), num(&raw, "sun_el", 45.0));
        bundle_404(st, &site)?;
        let (dem, origin) = site_dem(st, &site)?;
        let (lat, lon) = (
            raw.get("lat").and_then(|v| validate::as_float(v).ok()),
            raw.get("lon").and_then(|v| validate::as_float(v).ok()),
        );
        // a picked lat/lon re-anchors the window (absolute pixel-metres); outside the tile keeps the anchor
        let (ox, oy) = match (lat, lon) {
            (Some(la), Some(lo)) => st
                .terrain
                .latlon_to_order(&dem, (0.0, 0.0), lo, la)
                .unwrap_or(origin),
            _ => origin,
        };
        #[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)] // a clamped sample count
        let npx = ((win / dem.cell_m).round_ties_even() as usize + 1).max(2);
        let xs = linspace(0.0, win, npx);
        let cols: Vec<usize> = xs
            .iter()
            .map(|x| index((ox + x) / dem.cell_m, dem.cols - 1))
            .collect();
        let rows: Vec<usize> = xs
            .iter()
            .map(|y| index((oy + y) / dem.cell_m, dem.rows - 1))
            .collect();
        let patch: Vec<f64> = rows
            .iter()
            .flat_map(|&r| cols.iter().map(move |&c| (r, c)))
            .map(|(r, c)| dem.z[r * dem.cols + c])
            .collect();
        let gnb = if matches!(kind.as_str(), "illumination" | "incidence") {
            st.terrain
                .grid_north_bearing_deg(&dem, ox + win / 2.0, oy + win / 2.0)
                .ok()
        } else {
            None
        };
        let rgba = crate::raster::layer_rgba(&patch, npx, npx, dem.cell_m, &kind, az, el, gnb)
            .ok_or_else(|| {
                err(
                    StatusCode::BAD_REQUEST,
                    format!("unknown layer kind {}", py_repr(&kind)),
                )
            })?;
        let png = crate::raster::png_rgba(&crate::raster::flipud(&rgba, npx), npx, npx)
            .map_err(|e| err(StatusCode::INTERNAL_SERVER_ERROR, e))?;
        let mut r = png.into_response();
        r.headers_mut()
            .insert(header::CONTENT_TYPE, HeaderValue::from_static("image/png"));
        Ok(r)
    })
    .await
}

const LAYER_Q: Model = Model {
    fields: &[
        Field(
            "window_m",
            Kind::Float {
                gt: None,
                ge: None,
                le: None,
                default: Some(-1.0),
            },
        ),
        Field(
            "x0",
            Kind::Float {
                gt: None,
                ge: None,
                le: None,
                default: Some(0.0),
            },
        ),
        Field(
            "y0",
            Kind::Float {
                gt: None,
                ge: None,
                le: None,
                default: Some(0.0),
            },
        ),
        Field(
            "sun_az",
            Kind::Float {
                gt: None,
                ge: None,
                le: None,
                default: Some(315.0),
            },
        ),
        Field(
            "sun_el",
            Kind::Float {
                gt: None,
                ge: None,
                le: None,
                default: Some(45.0),
            },
        ),
        Field(
            "out_px",
            Kind::Int {
                ge: i64::MIN,
                le: i64::MAX,
                default: -1,
            },
        ),
    ],
    forbid_extra: false,
};

/// The drape's texture size (Python `heightfield_full.suggested_layer_px`): the horizon-sweep kinds small, the
/// gradient kinds larger, never past the mesh.
fn suggested_layer_px(kind: &str, n: usize) -> usize {
    let cap = if matches!(kind, "psr" | "cost" | "blocking") {
        384
    } else {
        1024
    };
    n.min(cap).max(2)
}

/// The 3D viewer's analysis drape over the same window as `/dem/heightfield_full`, north up, at a texture size of
/// its own. Public, under the viz quota.
#[allow(clippy::too_many_lines)] // one route, as the Python
async fn dem_heightfield_full_layer(
    State(st): State<Arc<AppState>>,
    Query(q): Query<Vec<(String, String)>>,
    req: Request,
) -> Response {
    let h = Head::of(&req);
    blocking(st, move |st| {
        st.viz_quota(&h)?;
        let raw = query(&q, LAYER_Q)?;
        let site = site_of(&q);
        let kind = q
            .iter()
            .rev()
            .find(|(k, _)| k == "kind")
            .map_or_else(|| "dem".to_owned(), |(_, v)| v.clone());
        let dem = full_load(st, &site)?;
        let w = num(&raw, "window_m", -1.0);
        let win = if w <= 0.0 {
            native_full_window_m(&dem)
        } else {
            w
        };
        #[allow(clippy::cast_possible_wrap)] // grid sizes
        let spec = full_grid_spec(
            &dem,
            num(&raw, "x0", 0.0),
            num(&raw, "y0", 0.0),
            win,
            (dem.cols + dem.rows) as i64,
        );
        let out_px = int(&raw, "out_px", -1);
        #[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)] // clamped
        let px = if out_px <= 0 {
            suggested_layer_px(&kind, spec.n)
        } else {
            out_px.clamp(2, 2048) as usize
        };
        let (az, el) = quantised_sun(num(&raw, "sun_az", 315.0), num(&raw, "sun_el", 45.0));
        let xs = linspace(0.0, spec.window_m, px);
        let cols: Vec<usize> = xs
            .iter()
            .map(|x| index((spec.x0 + x) / dem.cell_m, dem.cols - 1))
            .collect();
        let rows: Vec<usize> = xs
            .iter()
            .map(|y| index((spec.y0 + y) / dem.cell_m, dem.rows - 1))
            .collect();
        let patch: Vec<f64> = rows
            .iter()
            .flat_map(|&r| cols.iter().map(move |&c| (r, c)))
            .map(|(r, c)| dem.z[r * dem.cols + c])
            .collect();
        let gnb = if matches!(
            kind.as_str(),
            "illumination" | "incidence" | "cost" | "blocking"
        ) {
            st.terrain
                .grid_north_bearing_deg(
                    &dem,
                    spec.x0 + spec.window_m / 2.0,
                    spec.y0 + spec.window_m / 2.0,
                )
                .ok()
        } else {
            None
        };
        #[allow(clippy::cast_precision_loss)] // a pixel count
        let cm = if px > 1 {
            spec.window_m / (px - 1) as f64
        } else {
            dem.cell_m
        };
        let ise = |e: String| err(StatusCode::INTERNAL_SERVER_ERROR, e);
        let rgba = if matches!(kind.as_str(), "cost" | "blocking") {
            let spine = Spine::ipex(&st.planning).map_err(ise)?;
            crate::raster::costmap_rgba(&patch, px, px, cm, &kind, az, el, gnb, &spine)
                .map_err(ise)?
        } else if let Some(r) = {
            let spine = Spine::ipex(&st.planning).map_err(ise)?;
            crate::raster::physics_rgba(&patch, px, px, cm, &kind, &spine).map_err(ise)?
        } {
            Some(r)
        } else {
            crate::raster::layer_rgba(&patch, px, px, cm, &kind, az, el, gnb)
        }
        .ok_or_else(|| {
            err(
                StatusCode::BAD_REQUEST,
                format!("unknown layer kind {}", py_repr(&kind)),
            )
        })?;
        let png =
            crate::raster::png_rgba(&crate::raster::flipud(&rgba, px), px, px).map_err(ise)?;
        let mut r = png.into_response();
        r.headers_mut()
            .insert(header::CONTENT_TYPE, HeaderValue::from_static("image/png"));
        Ok(r)
    })
    .await
}

/// A composed planning surface: heights (row-major), columns, rows, cell [m] and its order-frame anchor.
type Surface = (Vec<f64>, usize, usize, f64, (f64, f64));

/// The as-built request (Python `AsBuiltRequest`; unknown keys are ignored, as Pydantic's default).
const ASBUILT_REQ: Model = Model {
    fields: &[
        Field(
            "body",
            Kind::Str {
                min: 0,
                max: usize::MAX,
                nullable: false,
                default: Some("moon"),
            },
        ),
        Field(
            "site",
            Kind::Str {
                min: 0,
                max: usize::MAX,
                nullable: false,
                default: Some("haworth"),
            },
        ),
        Field("orders", Kind::AnyListDefault),
        Field("lat", Kind::Opt(&REQ_FLOAT)),
        Field("lon", Kind::Opt(&REQ_FLOAT)),
    ],
    forbid_extra: false,
};

/// The as-built (deformed) terrain of a set of cut and fill orders on the real site DEM (#264): the conserved
/// authority's own rasterise-execute delta, built on the site's remembered as-built surface (#267), so the 3D mesh
/// shows the topology transform mass-conservingly. Rows are y then x over the worked region.
#[allow(clippy::too_many_lines)] // one route, as the Python
async fn dem_asbuilt(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let (h, bytes) = split(req, st.settings.max_body).await;
    blocking(st, move |st| {
        let body = parse_body(&bytes?)?;
        let identity = require_auth(st, &h)?;
        let v = body_model(body.as_ref(), ASBUILT_REQ)?;
        // only cut and fill move terrain; goto and keep-out orders are dropped before validation
        let orders: Vec<Value> = v["orders"]
            .as_array()
            .map(|a| {
                a.iter()
                    .filter(|o| {
                        matches!(o.get("kind").and_then(Value::as_str), Some("cut" | "fill"))
                    })
                    .cloned()
                    .collect()
            })
            .unwrap_or_default();
        if orders.is_empty() {
            return Err(err(
                StatusCode::BAD_REQUEST,
                "need at least one cut or fill order to build an as-built surface",
            ));
        }
        let mut payload = Value::Object(v.clone());
        payload["orders"] = Value::Array(orders.clone());
        let bad = |e: String| err(StatusCode::BAD_REQUEST, e);
        let m = st.planning.mission(&payload).map_err(bad)?;
        let inputs = st.planning.inputs(&m).map_err(|(unconfigured, e)| {
            if unconfigured {
                err(StatusCode::SERVICE_UNAVAILABLE, e)
            } else {
                bad(e)
            }
        })?;
        let site = v["site"].as_str().unwrap_or("haworth").to_owned();
        let mut surface: Option<Surface> = None;
        if m.body == "moon" {
            bundle_404(st, &site)?;
            if let Some((dem, anchor)) = st.terrain.moon_dem(&site) {
                let mut origin = anchor;
                if let (Some(lat), Some(lon)) = (v["lat"].as_f64(), v["lon"].as_f64()) {
                    // a globe site-pick overrides the flattest anchor (absolute pixel-metres); off the tile keeps it
                    origin = st
                        .terrain
                        .latlon_to_order(&dem, (0.0, 0.0), lon, lat)
                        .unwrap_or(origin);
                }
                let view = st.terrain.current_terrain_view(&site, &dem, origin);
                surface = Some((view.heights, dem.cols, dem.rows, dem.cell_m, origin));
            }
        }
        let dem = surface
            .as_ref()
            .map(|(z, w, hh, cell, origin)| stewie_traverse::route::Dem {
                z,
                width: *w,
                height: *hh,
                cell_m: *cell,
                origin: *origin,
            });
        let d = stewie_build::record::mission_terrain_delta(
            &m,
            dem,
            &inputs.acceptance(),
            &stewie_plan::acceptance::AcceptanceParams::default(),
        )
        .map_err(bad)?;
        log(
            st,
            &h,
            &identity,
            "dem.asbuilt",
            &format!(
                "{site}: {} orders, {:.0} kg moved",
                orders.len(),
                d.mass_moved_kg
            ),
        );
        let ext = |v: &[f64], max: bool| {
            v.iter().copied().fold(
                if max {
                    f64::NEG_INFINITY
                } else {
                    f64::INFINITY
                },
                |a, b| {
                    if max { a.max(b) } else { a.min(b) }
                },
            )
        };
        Ok(axum::Json(json!({"ok": true, "site": site, "body": m.body,
            "rows": d.rows, "cols": d.cols, "cell_m": d.cell_m, "x0": d.x0, "y0": d.y0,
            "z": d.as_built.iter().map(|x| round(*x, 3)).collect::<Vec<_>>(),
            "base": d.base.iter().map(|x| round(*x, 3)).collect::<Vec<_>>(),
            "delta": d.delta.iter().map(|x| round(*x, 4)).collect::<Vec<_>>(),
            "z_min": ext(&d.as_built, false), "z_max": ext(&d.as_built, true),
            "delta_min": ext(&d.delta, false), "delta_max": ext(&d.delta, true),
            "mass_moved_kg": d.mass_moved_kg}))
        .into_response())
    })
    .await
}

/// The DEM read routes (the literal paths are matched before the preview's `{name}`).
pub fn routes() -> Router<Arc<AppState>> {
    Router::new()
        .route("/clasts/scene", get(clasts_scene))
        .route("/dem/georef", get(dem_georef))
        .route("/dem/site_xy", get(dem_site_xy))
        .route("/dem/site_lonlat", get(dem_site_lonlat))
        .route("/dem/site_meta", get(dem_site_meta))
        .route("/dem/sources", get(dem_sources))
        .route("/dem/heightfield", get(dem_heightfield))
        .route("/dem/terrain_grid", get(dem_terrain_grid))
        .route("/dem/heightfield_full", get(dem_heightfield_full_bin))
        .route("/dem/heightfield_full/meta", get(dem_heightfield_full_meta))
        .route("/dem/graticule", get(dem_graticule))
        .route("/dem/workarea.png", get(dem_workarea_png))
        .route("/dem/asbuilt", post(dem_asbuilt))
        .route(
            "/dem/heightfield_full/layer.png",
            get(dem_heightfield_full_layer),
        )
        .route("/dem/{name}", get(dem_preview))
}
