//! The mission model and its trust boundary (Python `lode.planner_model.Mission` / `mission_from_dict`, RW-33a).
//!
//! A mission is the operator's build orders on a map plus everything the planner is told about the fleet,
//! the site and the schedule. [`mission_from_value`] is the only way in: it walks the schema migration chain,
//! checks the body, the vehicle and its tools, every order (kind, the fleet's capability for it, finite
//! coordinates, positive footprint and depth or a typed footprint shape) and every optional block, and refuses
//! the first malformed field with a message naming it. Nothing physical is defaulted.
//!
//! Stricter than the Python: a number must be a JSON number (the Python's `float()` also took booleans and
//! numeric strings), and a field the Python would stringify from a list or object is refused.

use std::collections::BTreeMap;
use std::fmt;

use serde_json::{Map, Value};
use stewie_contracts::body::BodyRegistry;
use stewie_contracts::fleet::{Action, Fleet};

/// The mission wire format this build reads (an absent version is the legacy unversioned format, which is
/// field-compatible and migrates by adoption).
pub const MISSION_SCHEMA_VERSION: &str = "stewie_mission/1.0";
pub const LEGACY_MISSION_VERSION: &str = "stewie_mission/0";
/// A polygon keep-out's vertex cap (#305): routing tests every candidate cell against every vertex.
pub const MAX_KEEPOUT_VERTS: usize = 256;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MissionError(pub String);

impl fmt::Display for MissionError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for MissionError {}

