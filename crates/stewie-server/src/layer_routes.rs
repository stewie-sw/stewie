//! The selectable map layers (RW-55b15; Python `routers.plan.get_layers` and `get_raster_layer`, over
//! `map_layers.layer_defs` and `gis_layers.render`): the layer list the navigation panel loads and unloads, and
//! the computed GIS overlays of a site's work area, each drawn from the real DEM and upscaled four times.

use std::sync::{Arc, LazyLock};

use axum::Router;
use axum::extract::{Path, Query, Request, State};
use axum::http::{HeaderValue, StatusCode, header};
use axum::response::{IntoResponse, Response};
use axum::routing::get;
use serde_json::{Value, json};
use stewie_twin::traffic_memory::{self, Hardening};

use crate::app::{ApiError, AppState, Head, blocking, err};
use crate::dem_routes::{Missing, bundle, quantised_sun, site_of};
use crate::operators::py_repr;
use crate::raster::{hazard_cost_rgba, layer_rgba, png_rgba, slope_rgba, traffic_rgba, upscale};
use crate::validate::{self, Field, Kind, Model};

/// The raster definitions the GIS panel lists (`gis_layers.RASTER_DEFS`).
static RASTER_DEFS: LazyLock<Value> = LazyLock::new(|| {
    serde_json::from_str(include_str!(
        "../../stewie-contracts/fixtures/raster_defs.json"
    ))
    .unwrap_or(Value::Null)
});

/// The selectable layers (Python `map_layers.LAYERS`): terrain rasters name their real DEM source; the imagery base
/// is a flat drape.
fn layer_defs() -> Vec<Value> {
    const DEM_SOURCE: &str = "lunar_dem/haworth_10km_5m";
    vec![
        json!({"id": "imagery", "name": "Imagery", "kind": "raster", "group": "base", "default": true,
               "imagery_only": true}),
        json!({"id": "dem", "name": "DEM (hillshade)", "kind": "raster", "group": "terrain", "default": true,
               "dem_source": DEM_SOURCE}),
        json!({"id": "topology", "name": "Topology (slope)", "kind": "raster", "group": "terrain", "default": false,
               "dem_source": DEM_SOURCE}),
        json!({"id": "hazard", "name": "Hazard / keep-outs", "kind": "vector", "group": "nav", "default": true}),
        json!({"id": "excavation", "name": "Excavation history", "kind": "vector", "group": "ops", "default": true}),
        json!({"id": "lander", "name": "Lander", "kind": "vector", "group": "ops", "default": true}),
    ]
}

/// The map layers and the raster overlays (public).
async fn layers() -> Response {
    let mut all = layer_defs();
    all.extend(
        RASTER_DEFS["raster_defs"]
            .as_array()
            .into_iter()
            .flatten()
            .cloned(),
    );
    axum::Json(json!({"ok": true, "layers": all})).into_response()
}

const RASTER_Q: Model = Model {
    fields: &[
        Field(
            "sun_el",
            Kind::Float {
                gt: None,
                ge: None,
                le: None,
                default: Some(6.0),
            },
        ),
        Field(
            "sun_az",
            Kind::Float {
                gt: None,
                ge: None,
                le: None,
                default: Some(90.0),
            },
        ),
        Field("mission_t_s", Kind::Opt(&crate::dem_routes::REQ_FLOAT)),
        Field(
            "vmax",
            Kind::Float {
                gt: None,
                ge: None,
                le: None,
                default: Some(30.0),
            },
        ),
        Field(
            "classes",
            Kind::Int {
                ge: i64::MIN,
                le: i64::MAX,
                default: 0,
            },
        ),
    ],
    forbid_extra: false,
};

