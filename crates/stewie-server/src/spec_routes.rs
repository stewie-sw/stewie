//! Small specification reads (RW-55b7a; Python `routers.schema`, `ephemeris`, `tiles`, `fleet`): the spine
//! contracts' JSON Schemas, the sun at a mission time and site from the analytic mean-motion model, the Cesium 3D
//! Tiles tilesets of the reconstruction twin, and the fleet roster from the vehicle registry.

use std::path::{Component, Path as FsPath, PathBuf};
use std::sync::Arc;

use axum::Router;
use axum::extract::{Path, Query, Request, State};
use axum::http::{HeaderValue, StatusCode, header};
use axum::response::{IntoResponse, Response};
use axum::routing::get;
use serde_json::{Map, Value, json};

use crate::admin::require_role;
use crate::app::{ApiError, AppState, Head, blocking, err, require_auth};
use crate::point::py_mod;
use crate::validate::{self, Field, Kind, Model};

const CONTRACT_SCHEMAS: &str =
    include_str!("../../stewie-contracts/fixtures/contract_schemas.json");
const SITES: &str = include_str!("../../stewie-contracts/fixtures/sites.json");
const FLEET: &str = include_str!("../../stewie-contracts/fixtures/fleet.json");

/// The JSON Schema of every spine contract (FS-08): the contract definitions, no live data. Public.
async fn contracts_schema() -> Response {
    let reg: Value = serde_json::from_str(CONTRACT_SCHEMAS).unwrap_or(Value::Null);
    axum::Json(
        json!({"ok": true, "spine_version": reg["spine_version"], "schemas": reg["schemas"]}),
    )
    .into_response()
}

/// The lunar spin axis against the ecliptic normal [deg], the lunar day and the sub-solar latitude's period [s]
/// (Python `stewie.specs.solar`).
const LUNAR_OBLIQUITY_DEG: f64 = 1.54;
const SYNODIC_MONTH_S: f64 = 29.530_589 * 86400.0;
const SIDEREAL_MONTH_S: f64 = 27.321_661 * 86400.0;

/// The sun's azimuth (from local north, eastward) and elevation [deg] at a site by the analytic mean-motion model
/// (Python `solar.sun_az_el` with its defaults: sub-solar longitude 0 at t = 0, season phase 0.7 rad), the
/// kernel-free fallback whose accuracy the SPICE path reports.
#[must_use]
pub fn analytic_sun_az_el(lat_deg: f64, t_s: f64, lon_deg: f64) -> (f64, f64) {
    let delta_deg =
        LUNAR_OBLIQUITY_DEG * (2.0 * std::f64::consts::PI * t_s / SIDEREAL_MONTH_S + 0.7).sin();
    let sun_lon = py_mod(0.0 - 360.0 * t_s / SYNODIC_MONTH_S, 360.0);
    let (phi, delta) = (lat_deg.to_radians(), delta_deg.to_radians());
    let h = py_mod(lon_deg - sun_lon, 360.0).to_radians();
    let sin_el = phi.sin() * delta.sin() + phi.cos() * delta.cos() * h.cos();
    let el = sin_el.clamp(-1.0, 1.0).asin().to_degrees();
    let az = (-delta.cos() * h.sin())
        .atan2(phi.cos() * delta.sin() - phi.sin() * delta.cos() * h.cos())
        .to_degrees();
    (py_mod(az, 360.0), el)
}

/// The mission clock's epoch (Python `solar.MISSION_EPOCH_UTC`): mission time 0.
const MISSION_EPOCH_UTC: &str = "2026-11-15T00:00:00Z";
/// The sphere the site sits on [m] (Python `sun_az_el_spice`'s 1737.4 km).
const MOON_SPHERE_M: f64 = 1_737_400.0;