fn bad<T>(m: impl Into<String>) -> Result<T, MissionError> {
    Err(MissionError(m.into()))
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OrderKind {
    Cut,
    Fill,
    Sinter,
    /// A path waypoint: a zero-mass visit, sequenced after the previous waypoint.
    Goto,
}

impl OrderKind {
    fn parse(s: &str) -> Option<Self> {
        Some(match s {
            "cut" => Self::Cut,
            "fill" => Self::Fill,
            "sinter" => Self::Sinter,
            "goto" => Self::Goto,
            _ => return None,
        })
    }

    /// The payload name.
    #[must_use]
    pub fn name(self) -> &'static str {
        match self {
            Self::Cut => "cut",
            Self::Fill => "fill",
            Self::Sinter => "sinter",
            Self::Goto => "goto",
        }
    }

    /// The fleet capability the order needs.
    #[must_use]
    pub fn capability(self) -> Option<&'static str> {
        match self {
            Self::Cut => Some("excavate"),
            Self::Fill => Some("dump"),
            Self::Sinter => Some("sinter"),
            Self::Goto => None,
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct BuildOrder {
    pub action: String,
    pub kind: OrderKind,
    pub x: f64,
    pub y: f64,
    /// [m^2]; derived from `shape` when one is given; 0 for a waypoint.
    pub footprint_m2: f64,
    /// Cut depth, fill height or sinter depth [m]; 0 for a waypoint.
    pub depth_m: f64,
    pub note: String,
    /// The typed footprint (rectangle, circle, corridor or polygon) as given, for geometry and acceptance.
    pub shape: Option<Value>,
    /// The cut material's known in-situ density [kg/m^3].
    pub insitu_density_kg_m3: Option<f64>,
}

/// A keep-out in the local order frame (the router's own type; a rectangle is normalised so `x0 <= x1`, `y0 <= y1`).
pub use stewie_traverse::costmap::Keepout;

#[derive(Debug, Clone, PartialEq)]
pub struct SharedResource {
    pub id: String,
    pub kind: String,
    pub capacity: u64,
    pub sites: Vec<(f64, f64)>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Observation {
    pub vehicle: u64,
    pub x: f64,
    pub y: f64,
    pub t_start: f64,
    pub t_end: f64,
    pub kind: String,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Mission {
    pub name: String,
    pub body: String,
    pub orders: Vec<BuildOrder>,
    pub charger: (f64, f64),
    pub charger_capacity: u64,
    pub date: Option<String>,
    pub lander: Option<(f64, f64)>,
    /// Buffer over the bare return-to-lander energy; `None` leaves it to the planner's required parameter.
    pub return_buffer_frac: Option<f64>,
    /// `(before, after)` order actions; consecutive waypoints are chained automatically.
    pub precedence: Vec<(String, String)>,
    pub vehicle: String,
    pub tools: Vec<String>,
    /// Regolith model override (a body key); empty means the body's own.
    pub soil: String,
    pub keepouts: Vec<Keepout>,
    pub objective_constraints: BTreeMap<String, f64>,
    /// Action class (`recharge`, `work`, `drive`) to its allowed `[open, close]` mission-clock intervals.
    pub mission_windows: BTreeMap<String, Vec<(f64, f64)>>,
    pub shared_resources: Vec<SharedResource>,
    pub observations: Vec<Observation>,
    pub dig_energy_factor: Option<f64>,
    pub accept_flatness_tol_m: Option<f64>,
    pub physics_backend_id: String,
}

/// The physics backends a mission may select. The Rust physics crate is the conserved Tier-2 authority; it keeps the
/// Python's wire name so existing missions validate unchanged.
pub const SELECTABLE_BACKENDS: [&str; 1] = ["tier2_numpy"];

/// What the boundary checks names against: the body registry's keys and the fleet's capabilities.
#[derive(Debug, Clone, PartialEq)]
pub struct Registries {
    /// Body registry keys (lower case).
    pub bodies: Vec<String>,
    /// Vehicle key to its base capabilities.
    pub vehicles: BTreeMap<String, Vec<String>>,
    /// Tool key to the capability it grants.
    pub tools: BTreeMap<String, String>,
    pub default_vehicle: String,
    pub backends: Vec<String>,
}

impl Registries {
    /// From the body registry and the fleet contract.
    #[must_use]
    pub fn new(bodies: &BodyRegistry, fleet: &Fleet) -> Self {
        let action = |a: &Action| {
            serde_json::to_value(a)
                .ok()
                .and_then(|v| v.as_str().map(str::to_owned))
                .unwrap_or_default()
        };
        Self {
            bodies: bodies.keys().cloned().collect(),
            vehicles: fleet
                .vehicles
                .iter()
                .map(|(k, v)| (k.clone(), v.capabilities.iter().map(action).collect()))
                .collect(),
            tools: fleet
                .tools
                .iter()
                .map(|(k, t)| (k.clone(), action(&t.capability)))
                .collect(),
            default_vehicle: fleet.default_vehicle.as_str().to_owned(),
            backends: SELECTABLE_BACKENDS
                .iter()
                .map(|s| (*s).to_owned())
                .collect(),
        }
    }
}

use stewie_twin::pyjson::{repr, repr_list, repr_str};

/// A float as Python's `repr` (the Python formats the values it converted with `float()`).
fn fr(x: f64) -> String {
    stewie_twin::pyjson::float_repr(x).unwrap_or_else(|_| x.to_string())
}

/// Python's `sorted(registry)`, as its repr.
fn sorted<S: AsRef<str>>(keys: &[S]) -> String {
    let mut k: Vec<&str> = keys.iter().map(AsRef::as_ref).collect();
    k.sort_unstable();
    repr_list(&k)
}

/// A finite JSON number.
fn finite(v: &Value, what: &str) -> Result<f64, MissionError> {
    match v.as_f64() {
        Some(x) if x.is_finite() => Ok(x),
        _ => bad(format!("{what}: must be a finite number (got {})", repr(v))),
    }
}

fn positive(v: &Value, what: &str) -> Result<f64, MissionError> {
    let x = finite(v, what)?;
    if x > 0.0 {
        Ok(x)
    } else {
        bad(format!("{what}: must be > 0 (got {})", repr(v)))
    }
}

/// Python `str()` of a scalar: a string as is, an integer in decimal, a float as `repr`.
fn text(v: &Value, what: &str) -> Result<String, MissionError> {
    match v {
        Value::String(s) => Ok(s.clone()),
        Value::Number(n) if n.is_i64() || n.is_u64() => Ok(n.to_string()),
        Value::Number(n) => n
            .as_f64()
            .and_then(|x| stewie_twin::pyjson::float_repr(x).ok())
            .ok_or_else(|| MissionError(format!("{what}: not representable"))),
        _ => bad(format!(
            "{what}: must be a string or a number (got {})",
            repr(v)
        )),
    }
}

fn xy(v: &Value, what: &str) -> Result<(f64, f64), MissionError> {
    match v.as_array() {
        Some(a) if a.len() == 2 => Ok((
            finite(&a[0], &format!("{what} x"))?,
            finite(&a[1], &format!("{what} y"))?,
        )),
        _ => bad(format!(
            "{what} must be a 2-element [x, y]; got {}",
            repr(v)
        )),
    }
}

/// A registry lookup as the Python's: the exact key, else the trimmed lower-case key.
fn lookup<'m, T>(map: &'m BTreeMap<String, T>, name: &str) -> Option<&'m T> {
    map.get(name)
        .or_else(|| map.get(&name.trim().to_lowercase()))
}

fn truthy(v: Option<&Value>) -> bool {
    match v {
        None | Some(Value::Null) => false,
        Some(Value::Bool(b)) => *b,
        Some(Value::Number(n)) => n.as_f64().is_some_and(|x| x != 0.0),
        Some(Value::String(s)) => !s.is_empty(),
        Some(Value::Array(a)) => !a.is_empty(),
        Some(Value::Object(o)) => !o.is_empty(),
    }
}

/// Planar area [m^2] of a typed footprint: rectangle `w x h`, circle `r`, corridor `length x width`, polygon
/// `vertices` (shoelace). Orientation is carried but does not change the area.
///
/// # Errors
/// An unknown kind, a missing or non-positive dimension, or a degenerate polygon.
pub fn footprint_shape_area_m2(shape: &Map<String, Value>) -> Result<f64, MissionError> {
    let kind = shape
        .get("kind")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_lowercase();
    let dim = |k: &str| -> Result<f64, MissionError> {
        finite(
            shape.get(k).unwrap_or(&Value::Null),
            &format!("{kind} footprint {k}"),
        )
    };
    match kind.as_str() {
        "rectangle" => {
            let (w, h) = (dim("w")?, dim("h")?);
            if w <= 0.0 || h <= 0.0 {
                return bad(format!(
                    "rectangle footprint needs w,h > 0 (got {},{})",
                    fr(w),
                    fr(h)
                ));
            }
            Ok(w * h)
        }
        "circle" => {
            let r = dim("r")?;
            if r <= 0.0 {
                return bad(format!("circle footprint needs r > 0 (got {})", fr(r)));
            }
            Ok(std::f64::consts::PI * r * r)
        }
        "corridor" => {
            let (l, w) = (dim("length")?, dim("width")?);
            if l <= 0.0 || w <= 0.0 {
                return bad(format!(
                    "corridor footprint needs length,width > 0 (got {},{})",
                    fr(l),
                    fr(w)
                ));
            }
            Ok(l * w)
        }
        "polygon" => {
            let verts: Vec<(f64, f64)> = shape
                .get("vertices")
                .and_then(Value::as_array)
                .ok_or_else(|| MissionError("polygon footprint needs 'vertices'".into()))?
                .iter()
                .map(|p| xy(p, "polygon vertex"))
                .collect::<Result<_, _>>()?;
            if verts.len() < 3 {
                return bad(format!(
                    "polygon footprint needs >= 3 vertices (got {})",
                    verts.len()
                ));
            }
            let n = verts.len();
            let twice: f64 = (0..n)
                .map(|i| verts[i].0 * verts[(i + 1) % n].1 - verts[(i + 1) % n].0 * verts[i].1)
                .sum();
            let area = twice.abs() * 0.5;
            if area <= 0.0 {
                return bad("polygon footprint is degenerate (zero area)");
            }
            Ok(area)
        }
        k => bad(format!(
            "unknown footprint shape kind {} (use rectangle|circle|corridor|polygon)",
            repr_str(k)
        )),
    }
}

fn parse_order(
    idx: usize,
    raw: &Value,
    caps: &[String],
    vehicle: &str,
    tools: &[String],
) -> Result<BuildOrder, MissionError> {
    let Some(o) = raw.as_object() else {
        return bad(format!("order {idx} must be an object"));
    };
    let goto = o.get("kind").and_then(Value::as_str) == Some("goto");
    let has_shape = truthy(o.get("shape"));
    let required: &[&str] = if goto {
        &["action", "kind", "x", "y"]
    } else if has_shape {
        &["action", "kind", "x", "y", "depth_m"]
    } else {
        &["action", "kind", "x", "y", "footprint_m2", "depth_m"]
    };
    let missing: Vec<&str> = required
        .iter()
        .copied()
        .filter(|k| !o.contains_key(*k))
        .collect();
    if !missing.is_empty() {
        return bad(format!(
            "order {idx} missing field(s): {}",
            repr_list(&missing)
        ));
    }
    let kind_txt = o["kind"].as_str().unwrap_or("");
    let Some(kind) = OrderKind::parse(kind_txt) else {
        return bad(format!(
            "order {idx} kind {} not in ('cut', 'fill', 'sinter', 'goto')",
            repr(&o["kind"])
        ));
    };
    if let Some(need) = kind.capability()
        && !caps.iter().any(|c| c == need)
    {
        if kind == OrderKind::Sinter {
            return bad(format!(
                "order {idx}: sinter is GATED OFF -- no vehicle in the fleet carries a sinter tool \
                 ({} is a drum excavator; sinter is a separate Tool to mount).",
                repr_str(vehicle)
            ));
        }
        return bad(format!(
            "order {idx}: kind {} needs the {} capability, which the fleet ({} + tools {}) lacks.",
            repr_str(kind_txt),
            repr_str(need),
            repr_str(vehicle),
            repr_list(tools)
        ));
    }
    let x = finite(&o["x"], &format!("order {idx} x"))?;
    let y = finite(&o["y"], &format!("order {idx} y"))?;
    let (footprint_m2, depth_m, shape) = if goto {
        (0.0, 0.0, None)
    } else {
        let footprint = if has_shape {
            let Some(s) = o["shape"].as_object() else {
                return bad(format!("order {idx} shape must be an object"));
            };
            let area = footprint_shape_area_m2(s)?;
            positive(
                &Value::from(area),
                &format!("order {idx} footprint shape area"),
            )?
        } else {
            positive(&o["footprint_m2"], &format!("order {idx} footprint_m2"))?
        };
        let depth = positive(&o["depth_m"], &format!("order {idx} depth_m"))?;
        (
            footprint,
            depth,
            o.get("shape").filter(|_| has_shape).cloned(),
        )
    };
    let insitu = match o.get("insitu_density_kg_m3") {
        None | Some(Value::Null) => None,
        Some(v) => Some(positive(v, &format!("order {idx} insitu_density_kg_m3"))?),
    };
    Ok(BuildOrder {
        action: text(&o["action"], &format!("order {idx} action"))?,
        kind,
        x,
        y,
        footprint_m2,
        depth_m,
        note: o
            .get("note")
            .map(|n| text(n, &format!("order {idx} note")))
            .transpose()?
            .unwrap_or_default(),
        shape,
        insitu_density_kg_m3: insitu,
    })
}

fn parse_precedence(
    p: &Map<String, Value>,
    orders: &[BuildOrder],
) -> Result<Vec<(String, String)>, MissionError> {
    let gotos: Vec<&str> = orders
        .iter()
        .filter(|o| o.kind == OrderKind::Goto)
        .map(|o| o.action.as_str())
        .collect();
    let user = match p.get("precedence") {
        None | Some(Value::Null) => Vec::new(),
        Some(Value::Array(a)) => a.clone(),
        Some(v) => {
            return bad(format!(
                "precedence must be a list of [before_action, after_action] (got {})",
                repr(v)
            ));
        }
    };
    let actions: Vec<&str> = orders.iter().map(|o| o.action.as_str()).collect();
    let mut pairs = Vec::new();
    for e in &user {
        let (b, a) = match e.as_array() {
            Some(pa) if pa.len() == 2 => (text(&pa[0], "precedence")?, text(&pa[1], "precedence")?),
            _ => {
                return bad(format!(
                    "precedence entry {} must be [before_action, after_action]",
                    repr(e)
                ));
            }
        };
        if !actions.contains(&b.as_str()) || !actions.contains(&a.as_str()) {
            return bad(format!(
                "precedence {}->{} references an unknown order action",
                repr_str(&b),
                repr_str(&a)
            ));
        }
        pairs.push((b, a));
    }
    pairs.extend(gotos.windows(2).map(|w| (w[0].to_owned(), w[1].to_owned())));
    Ok(pairs)
}

fn parse_keepouts(v: &Value) -> Result<Vec<Keepout>, MissionError> {
    let Some(list) = v.as_array() else {
        return bad("'keepouts' must be a list of {x,y,r} circles or {x0,y0,x1,y1} rectangles");
    };
    let mut out = Vec::new();
    for (j, k) in list.iter().enumerate() {
        let Some(k) = k.as_object() else {
            return bad(format!("keepout {j} must be an object"));
        };
        let has = |f: &[&str]| f.iter().all(|x| k.contains_key(*x));
        if let Some(pts) = k.get("points").and_then(Value::as_array) {
            if !(3..=MAX_KEEPOUT_VERTS).contains(&pts.len()) {
                return bad(format!(
                    "keepout {j} polygon needs 3..{MAX_KEEPOUT_VERTS} vertices (got {})",
                    pts.len()
                ));
            }
            out.push(Keepout::Polygon(
                pts.iter()
                    .map(|p| xy(p, &format!("keepout {j} vertex")))
                    .collect::<Result<_, _>>()?,
            ));
        } else if has(&["x0", "y0", "x1", "y1"]) {
            let c = |f: &str| finite(&k[f], &format!("keepout {j} {f}"));
            let (x0, y0, x1, y1) = (c("x0")?, c("y0")?, c("x1")?, c("y1")?);
            out.push(Keepout::Rect {
                x0: x0.min(x1),
                y0: y0.min(y1),
                x1: x0.max(x1),
                y1: y0.max(y1),
            });
        } else if has(&["x", "y", "r"]) {
            out.push(Keepout::Circle {
                x: finite(&k["x"], &format!("keepout {j} x"))?,
                y: finite(&k["y"], &format!("keepout {j} y"))?,
                r: positive(&k["r"], &format!("keepout {j} r"))?,
            });
        } else {
            return bad(format!(
                "keepout {j} must be {{x,y,r}} (circle), {{x0,y0,x1,y1}} (rectangle), or {{points}} (polygon)"
            ));
        }
    }
    Ok(out)
}

/// The objective-constraint budgets the sequencer understands, plus the risk weight.
pub const CONSTRAINT_KEYS: [&str; 5] = [
    "max_charges",
    "max_distance_m",
    "max_energy_J",
    "max_time_s",
    "risk_weight",
];

fn parse_constraints(v: &Value) -> Result<BTreeMap<String, f64>, MissionError> {
    let Some(oc) = v.as_object() else {
        return bad("'objective_constraints' must be an object of {budget: value}");
    };
    let mut out = BTreeMap::new();
    for (k, val) in oc {
        if !CONSTRAINT_KEYS.contains(&k.as_str()) {
            return bad(format!(
                "unknown objective constraint {}; allowed: {}",
                repr_str(k),
                repr_list(&CONSTRAINT_KEYS)
            ));
        }
        let x = finite(val, &format!("objective_constraints[{k}]"))?;
        if x < 0.0 {
            return bad(format!(
                "objective constraint {} must be >= 0 (got {})",
                repr_str(k),
                fr(x)
            ));
        }
        out.insert(k.clone(), x);
    }
    Ok(out)
}

fn parse_windows(v: &Value) -> Result<BTreeMap<String, Vec<(f64, f64)>>, MissionError> {
    let Some(mw) = v.as_object() else {
        return bad("'mission_windows' must be an object of {class: [[open_s, close_s], ...]}");
    };
    let mut out = BTreeMap::new();
    for (cls, ivals) in mw {
        if !["drive", "recharge", "work"].contains(&cls.as_str()) {
            return bad(format!(
                "unknown mission_window class {}; allowed: ['drive', 'recharge', 'work']",
                repr_str(cls)
            ));
        }
        let Some(ivals) = ivals.as_array() else {
            return bad(format!(
                "mission_windows[{}] must be a list of [open_s, close_s] pairs",
                repr_str(cls)
            ));
        };
        let mut clean = Vec::new();
        for (n, iv) in ivals.iter().enumerate() {
            let Some([o, c]) = iv
                .as_array()
                .map(Vec::as_slice)
                .and_then(|s| <&[Value; 2]>::try_from(s).ok())
            else {
                return bad(format!(
                    "mission_windows[{}][{n}] must be a [open_s, close_s] pair",
                    repr_str(cls)
                ));
            };
            let (o, c) = (
                finite(o, &format!("mission_windows[{cls}][{n}] open"))?,
                finite(c, &format!("mission_windows[{cls}][{n}] close"))?,
            );
            if c < o {
                return bad(format!(
                    "mission_windows[{}][{n}]: close ({}) must be >= open ({})",
                    repr_str(cls),
                    fr(c),
                    fr(o)
                ));
            }
            clean.push((o, c));
        }
        if !clean.is_empty() {
            out.insert(cls.clone(), clean);
        }
    }
    Ok(out)
}

/// A non-negative JSON integer (not a boolean, not a float such as `2.0`).
fn count(v: Option<&Value>) -> Option<u64> {
    v.and_then(Value::as_u64)
}

fn parse_resources(v: &Value) -> Result<Vec<SharedResource>, MissionError> {
    let Some(list) = v.as_array() else {
        return bad("'shared_resources' must be a list of {id, kind, capacity, sites}");
    };
    let mut out: Vec<SharedResource> = Vec::new();
    for (n, r) in list.iter().enumerate() {
        let Some(r) = r.as_object() else {
            return bad(format!("shared_resources[{n}] must be an object"));
        };
        let id = r
            .get("id")
            .map(|v| text(v, "id"))
            .transpose()?
            .unwrap_or_default()
            .trim()
            .to_owned();
        if id.is_empty() {
            return bad(format!("shared_resources[{n}] needs a non-empty 'id'"));
        }
        if out.iter().any(|s| s.id == id) {
            return bad(format!(
                "shared_resources[{n}]: duplicate id {}",
                repr_str(&id)
            ));
        }
        let kind = r.get("kind").and_then(Value::as_str).unwrap_or("");
        if !["corridor", "dump", "pit", "vantage"].contains(&kind) {
            return bad(format!(
                "shared_resources[{}] kind {}; allowed: ['corridor', 'dump', 'pit', 'vantage']",
                repr_str(&id),
                repr(r.get("kind").unwrap_or(&Value::Null))
            ));
        }
        let capacity = match r.get("capacity") {
            None => 1,
            v => match count(v) {
                Some(c) if c >= 1 => c,
                _ => {
                    return bad(format!(
                        "shared_resources[{}] capacity must be an int >= 1 (got {})",
                        repr_str(&id),
                        repr(v.unwrap_or(&Value::Null))
                    ));
                }
            },
        };
        let sites = match r.get("sites").and_then(Value::as_array) {
            Some(s) if !s.is_empty() => s
                .iter()
                .enumerate()
                .map(|(m, p)| xy(p, &format!("shared_resources[{id}].sites[{m}]")))
                .collect::<Result<Vec<_>, _>>()?,
            _ => {
                return bad(format!(
                    "shared_resources[{}] needs a non-empty 'sites' list of [x, y]",
                    repr_str(&id)
                ));
            }
        };
        out.push(SharedResource {
            id,
            kind: kind.to_owned(),
            capacity,
            sites,
        });
    }
    Ok(out)
}

fn parse_observations(value: &Value) -> Result<Vec<Observation>, MissionError> {
    let Some(list) = value.as_array() else {
        return bad("'observations' must be a list of {vehicle, x, y, t_start, t_end, kind}");
    };
    let mut out = Vec::new();
    for (n, entry) in list.iter().enumerate() {
        let Some(o) = entry.as_object() else {
            return bad(format!("observations[{n}] must be an object"));
        };
        let Some(vehicle) = count(o.get("vehicle")) else {
            return bad(format!(
                "observations[{n}] vehicle must be an int >= 0 (got {})",
                repr(o.get("vehicle").unwrap_or(&Value::Null))
            ));
        };
        let kind = match o.get("kind") {
            None => "meerkat",
            Some(k) => k.as_str().unwrap_or(""),
        };
        if !["meerkat", "solar"].contains(&kind) {
            return bad(format!(
                "observations[{n}] kind {}; allowed: ['meerkat', 'solar']",
                repr(o.get("kind").unwrap_or(&Value::Null))
            ));
        }
        for key in ["x", "y", "t_start", "t_end"] {
            if !o.contains_key(key) {
                return bad(format!("observations[{n}] needs '{key}'"));
            }
        }
        let f = |k: &str| finite(&o[k], &format!("observations[{n}].{k}"));
        let (x, y, t0, t1) = (f("x")?, f("y")?, f("t_start")?, f("t_end")?);
        if t1 <= t0 {
            return bad(format!(
                "observations[{n}] window must have t_end > t_start (got [{}, {}))",
                fr(t0),
                fr(t1)
            ));
        }
        out.push(Observation {
            vehicle,
            x,
            y,
            t_start: t0,
            t_end: t1,
            kind: kind.to_owned(),
        });
    }
    Ok(out)
}

fn optional_positive(p: &Map<String, Value>, key: &str) -> Result<Option<f64>, MissionError> {
    match p.get(key) {
        None | Some(Value::Null) => Ok(None),
        Some(v) => {
            let x = finite(v, key)?;
            if x <= 0.0 {
                return bad(format!("'{key}' must be > 0 (got {})", fr(x)));
            }
            Ok(Some(x))
        }
    }
}

/// Build a [`Mission`] from the wire format, refusing the first malformed field.
///
/// # Errors
/// [`MissionError`] naming the field and why.
#[allow(clippy::too_many_lines)] // one pass over the wire format, in the Python's order of checks
pub fn mission_from_value(payload: &Value, reg: &Registries) -> Result<Mission, MissionError> {
    let Some(p) = payload.as_object() else {
        return bad("mission payload must be a JSON object");
    };
    match p.get("schema_version") {
        None | Some(Value::Null) => {}
        Some(Value::String(s))
            if s.is_empty() || s == LEGACY_MISSION_VERSION || s == MISSION_SCHEMA_VERSION => {}
        Some(v) => {
            return bad(format!(
                "no migration path from schema_version {} to {}; register a migrator (register_mission_migration) for that version",
                repr(v),
                repr_str(MISSION_SCHEMA_VERSION)
            ));
        }
    }
    let body = match p.get("body").and_then(Value::as_str) {
        Some(b) if reg.bodies.iter().any(|k| k == b) => b.to_owned(),
        _ => {
            return bad(format!(
                "unknown body {}; known: {}",
                repr(p.get("body").unwrap_or(&Value::Null)),
                sorted(&reg.bodies)
            ));
        }
    };
    let vehicle = p
        .get("vehicle")
        .map(|v| text(v, "vehicle"))
        .transpose()?
        .unwrap_or_else(|| reg.default_vehicle.clone());
    let tools: Vec<String> = match p.get("tools") {
        None | Some(Value::Null) => Vec::new(),
        Some(Value::Array(a)) => a
            .iter()
            .map(|t| text(t, "tool"))
            .collect::<Result<_, _>>()?,
        Some(v) if !truthy(Some(v)) => Vec::new(),
        Some(v) => return bad(format!("'tools' must be a list (got {})", repr(v))),
    };
    let Some(base) = lookup(&reg.vehicles, &vehicle) else {
        // a KeyError's text, as str() of it quotes it
        return bad(repr_str(&format!(
            "unknown vehicle {}; known: {}",
            repr_str(&vehicle),
            sorted(&reg.vehicles.keys().collect::<Vec<_>>())
        )));
    };
    let mut caps = base.clone();
    for t in &tools {
        let Some(cap) = lookup(&reg.tools, t) else {
            return bad(repr_str(&format!(
                "unknown tool {}; known: {}",
                repr_str(t),
                sorted(&reg.tools.keys().collect::<Vec<_>>())
            )));
        };
        caps.push(cap.clone());
    }
    let mut soil = match p.get("soil") {
        Some(v) if truthy(Some(v)) => text(v, "soil")?.trim().to_owned(),
        _ => String::new(),
    };
    if !soil.is_empty() {
        let key = soil.to_lowercase();
        if !reg.bodies.contains(&key) {
            return bad(repr_str(&format!(
                "unknown body {}; known: {}",
                repr_str(&soil),
                sorted(&reg.bodies)
            )));
        }
        if key == body {
            soil.clear();
        }
    }
    let backend = match p.get("physics_backend_id") {
        Some(v) if truthy(Some(v)) => text(v, "physics_backend_id")?.trim().to_owned(),
        _ => String::new(),
    };
    let backend = if backend.is_empty() {
        "tier2_numpy".to_owned()
    } else {
        backend
    };
    if !reg.backends.contains(&backend) {
        return bad(format!(
            "unknown/unselectable physics_backend_id {}; selectable: {} (the PX-03 Chrono oracle is not a \
             release-authority backend until it conserves mass)",
            repr_str(&backend),
            repr_list(&reg.backends)
        ));
    }
    let raw = match p.get("orders").and_then(Value::as_array) {
        Some(a) if !a.is_empty() => a,
        _ => return bad("mission needs a non-empty 'orders' list"),
    };
    let orders = raw
        .iter()
        .enumerate()
        .map(|(i, o)| parse_order(i, o, &caps, &vehicle, &tools))
        .collect::<Result<Vec<_>, _>>()?;
    let charger = match p.get("charger") {
        None => (0.0, 0.0),
        Some(c) => xy(c, "charger")?,
    };
    let charger_capacity = match p.get("charger_capacity") {
        Some(v) if truthy(Some(v)) => {
            let x = finite(v, "charger_capacity")?;
            #[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)]
            // Python int(): toward zero, clamped
            let c = x.trunc().clamp(1.0, 8.0) as u64;
            c
        }
        _ => 1,
    };
    let date = p.get("date").map(|d| text(d, "date")).transpose()?;
    let lander = match p.get("lander") {
        None | Some(Value::Null) => None,
        Some(l) => Some(xy(l, "lander")?),
    };
    let return_buffer_frac = match p.get("return_buffer_frac") {
        None => None,
        Some(v) => {
            let x = finite(v, "return_buffer_frac")?;
            if x < 0.0 {
                return bad(format!("return_buffer_frac must be >= 0 (got {x})"));
            }
            Some(x)
        }
    };
    let precedence = parse_precedence(p, &orders)?;
    let keepouts = match p.get("keepouts") {
        None | Some(Value::Null) => Vec::new(),
        Some(k) => parse_keepouts(k)?,
    };
    let opt = |k: &str| p.get(k).filter(|v| !v.is_null());
    Ok(Mission {
        name: p
            .get("name")
            .map(|n| text(n, "name"))
            .transpose()?
            .unwrap_or_else(|| "Build Mission".to_owned()),
        body,
        orders,
        charger,
        charger_capacity,
        date,
        lander,
        return_buffer_frac,
        precedence,
        vehicle,
        tools,
        soil,
        keepouts,
        objective_constraints: opt("objective_constraints")
            .map(parse_constraints)
            .transpose()?
            .unwrap_or_default(),
        mission_windows: opt("mission_windows")
            .map(parse_windows)
            .transpose()?
            .unwrap_or_default(),
        shared_resources: opt("shared_resources")
            .map(parse_resources)
            .transpose()?
            .unwrap_or_default(),
        observations: opt("observations")
            .map(parse_observations)
            .transpose()?
            .unwrap_or_default(),
        dig_energy_factor: optional_positive(p, "dig_energy_factor")?,
        accept_flatness_tol_m: optional_positive(p, "accept_flatness_tol_m")?,
        physics_backend_id: backend,
    })
}