/// One overlay of the site's work area as RGBA, its width and height, or `None` for a kind the renderer does not
/// draw (Python `gis_layers.render`).
fn render(
    st: &AppState,
    kind: &str,
    site: &str,
    (sun_az, sun_el): (f64, f64),
    (vmax, classes): (f64, usize),
) -> Result<Option<(Vec<u8>, usize, usize)>, ApiError> {
    let internal = |e: String| err(StatusCode::INTERNAL_SERVER_ERROR, e);
    let (dem, origin) = st.terrain.moon_dem(site).ok_or_else(|| {
        err(
            StatusCode::NOT_FOUND,
            format!("DEM bundle absent: no DEM for site {}", py_repr(site)),
        )
    })?;
    let (z, w, h, (r0, c0)) = crate::point::work_area(&dem, origin);
    let cell = dem.cell_m;
    if kind == "traffic" {
        // TW-11: where the rover drove and how much the traffic hardened the regolith; none yet is transparent
        let mem = traffic_memory::load_site(&st.cfg.data_dir, site)
            .map_err(|e| internal(e.to_string()))?;
        return Ok(Some(match mem {
            None => (vec![0; w * h * 4], w, h),
            Some(mem) => {
                let p = &st.planning;
                let soil = stewie_physics::soil::SoilParams::for_body(
                    &p.bodies,
                    &p.soil_base,
                    "moon",
                    false,
                )
                .map_err(|e| internal(e.to_string()))?;
                let material =
                    stewie_physics::material::MaterialModel::for_soil(&soil, &p.soil_base);
                let contact_len_m = p
                    .fleet
                    .vehicles
                    .get("ipex")
                    .map_or(0.10, |v| v.contact_len_m);
                let gravity_ms2 = p.bodies.get("moon").map_or(1.62, |b| b.g);
                let hard = Hardening {
                    soil: &soil,
                    contact_len_m,
                    material: &material,
                    gravity_ms2,
                };
                (
                    traffic_rgba(&mem.relative_density(&hard), mem.passes()),
                    mem.cols,
                    mem.rows,
                )
            }
        }));
    }
    let rgba = match kind {
        // the rock + roughness navigation cost the routing detours on (richer than the drape's slope proxy)
        "hazard" => hazard_cost_rgba(&z, w, h, cell),
        "slope" => slope_rgba(&z, w, h, cell, vmax, classes),
        "illumination" | "incidence" | "psr" => {
            #[allow(clippy::cast_precision_loss)] // tile indices
            let centre = (
                (c0 as f64 + w as f64 / 2.0) * cell,
                (r0 as f64 + h as f64 / 2.0) * cell,
            );
            // #266: the true sun azimuth re-expressed in the grid frame; off the tile, uncorrected
            let gnb = (kind != "psr")
                .then(|| {
                    st.terrain
                        .grid_north_bearing_deg(&dem, centre.0, centre.1)
                        .ok()
                })
                .flatten();
            match layer_rgba(&z, w, h, cell, kind, sun_az, sun_el, gnb) {
                Some(px) => px,
                None => return Ok(None),
            }
        }
        _ => return Ok(None),
    };
    Ok(Some((rgba, w, h)))
}

