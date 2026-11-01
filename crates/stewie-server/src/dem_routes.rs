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
use axum::routing::get;
use serde_json::{Map, Value, json};
use stewie_twin::numpy::round;

use crate::app::{ApiError, AppState, Head, blocking, err, require_auth};
use crate::operators::py_repr;
use crate::state::SiteDem;
use crate::validate::{self, Field, Kind, Model};

const DEM_SOURCES: &str = include_str!("../../stewie-contracts/fixtures/dem_sources.json");

fn site_of(q: &[(String, String)]) -> String {
    q.iter()
        .rev()
        .find(|(k, _)| k == "site")
        .map_or_else(|| "haworth".to_owned(), |(_, v)| v.clone())
}

/// A site's bundle, or why not: an unknown site (the Python's `KeyError`, whose text is the message's repr), or
/// a known site with no bundle (its `FileNotFoundError`, plain).
enum Missing {
    Unknown(String),
    NotImported(String),
}

fn bundle(st: &AppState, site: &str) -> Result<PathBuf, Missing> {
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

fn metadata(dir: &std::path::Path) -> Result<Value, String> {
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

const REQ_FLOAT: Kind = Kind::Float {
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
fn linspace(start: f64, stop: f64, n: usize) -> Vec<f64> {
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
        .route("/dem/{name}", get(dem_preview))
}
