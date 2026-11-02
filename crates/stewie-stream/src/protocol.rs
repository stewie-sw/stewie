//! The browser contract of the stream (Python `stewie.stream.protocol`): the session config (the first WebSocket
//! message) and each later control frame, relayed to Godot. Validation only: no I/O.
//!
//! A message carrying JSON's non-standard `NaN`/`Infinity` literals, which Python's `json.loads` reads, is not JSON
//! here: a config so written is refused as not JSON, and a control frame so written relays nothing (D-R184).

use serde_json::{Map, Value, json};

use crate::py;

/// The real-mode default site.
pub const DEFAULT_SITE: &str = "haworth_sfs_2km_1m";
/// The default hard sun of a fresh session [deg].
pub const DEFAULT_SUN_AZ: f64 = 135.0;
pub const DEFAULT_SUN_EL: f64 = 18.0;

/// Python `float(v)` if finite, else `default`.
fn finite_or(v: Option<&Value>, default: f64) -> f64 {
    v.and_then(py::float)
        .filter(|x| x.is_finite())
        .unwrap_or(default)
}

/// [REQ:TR-03] The operator's chosen worksite section in `IAU_2015:30135` metres, refused (never coerced) when it is
/// not a finite pair; `None` lets the runtime's flattest-interior fallback run.
fn start_xy(value: Option<&Value>) -> Result<Option<[f64; 2]>, String> {
    let Some(value) = value.filter(|v| !v.is_null()) else {
        return Ok(None);
    };
    let repr = || stewie_twin::pyjson::repr(value);
    let Value::Array(items) = value else {
        return Err(format!(
            "start_xy must be a [x, y] pair in IAU_2015:30135 metres, got {}",
            repr()
        ));
    };
    if items.len() != 2 {
        return Err(format!(
            "start_xy must have exactly 2 coordinates, got {}",
            items.len()
        ));
    }
    let (Some(x), Some(y)) = (py::float(&items[0]), py::float(&items[1])) else {
        return Err(format!(
            "start_xy coordinates must be numbers, got {}",
            repr()
        ));
    };
    if !(x.is_finite() && y.is_finite()) {
        return Err(format!(
            "start_xy must be finite (no NaN/inf), got {}",
            repr()
        ));
    }
    Ok(Some([x, y]))
}

/// [REQ:TR-03] Whether the chosen section lies inside the tile's `world_bounds_m` (an out-of-tile choice is refused
/// by the caller, never clamped to an edge).
#[must_use]
pub fn start_xy_in_bounds(start: Option<[f64; 2]>, world_bounds: &Value) -> bool {
    let Some([x, y]) = start else { return true };
    let b = |k: &str| world_bounds[k].as_f64().unwrap_or(f64::NAN);
    let (x0, x1) = (b("x0").min(b("x1")), b("x0").max(b("x1")));
    let (y0, y1) = (b("y0").min(b("y1")), b("y0").max(b("y1")));
    x0 <= x && x <= x1 && y0 <= y && y <= y1
}

fn resolve_fine(value: Option<&Value>) -> Result<Value, String> {
    const BAD: &str = "fine must be native or a positive source cell size";
    match value {
        None | Some(Value::Null) => Ok(Value::Null),
        Some(Value::String(s)) if s == "native" => Ok(Value::Null),
        Some(Value::Bool(_)) => Err(BAD.to_owned()),
        Some(v) => py::float(v)
            .filter(|f| f.is_finite() && *f > 0.0)
            .map(|f| json!(f))
            .ok_or_else(|| BAD.to_owned()),
    }
}

/// The session config from the first message's text.
///
/// # Errors
/// Text that is not JSON, or a config [`parse_config`] refuses.
pub fn parse_config_text(raw: &[u8]) -> Result<Map<String, Value>, String> {
    let cfg: Value = serde_json::from_slice(raw).map_err(|e| format!("config is not JSON: {e}"))?;
    parse_config(&cfg)
}