/// The sun's azimuth and elevation [deg] at a site and mission time, and where they came from: the bundled DE440
/// ephemeris (the SPICE solution the Python's dispatcher prefers, apparent from the site on the 1737.4 km sphere),
/// or the analytic mean-motion model outside the ephemeris' span.
#[must_use]
pub fn sun_az_el(lat_deg: f64, t_s: f64, lon_deg: f64) -> (f64, f64, &'static str) {
    static EPH: std::sync::OnceLock<Option<lunar_ephem::Ephemeris>> = std::sync::OnceLock::new();
    let eph = EPH.get_or_init(|| lunar_ephem::Ephemeris::bundled().ok());
    let de440 = eph.as_ref().and_then(|e| {
        let utc = lunar_ephem::Utc::parse_iso8601(MISSION_EPOCH_UTC).ok()?;
        let site = lunar_frames::LatLon { lat_deg, lon_deg };
        let sphere = lunar_frames::Sphere::new(MOON_SPHERE_M).ok()?;
        let v = e
            .apparent_from(
                lunar_ephem::Body::Sun,
                e.tdb(&utc) + t_s,
                lunar_frames::body_fixed(sphere, site, 0.0),
            )
            .ok()?;
        let a = lunar_ephem::az_el(v, site);
        Some((py_mod(a.az_deg, 360.0), a.el_deg, "de440"))
    });
    de440.unwrap_or_else(|| {
        let (az, el) = analytic_sun_az_el(lat_deg, t_s, lon_deg);
        (az, el, "analytic")
    })
}

/// A site's (lat, lon) for solar geometry (Python `sites.site_latlon`): an ad-hoc `adhoc_<lat*1000>_<lon*1000>`
/// id carries its own; another name is the registry's, Haworth when unknown.
///
/// # Errors
/// A malformed ad-hoc id.
#[allow(clippy::cast_precision_loss)] // thousandths of a degree
pub fn site_latlon(name: &str) -> Result<(f64, f64), String> {
    if let Some(rest) = name.strip_prefix("adhoc_") {
        let parts: Vec<&str> = rest.split('_').collect();
        let parse = |s: &str| {
            s.trim()
                .parse::<i64>()
                .map_err(|_| format!("malformed ad-hoc site id: '{name}'"))
        };
        if parts.len() != 2 {
            return Err(format!("malformed ad-hoc site id: '{name}'"));
        }
        return Ok((
            parse(parts[0])? as f64 / 1000.0,
            parse(parts[1])? as f64 / 1000.0,
        ));
    }
    let sites: Value = serde_json::from_str(SITES).map_err(|e| e.to_string())?;
    let s = if sites.get(name).is_some() {
        &sites[name]
    } else {
        &sites["haworth"]
    };
    Ok((
        s["lat_deg"].as_f64().unwrap_or(f64::NAN),
        s["lon_deg"].as_f64().unwrap_or(f64::NAN),
    ))
}

const ANY_FLOAT: Kind = Kind::Float {
    gt: None,
    ge: None,
    le: None,
    default: Some(0.0),
};
const EPHEMERIS_Q: Model = Model {
    fields: &[
        Field("mission_t_s", ANY_FLOAT),
        Field(
            "lat_deg",
            Kind::Float {
                gt: None,
                ge: Some((-90.0, "-90")),
                le: Some((90.0, "90")),
                default: Some(-87.45),
            },
        ),
        Field(
            "lon_deg",
            Kind::Float {
                gt: None,
                ge: Some((-360.0, "-360")),
                le: Some((360.0, "360")),
                default: Some(0.0),
            },
        ),
        Field(
            "site",
            Kind::Str {
                min: 0,
                max: 64,
                nullable: true,
                default: None,
            },
        ),
    ],
    forbid_extra: false,
};