/// A computed GIS overlay of the site's work area from the real DEM (any authenticated caller, under the heavy
/// quota). A mission time puts the sun where the ephemeris has it at the site; the slope ramp's domain and
/// classes are the graduated renderer's controls.
async fn raster(
    State(st): State<Arc<AppState>>,
    Path(file): Path<String>,
    Query(q): Query<Vec<(String, String)>>,
    req: Request,
) -> Response {
    let Some(kind) = file.strip_suffix(".png").map(str::to_owned) else {
        return crate::app::no_route_for(
            &axum::http::Method::GET,
            &format!("/layers/raster/{file}"),
        );
    };
    let h = Head::of(&req);
    blocking(st, move |st| {
        st.heavy(&h)?;
        let raw = crate::spec_routes::query(&q, RASTER_Q)?;
        let site = site_of(&q);
        let num = |k: &str, d: f64| {
            raw.get(k)
                .and_then(|v| validate::as_float(v).ok())
                .unwrap_or(d)
        };
        let (mut az, mut el) = (num("sun_az", 90.0), num("sun_el", 6.0));
        if let Some(t) = raw
            .get("mission_t_s")
            .and_then(|v| validate::as_float(v).ok())
        {
            let (lat, lon) = crate::spec_routes::site_latlon(&site)
                .map_err(|e| err(StatusCode::INTERNAL_SERVER_ERROR, e))?;
            // `solar.sun_az_el` is rebound to the dispatcher: the ephemeris, else the analytic model
            (az, el, _) = crate::spec_routes::sun_az_el(lat, t, lon);
        }
        let vmax = num("vmax", 30.0);
        let vmax = if vmax.is_finite() {
            vmax.clamp(1.0, 90.0)
        } else {
            30.0
        };
        #[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)] // clamped to 0..=12
        let classes = raw
            .get("classes")
            .and_then(|v| validate::as_int(v).ok())
            .unwrap_or(0)
            .clamp(0, 12) as usize;
        bundle(st, &site).map_err(|m| match m {
            Missing::Unknown(e) => err(StatusCode::NOT_FOUND, e),
            Missing::NotImported(e) => {
                err(StatusCode::NOT_FOUND, format!("DEM bundle absent: {e}"))
            }
        })?;
        let (rgba, w, hgt) = render(st, &kind, &site, quantised_sun(az, el), (vmax, classes))?
            .ok_or_else(|| {
                err(
                    StatusCode::NOT_FOUND,
                    format!("unknown layer {}", py_repr(&kind)),
                )
            })?;
        let png = png_rgba(&upscale(&rgba, w, hgt, 4), w * 4, hgt * 4)
            .map_err(|e| err(StatusCode::INTERNAL_SERVER_ERROR, e))?;
        let mut r = png.into_response();
        r.headers_mut()
            .insert(header::CONTENT_TYPE, HeaderValue::from_static("image/png"));
        Ok(r)
    })
    .await
}

/// The map legend (public): every threshold, ramp and band read from the physics and the renderers, exported from
/// the Python's `layers_legend` (`layers_legend.json`).
async fn legend() -> Response {
    (
        [(
            header::CONTENT_TYPE,
            HeaderValue::from_static("application/json"),
        )],
        include_str!("../../stewie-contracts/fixtures/layers_legend.json"),
    )
        .into_response()
}