/// The normalized session config, every field resolved: `mode`, `fine_cell_m`, `sun_az`, `sun_el`, `region_size`
/// (the mission size, 60..500 m, default 100), `site` and `start_xy`.
///
/// # Errors
/// Not an object, a mode other than `real`, a path-escaping site, a bad `fine`, or a malformed `start_xy`.
pub fn parse_config(cfg: &Value) -> Result<Map<String, Value>, String> {
    let Value::Object(cfg) = cfg else {
        return Err("config must be a JSON object".to_owned());
    };
    let mode = cfg
        .get("mode")
        .map_or_else(|| "real".to_owned(), py::str_of)
        .to_lowercase();
    if mode != "real" {
        return Err("only measured real-terrain bundles are permitted".to_owned());
    }
    let empty = Map::new();
    let sun = cfg.get("sun").and_then(Value::as_object).unwrap_or(&empty);
    let mut out = Map::new();
    out.insert("mode".into(), json!(mode));
    out.insert("fine_cell_m".into(), resolve_fine(cfg.get("fine"))?);
    out.insert(
        "sun_az".into(),
        json!(finite_or(sun.get("az"), DEFAULT_SUN_AZ)),
    );
    out.insert(
        "sun_el".into(),
        json!(finite_or(sun.get("el"), DEFAULT_SUN_EL)),
    );
    let mission = cfg.get("mission_size").or_else(|| cfg.get("region_size"));
    out.insert(
        "region_size".into(),
        json!(finite_or(mission, 100.0).clamp(60.0, 500.0)),
    );
    let site = cfg
        .get("site")
        .filter(|v| py::truthy(v))
        .map_or_else(|| DEFAULT_SITE.to_owned(), py::str_of);
    let site = site.trim();
    // a real site is a bare bundle name under samples/lunar_dem/
    if site.is_empty() || site.contains('/') || site.contains('\\') || site.starts_with('.') {
        return Err(format!(
            "real-mode site must be a bare bundle name, got {}",
            stewie_twin::pyjson::repr_str(site)
        ));
    }
    out.insert("site".into(), json!(site));
    out.insert("start_xy".into(), json!(start_xy(cfg.get("start_xy"))?));
    Ok(out)
}

/// One browser control frame, clamped into the command relayed to Godot; only present, valid keys appear, so an
/// absent field never overwrites Godot's retained state.
#[must_use]
pub fn normalize_input(raw: &[u8]) -> Map<String, Value> {
    match serde_json::from_slice::<Value>(raw) {
        Ok(Value::Object(m)) => normalize(&m),
        _ => Map::new(),
    }
}

fn clamp(v: Option<&Value>, default: f64, lo: f64, hi: f64) -> Value {
    json!(finite_or(v, default).clamp(lo, hi))
}

#[allow(clippy::cast_possible_truncation)] // a camera mode in 0..4
fn normalize(m: &Map<String, Value>) -> Map<String, Value> {
    let mut out = Map::new();
    let on = |k: &str| m.get(k).is_some_and(py::truthy);
    if m.contains_key("v") || m.contains_key("omega") {
        out.insert("v".into(), clamp(m.get("v"), 0.0, -1.0, 1.0));
        out.insert("omega".into(), clamp(m.get("omega"), 0.0, -1.0, 1.0));
    }
    for k in ["dig", "dump"] {
        if on(k) {
            out.insert(k.into(), json!(true));
        }
    }
    if m.contains_key("sun_az") {
        out.insert(
            "sun_az".into(),
            json!(py::fmod(finite_or(m.get("sun_az"), DEFAULT_SUN_AZ), 360.0)),
        );
    }
    if m.contains_key("sun_el") {
        out.insert(
            "sun_el".into(),
            clamp(m.get("sun_el"), DEFAULT_SUN_EL, -5.0, 90.0),
        );
    }
    if on("cam_next") {
        out.insert("cam_next".into(), json!(true));
    }
    if m.contains_key("cam_mode") {
        // Python int(x) % 4, taken in floats so a huge x cannot saturate
        out.insert(
            "cam_mode".into(),
            json!(py::fmod(finite_or(m.get("cam_mode"), 0.0).trunc(), 4.0) as i64),
        );
    }
    for k in ["orbit_dyaw", "orbit_dpitch", "orbit_dzoom"] {
        if m.contains_key(k) {
            out.insert(k.into(), clamp(m.get(k), 0.0, -90.0, 90.0));
        }
    }
    if m.contains_key("drum") {
        out.insert("drum".into(), clamp(m.get("drum"), 0.0, -1.0, 1.0));
    }
    for k in ["arm_front_d", "arm_back_d"] {
        if m.contains_key(k) {
            out.insert(k.into(), clamp(m.get(k), 0.0, -0.5, 0.5));
        }
    }
    if let Some(Value::Array(c)) = m.get("click_px")
        && c.len() == 2
    {
        out.insert(
            "click_px".into(),
            json!([finite_or(c.first(), 0.0), finite_or(c.get(1), 0.0)]),
        );
    }
    if let Some(t) = m.get("traverse") {
        out.insert("traverse".into(), json!(py::truthy(t)));
    }
    if on("clear_wp") {
        out.insert("clear_wp".into(), json!(true));
    }
    if let Some(Value::String(o)) = m.get("overlay") {
        out.insert("overlay".into(), json!(o));
    }
    match m.get("plan") {
        Some(Value::Bool(true)) => {
            out.insert("plan".into(), json!(true));
        }
        Some(Value::Object(pv)) => {
            if let Some(Value::Array(route)) = pv.get("route") {
                let pts: Vec<Value> = route
                    .iter()
                    .filter_map(|p| p.as_array().filter(|p| p.len() >= 2))
                    .map(|p| json!([finite_or(p.first(), 0.0), finite_or(p.get(1), 0.0)]))
                    .collect();
                if !pts.is_empty() {
                    out.insert("plan".into(), json!({"route": pts}));
                }
            }
        }
        _ => {}
    }
    out
}