/// The query's named values validated as Pydantic does (the last of a repeated key wins), read raw.
pub(crate) fn query(q: &[(String, String)], model: Model) -> Result<Map<String, Value>, ApiError> {
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

fn num(raw: &Map<String, Value>, k: &str, default: f64) -> f64 {
    raw.get(k)
        .and_then(|v| validate::as_float(v).ok())
        .unwrap_or(default)
}

/// The sun at a mission time and site (FS-06) as the typed `EphemerisObservation`, the azimuth convention explicit
/// and the source named (the Python labels every answer `analytic`, its SPICE ones included). A `site` overrides
/// the lat/lon. Public.
async fn ephemeris(Query(q): Query<Vec<(String, String)>>) -> Response {
    let run = || -> Result<Value, ApiError> {
        let raw = query(&q, EPHEMERIS_Q)?;
        let t = num(&raw, "mission_t_s", 0.0);
        let (mut lat, mut lon) = (num(&raw, "lat_deg", -87.45), num(&raw, "lon_deg", 0.0));
        if let Some(site) = raw
            .get("site")
            .and_then(Value::as_str)
            .filter(|s| !s.is_empty())
        {
            (lat, lon) =
                site_latlon(site).map_err(|e| err(StatusCode::INTERNAL_SERVER_ERROR, e))?;
        }
        let (az, el, source) = sun_az_el(lat, t, lon);
        Ok(json!({"ok": true, "ephemeris": {
            "schema_version": "1.0", "mission_t_s": t, "body": "moon", "site_lat_deg": lat, "site_lon_deg": lon,
            "frame": "MOON_ME", "sun_az_deg": py_mod(az, 360.0), "sun_el_deg": el.clamp(-90.0, 90.0),
            "azimuth_convention": "from_north_eastward", "uncertainty_deg": 0.0, "source": source}}))
    };
    match run() {
        Ok(v) => axum::Json(v).into_response(),
        Err(e) => e.into_response(),
    }
}

/// `path` with `.` and `..` resolved lexically (the existing prefix's symlinks resolved too, as `realpath`).
fn real_path(path: &FsPath) -> PathBuf {
    if let Ok(p) = path.canonicalize() {
        return p;
    }
    let mut out = PathBuf::new();
    for c in path.components() {
        match c {
            Component::ParentDir => {
                out.pop();
            }
            Component::CurDir => {}
            other => out.push(other),
        }
    }
    out
}

/// A Cesium 3D Tiles file of a tileset under the tiles directory; a path that escapes it is refused.
async fn tile(
    State(st): State<Arc<AppState>>,
    Path((name, asset)): Path<(String, String)>,
    req: Request,
) -> Response {
    let h = Head::of(&req);
    blocking(st, move |st| {
        require_auth(st, &h)?;
        let base = real_path(&st.settings.tiles_dir);
        let path = real_path(&base.join(&name).join(&asset));
        if !path.starts_with(&base) || path == base {
            return Err(err(StatusCode::BAD_REQUEST, "bad tile path"));
        }
        let bytes = std::fs::read(&path)
            .ok()
            .filter(|_| path.is_file())
            .ok_or_else(|| err(StatusCode::NOT_FOUND, format!("no tile {name}/{asset}")))?;
        let ct = match FsPath::new(&asset)
            .extension()
            .and_then(|e| e.to_str())
            .map(str::to_lowercase)
            .as_deref()
        {
            Some("json") => "application/json",
            Some("glb") => "model/gltf-binary",
            _ => "application/octet-stream",
        };
        let mut r = bytes.into_response();
        r.headers_mut()
            .insert(header::CONTENT_TYPE, HeaderValue::from_static(ct));
        Ok(r)
    })
    .await
}

/// The fleet roster (FS-03): the vehicle registry in its own order, each with its onboard power sources; the live
/// per-plan allocation comes from `/plan`. Operator and above.
#[allow(clippy::cast_possible_truncation)] // the registry's wheel count, a small whole number
async fn fleet(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let h = Head::of(&req);
    blocking(st, move |st| {
        require_role(st, &h, "operator")?;
        let reg: Value = serde_json::from_str(FLEET).map_err(|e| err(StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;
        let f = |v: &Value| json!(v.as_f64().unwrap_or(0.0));
        let rows: Vec<Value> = reg["vehicle_order"]
            .as_array()
            .map(Vec::as_slice)
            .unwrap_or_default()
            .iter()
            .filter_map(Value::as_str)
            .map(|id| {
                let v = &reg["vehicles"][id];
                let powers: Vec<Value> = v["onboard_power"]
                    .as_array()
                    .map(Vec::as_slice)
                    .unwrap_or_default()
                    .iter()
                    .filter_map(Value::as_str)
                    .map(|pid| {
                        let ps = &reg["power_sources"][pid];
                        if ps.is_object() {
                            json!({"id": pid, "label": ps["label"], "kind": ps["kind"], "capacity_j": f(&ps["capacity_j"])})
                        } else {
                            json!({"id": pid, "label": pid, "kind": "unknown", "capacity_j": 0.0})
                        }
                    })
                    .collect();
                json!({"id": id, "label": v["label"], "dry_mass_kg": f(&v["dry_mass_kg"]),
                       "n_wheels": v["n_wheels"].as_f64().map_or(0, |n| n as i64),
                       "drum_capacity_kg": f(&v["drum_capacity_kg"]), "drive_power_w": f(&v["drive_power_w"]),
                       "dig_energy_j_per_kg": f(&v["dig_energy_j_per_kg"]),
                       "can_dig": v["dig_energy_j_per_kg"].as_f64().unwrap_or(0.0) > 0.0,
                       "capabilities": v["capabilities"], "onboard_power": powers,
                       "ui_visible": v["ui_visible"].as_bool().unwrap_or(false), "provenance": v["provenance"]})
            })
            .collect();
        let visible = rows.iter().filter(|r| r["ui_visible"] == true).count();
        Ok(axum::Json(json!({"ok": true, "count": rows.len(), "ui_visible_count": visible, "vehicles": rows,
            "default_vehicle": reg["default_vehicle"],
            "live_allocation_source": "plan.totals.vehicles_detail + makespan_s + vehicle_conflicts",
            "note": "Roster is the real vehicle registry (specs/vehicles.py). Per-vehicle allocation, makespan, \
                     and space-time conflicts are a property of a planned mission and are read from the last \
                     /plan result, not stored server-side."}))
        .into_response())
    })
    .await
}

const POSTURES: &str = include_str!("../../../stewie/physics/data/ipex_postures.json");
const RASTER_DEFS: &str = include_str!("../../stewie-contracts/fixtures/raster_defs.json");

/// The posture kinematics' drum-arm reach (pivot to drum centre), wheel radius and pivot span [m] (Python
/// `posture_kinematics`, from the sidecar rig and `ipex_specs`).
const FK_ARM_LENGTH_M: f64 = 0.388_245;
const FK_WHEEL_RADIUS_M: f64 = 0.1524;
const FK_ARM_SPAN_M: f64 = 0.40;
/// An authored lift that contradicts the computed one by more than this is a stale second source [m].
const FK_AUTHORITY_TOL_M: f64 = 0.02;
/// The 8 LAC cameras' mounts in the body frame (fwd, up, lat) [m], in the rig's order (`camera_rig.gd`).
const CAMERA_MOUNTS: [(&str, [f64; 3]); 8] = [
    ("front_left", [0.30, -0.10, 0.035]),
    ("front_right", [0.30, -0.10, -0.035]),
    ("rear_left", [-0.30, -0.10, 0.035]),
    ("rear_right", [-0.30, -0.10, -0.035]),
    ("left_mono", [0.0, -0.05, 0.285]),
    ("right_mono", [0.0, -0.05, -0.285]),
    ("drum_front_cam", [0.10, 0.18, 0.0]),
    ("drum_back_cam", [-0.10, 0.18, 0.0]),
];

/// The fore and aft support heights: each end rides on the higher of its planted arm's drop and the wheel radius.
fn support_heights(front_pitch: f64, back_pitch: f64) -> (f64, f64) {
    let drop = |p: f64| FK_ARM_LENGTH_M * 0.0_f64.max(-p).sin();
    (
        drop(front_pitch).max(FK_WHEEL_RADIUS_M),
        drop(back_pitch).max(FK_WHEEL_RADIUS_M),
    )
}

/// `base_link`'s height above the ground and the body pitch the arms induce.
fn base_link(front_pitch: f64, back_pitch: f64) -> (f64, f64) {
    let (f, b) = support_heights(front_pitch, back_pitch);
    (0.5 * (f + b), (f - b).atan2(FK_ARM_SPAN_M))
}

/// One posture of the morphology registry, its lift computed from the arm angles.
struct Posture {
    front: f64,
    back: f64,
    lift: f64,
    stability: Value,
    provenance: Value,
}

/// The postures, by name (Python `postures.load_postures`): an authored lift that contradicts the FK is refused.
fn postures() -> Result<std::collections::BTreeMap<String, Posture>, String> {
    let doc: Value = serde_json::from_str(POSTURES).map_err(|e| e.to_string())?;
    let mut out = std::collections::BTreeMap::new();
    for (name, p) in doc["postures"].as_object().ok_or("no postures")? {
        let (front, back) = (
            p["arm_front_pitch_rad"]
                .as_f64()
                .ok_or(format!("posture {name}: arm_front_pitch_rad"))?,
            p["arm_back_pitch_rad"]
                .as_f64()
                .ok_or(format!("posture {name}: arm_back_pitch_rad"))?,
        );
        let lift = base_link(front, back).0 - FK_WHEEL_RADIUS_M;
        for k in ["chassis_lift_m", "camera_vantage_m"] {
            if let Some(v) = p[k]
                .as_f64()
                .filter(|v| (v - lift).abs() > FK_AUTHORITY_TOL_M)
            {
                return Err(format!(
                    "posture {name}: authored {k}={v} contradicts the FK-computed {lift:.3} m"
                ));
            }
        }
        out.insert(
            name.clone(),
            Posture {
                front,
                back,
                lift,
                stability: p["stability"].clone(),
                provenance: p["provenance"].clone(),
            },
        );
    }
    Ok(out)
}

const SOLAR_Q: Model = Model {
    fields: &[
        Field("mission_t_s", ANY_FLOAT),
        Field(
            "lat_deg",
            Kind::Float {
                gt: None,
                ge: Some((-90.0, "-90")),
                le: Some((90.0, "90")),
                default: Some(-87.45),
            },
        ),
        Field(
            "lon_deg",
            Kind::Float {
                gt: None,
                ge: Some((-360.0, "-360")),
                le: Some((360.0, "360")),
                default: Some(0.0),
            },
        ),
        Field(
            "posture",
            Kind::Str {
                min: 0,
                max: 64,
                nullable: false,
                default: Some("TRANSIT"),
            },
        ),
        Field("leds_on", Kind::Bool { default: false }),
        Field(
            "site",
            Kind::Str {
                min: 0,
                max: 64,
                nullable: true,
                default: None,
            },
        ),
    ],
    forbid_extra: false,
};

/// The Solar work area's one payload (PO-12; Python `solar_view.solar_view`): the sun vector, the sun-group raster
/// layers, the 8 cameras' heights for the arm posture, the LED state, the posture, and the SN-02 shadow-evidence
/// gate (idle: the route supplies no cast-shadow mask). Public.
#[allow(clippy::too_many_lines)] // one payload, as the Python
async fn solar(Query(q): Query<Vec<(String, String)>>) -> Response {
    let run = || -> Result<Value, ApiError> {
        let raw = query(&q, SOLAR_Q)?;
        let t = num(&raw, "mission_t_s", 0.0);
        let (mut lat, mut lon) = (num(&raw, "lat_deg", -87.45), num(&raw, "lon_deg", 0.0));
        if let Some(site) = raw
            .get("site")
            .and_then(Value::as_str)
            .filter(|s| !s.is_empty())
        {
            (lat, lon) =
                site_latlon(site).map_err(|e| err(StatusCode::INTERNAL_SERVER_ERROR, e))?;
        }
        let name = raw
            .get("posture")
            .and_then(Value::as_str)
            .unwrap_or("TRANSIT")
            .to_owned();
        let leds = raw
            .get("leds_on")
            .and_then(validate::as_bool)
            .unwrap_or(false);
        let ps = postures().map_err(|e| err(StatusCode::INTERNAL_SERVER_ERROR, e))?;
        let Some(p) = ps.get(&name) else {
            let known: Vec<String> = ps.keys().map(|k| crate::operators::py_repr(k)).collect();
            let msg = format!(
                "unknown posture {}; known: [{}]",
                crate::operators::py_repr(&name),
                known.join(", ")
            );
            return Err(err(
                StatusCode::BAD_REQUEST,
                format!("unknown posture: {}", crate::operators::py_repr(&msg)),
            ));
        };
        let (az, el, _) = sun_az_el(lat, t, lon);
        let (az, el) = (py_mod(az, 360.0), el.clamp(-90.0, 90.0));
        let r = stewie_twin::numpy::round;
        let defs: Value = serde_json::from_str(RASTER_DEFS)
            .map_err(|e| err(StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;
        let layers: Vec<Value> = defs["raster_defs"]
            .as_array()
            .map(Vec::as_slice)
            .unwrap_or_default()
            .iter()
            .filter(|d| d["group"] == "sun" && matches!(d["key"].as_str(), Some("illumination" | "incidence" | "psr")))
            .map(|d| json!({"key": d["key"], "name": d["name"],
                            "raster_route": format!("/layers/raster/{}.png", d["key"].as_str().unwrap_or(""))}))
            .collect();
        let (base, pitch) = base_link(p.front, p.back);
        let cameras: Vec<Value> = CAMERA_MOUNTS
            .iter()
            .map(|(cam, [fwd, up, lat_off])| {
                let world_up = fwd * pitch.sin()
                    + (up * 0.0_f64.cos() - lat_off * 0.0_f64.sin()) * pitch.cos();
                json!({"name": cam, "world_height_m": r(base + world_up, 4), "active": true})
            })
            .collect();
        Ok(json!({"ok": true, "solar": {
            "sun_vector": {"sun_az_deg": r(az, 4), "sun_el_deg": r(el, 4),
                           "anti_solar_az_deg": r(py_mod(az + 180.0, 360.0), 4),
                           "azimuth_convention": "from_north_eastward", "mission_t_s": t,
                           "site_lat_deg": lat, "site_lon_deg": lon, "lit": el > 0.0},
            "illumination_layers": layers,
            "cameras": cameras,
            "leds": {"on": leds, "note": if leds { "illuminators on: shadows are illuminator-cast, not solar" }
                                         else { "illuminators off: cast shadows are solar (usable as yaw evidence)" }},
            "arm_posture": {"name": name, "arm_front_pitch_rad": r(p.front, 6), "arm_back_pitch_rad": r(p.back, 6),
                            "chassis_lift_m": r(p.lift, 4), "stability": p.stability, "provenance": p.provenance,
                            "available": ps.keys().collect::<Vec<_>>()},
            "shadow_evidence": {"has_evidence": false, "accepted": null,
                "reason": "no cast-shadow mask supplied: the SN-02 shadow-vector gate is idle (no evidence to accept or reject)"},
            "authority": "stewie.specs.solar_view (ephemeris + gis sun layers + camera rig + posture + SN-02 gate)"}}))
    };
    match run() {
        Ok(v) => axum::Json(v).into_response(),
        Err(e) => e.into_response(),
    }
}

/// The specification read routes.
pub fn routes() -> Router<Arc<AppState>> {
    Router::new()
        .route("/contracts/schema", get(contracts_schema))
        .route("/ephemeris", get(ephemeris))
        .route("/tiles/{name}/{*asset}", get(tile))
        .route("/fleet", get(fleet))
        .route("/solar", get(solar))
}

#[cfg(test)]
mod tests {
    use super::analytic_sun_az_el;

    #[test]
    fn the_analytic_sun_is_the_pythons_mean_motion_model() {
        // the reference values are Python `solar._MEANMOTION(lat, t, site_lon_deg=lon)` on this tree
        for (lat, t, lon, az, el) in [
            (-87.45, 0.0, 0.0, 0.0, 1.557_904_761_653_953_2),
            (
                -89.5,
                86_400.0,
                120.0,
                227.818_320_643_208_64,
                -1.570_240_195_427_452_7,
            ),
            (
                -86.33,
                2_551_442.976,
                -25.5,
                25.505_962_213_025_71,
                1.872_863_295_033_505_3,
            ),
            (
                10.0,
                -5_000.5,
                359.0,
                169.251_432_072_303_17,
                80.818_345_212_059_71,
            ),
        ] {
            let (a, e) = analytic_sun_az_el(lat, t, lon);
            assert!(
                (a - az).abs() < 1e-9 && (e - el).abs() < 1e-9,
                "({lat}, {t}, {lon}): {a}, {e}"
            );
        }
    }
}