/// The elevation contours of a site's tile (Python `gis_layers.contour_geojson`, LY-05): isolines every `interval`
/// metres traced on the DEM strided to about `target_px` (contourpy, `stewie_server::contour::lines`), reprojected
/// to selenographic lon/lat; at most 400 levels and 200 000 vertices (`truncated` when hit).
#[allow(
    clippy::cast_precision_loss,
    clippy::cast_possible_truncation,
    clippy::cast_sign_loss
)] // grid sizes
fn contour_geojson(
    st: &AppState,
    site: &str,
    iv: f64,
    bundle: &std::path::Path,
) -> Result<Value, ApiError> {
    const MAX_LEVELS: usize = 400;
    const TARGET_PX: usize = 512;
    const MAX_VERTICES: usize = 200_000;
    let internal = |e: String| err(StatusCode::INTERNAL_SERVER_ERROR, e);
    let (dem, _) = st.terrain.moon_dem(site).ok_or_else(|| {
        err(
            StatusCode::NOT_FOUND,
            format!("DEM absent: no DEM for site {}", py_repr(site)),
        )
    })?;
    let meta = crate::dem_routes::metadata(bundle).map_err(internal)?;
    let bounds = &meta["world_bounds_m"];
    let bound = |k: &str| bounds[k].as_f64().unwrap_or(f64::NAN);
    let (x0, y0, x1, y1) = (bound("x0"), bound("y0"), bound("x1"), bound("y1"));
    let (h, w) = (dem.rows, dem.cols);
    let stride = ((h.max(w) as f64 / TARGET_PX.max(2) as f64).round_ties_even() as usize).max(1);
    let (rows, cols): (Vec<usize>, Vec<usize>) = (
        (0..h).step_by(stride).collect(),
        (0..w).step_by(stride).collect(),
    );
    let z = &dem.z;
    let zd: Vec<f64> = rows
        .iter()
        .flat_map(|&r| cols.iter().map(move |&c| z[r * w + c]))
        .collect();
    let xs = crate::dem_routes::linspace(x0, x1, cols.len());
    let ys = crate::dem_routes::linspace(y1, y0, rows.len());
    // numpy nanmin / nanmax
    let finite = zd.iter().copied().filter(|v| !v.is_nan());
    let zmin = finite.clone().fold(f64::INFINITY, f64::min);
    let zmax = finite.fold(f64::NEG_INFINITY, f64::max);
    let round = stewie_twin::numpy::round;
    let mut levels = Vec::new();
    let mut v = (zmin / iv).ceil() * iv;
    while v <= zmax && levels.len() < MAX_LEVELS {
        levels.push(round(v, 3));
        v += iv;
    }
    let proj = st.terrain.projection();
    let (mut features, mut n_vertices, mut truncated) = (Vec::new(), 0, false);
    for lev in levels {
        let mut coords = Vec::new();
        for pl in crate::contour::lines(&xs, &ys, &zd, lev).map_err(internal)? {
            if pl.len() < 2 {
                continue;
            }
            let line: Vec<Value> = pl
                .iter()
                .map(|&[x, y]| {
                    let ll = proj.inverse(x, y);
                    json!([round(ll.lon_deg, 6), round(ll.lat_deg, 6)])
                })
                .collect();
            n_vertices += line.len();
            coords.push(Value::Array(line));
            if n_vertices >= MAX_VERTICES {
                truncated = true;
                break;
            }
        }
        if !coords.is_empty() {
            features.push(
                json!({"type": "Feature", "properties": {"elevation_m": lev},
                                 "geometry": {"type": "MultiLineString", "coordinates": coords}}),
            );
        }
        if truncated {
            break;
        }
    }
    Ok(json!({
        "type": "FeatureCollection",
        "properties": {"site": site, "interval_m": iv, "levels": features.len(), "z_min_m": round(zmin, 2),
                       "z_max_m": round(zmax, 2), "vertices": n_vertices, "truncated": truncated, "crs": "OGC:CRS84",
                       "source": "LOLA DEM elevation isolines (contourpy on the real heightfield)",
                       "eligibility": "display-only (base.contours, LY-01 catalog)"},
        "features": features,
    }))
}

const CONTOURS_Q: Model = Model {
    fields: &[Field(
        "interval",
        Kind::Float {
            gt: None,
            ge: None,
            le: None,
            default: Some(50.0),
        },
    )],
    forbid_extra: false,
};

/// The site's elevation contours as `GeoJSON` (public, per-IP rate-limited like the globe drapes; display only).
async fn contours(
    State(st): State<Arc<AppState>>,
    Query(q): Query<Vec<(String, String)>>,
    req: Request,
) -> Response {
    let h = Head::of(&req);
    blocking(st, move |st| {
        st.globe_quota(&h)?;
        let raw = crate::spec_routes::query(&q, CONTOURS_Q)?;
        let site = site_of(&q);
        let iv = raw
            .get("interval")
            .and_then(|v| validate::as_float(v).ok())
            .unwrap_or(50.0);
        // a tiny interval cannot explode the trace
        let iv = if iv.is_finite() { iv } else { 50.0 }.clamp(1.0, 1000.0);
        let dir = bundle(st, &site).map_err(|m| match m {
            Missing::Unknown(e) => err(StatusCode::NOT_FOUND, e),
            Missing::NotImported(e) => err(StatusCode::NOT_FOUND, format!("DEM absent: {e}")),
        })?;
        let fc = contour_geojson(st, &site, iv, &dir)?;
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

/// The layer routes.
pub fn routes() -> Router<Arc<AppState>> {
    Router::new()
        .route("/layers", get(layers))
        .route("/layers/raster/{file}", get(raster))
        .route("/layers/legend", get(legend))
        .route("/layers/contours.geojson", get(contours))
}
