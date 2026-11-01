//! A plan's provenance and its playback timeline (RW-55b14b-2; Python `mission_planner._plan_provenance` and
//! `build_timeline`). The provenance ties a result to its inputs: a SHA-256 over the Python's
//! `json.dumps({mission (dataclasses.asdict), dem_origin, algorithm, objective, vehicles, seed}, sort_keys=True)`,
//! reproduced byte for byte, so a Rust plan of the same mission and anchor carries the Python's `input_sha256`.

use serde::Deserialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use stewie_traverse::costmap::Keepout;
use stewie_twin::numpy::round;

use crate::assemble::Plan;
use crate::mission::Mission;
use crate::sim::SpanKind;

/// What the provenance needs beyond the mission (`plan_provenance.json`).
#[derive(Debug, Clone, Deserialize, PartialEq)]
pub struct Defaults {
    /// `PlanResult` schema version.
    pub schema_version: String,
    pub mode: String,
    /// The Python `Mission` dataclass's `date` default (the mission JSON may omit it).
    pub default_date: String,
}

fn xy((x, y): (f64, f64)) -> Value {
    json!([x, y])
}

/// The Python's `dataclasses.asdict(mission)`: every field, a container the mission left empty as `None` (the
/// Python stores those only when non-empty), the dataclass defaults for an omitted date and return buffer.
#[must_use]
pub fn mission_asdict(m: &Mission, default_return_buffer_frac: f64, d: &Defaults) -> Value {
    let none_if_empty = |empty: bool, v: Value| if empty { Value::Null } else { v };
    let orders: Vec<Value> = m
        .orders
        .iter()
        .map(|o| {
            json!({"action": o.action, "kind": o.kind.name(), "x": o.x, "y": o.y, "footprint_m2": o.footprint_m2,
                   "depth_m": o.depth_m, "note": o.note, "shape": o.shape, "insitu_density_kg_m3": o.insitu_density_kg_m3})
        })
        .collect();
    let keepouts: Vec<Value> = m
        .keepouts
        .iter()
        .map(|k| match k {
            Keepout::Circle { x, y, r } => json!({"x": x, "y": y, "r": r}),
            Keepout::Rect { x0, y0, x1, y1 } => json!({"x0": x0, "y0": y0, "x1": x1, "y1": y1}),
            Keepout::Polygon(p) => json!({"points": p.iter().map(|&q| xy(q)).collect::<Vec<_>>()}),
        })
        .collect();
    json!({
        "name": m.name, "body": m.body, "orders": orders, "charger": xy(m.charger),
        "charger_capacity": m.charger_capacity, "date": m.date.clone().unwrap_or_else(|| d.default_date.clone()),
        "lander": m.lander.map(xy), "return_buffer_frac": m.return_buffer_frac.unwrap_or(default_return_buffer_frac),
        "precedence": m.precedence.iter().map(|(a, b)| json!([a, b])).collect::<Vec<_>>(),
        "vehicle": m.vehicle, "tools": m.tools, "soil": m.soil, "keepouts": keepouts, "temp_c": null,
        "objective_constraints": none_if_empty(m.objective_constraints.is_empty(), json!(m.objective_constraints)),
        "mission_windows": none_if_empty(
            m.mission_windows.is_empty(),
            Value::Object(m.mission_windows.iter().map(|(k, v)| (k.clone(), Value::Array(v.iter().map(|&w| xy(w)).collect())))
                .collect()),
        ),
        "shared_resources": none_if_empty(
            m.shared_resources.is_empty(),
            json!(m.shared_resources.iter().map(|r| json!({"id": r.id, "kind": r.kind, "capacity": r.capacity,
                "sites": r.sites.iter().map(|&s| xy(s)).collect::<Vec<_>>()})).collect::<Vec<_>>()),
        ),
        "observations": none_if_empty(
            m.observations.is_empty(),
            json!(m.observations.iter().map(|o| json!({"vehicle": o.vehicle, "x": o.x, "y": o.y, "t_start": o.t_start,
                "t_end": o.t_end, "kind": o.kind})).collect::<Vec<_>>()),
        ),
        "dig_energy_factor": m.dig_energy_factor, "accept_flatness_tol_m": m.accept_flatness_tol_m,
        "physics_backend_id": m.physics_backend_id,
    })
}

/// How a plan was asked for.
#[derive(Debug, Clone, Copy)]
pub struct Request<'a> {
    pub origin: (f64, f64),
    pub algorithm: &'a str,
    pub objective: &'a str,
    pub vehicles: usize,
    pub default_return_buffer_frac: f64,
}

/// The text the input hash covers: the Python's `json.dumps({...}, sort_keys=True, default=str)`.
///
/// # Errors
/// A non-finite number in the mission.
pub fn canonical(m: &Mission, req: &Request<'_>, d: &Defaults) -> Result<String, String> {
    let canon = json!({
        "mission": mission_asdict(m, req.default_return_buffer_frac, d), "dem_origin": xy(req.origin),
        "algorithm": req.algorithm, "objective": req.objective, "vehicles": req.vehicles, "seed": null,
    });
    stewie_twin::pyjson::dumps(&canon).map_err(|e| e.to_string())
}

/// The provenance of a plan (Python `_plan_provenance`; the planner's sequencers are deterministic, so the seed is
/// `None`). `commit` and `version` name the code that made it.
///
/// # Errors
/// A non-finite number in the mission.
pub fn provenance(
    m: &Mission,
    req: &Request<'_>,
    d: &Defaults,
    commit: &str,
    version: &str,
) -> Result<Value, String> {
    let text = canonical(m, req, d)?;
    let digest = Sha256::digest(text.as_bytes())
        .iter()
        .fold(String::new(), |mut s, b| {
            use std::fmt::Write as _;
            let _ = write!(s, "{b:02x}");
            s
        });
    Ok(json!({
        "schema_version": d.schema_version, "mode": d.mode, "commit": commit, "version": version, "seed": null,
        "config": {"algorithm": req.algorithm, "objective": req.objective, "vehicles": req.vehicles},
        "input_sha256": digest,
    }))
}

fn phase(k: SpanKind) -> &'static str {
    match k {
        SpanKind::Drive => "drive",
        SpanKind::Wait => "wait",
        SpanKind::Charge => "charge",
        SpanKind::Dig => "dig",
        SpanKind::Offload => "offload",
    }
}

/// The animatable playback of a plan (Python `build_timeline`): one frame per simulated span with its positions,
/// battery fractions of the IPEx pack (the Python's module `BATTERY_J`) and the mass moved so far.
#[must_use]
pub fn timeline(plan: &Plan, m: &Mission, ipex_battery_j: f64, provenance: &Value) -> Value {
    let mut cum = 0.0;
    let frames: Vec<Value> = plan
        .tl
        .iter()
        .map(|s| {
            cum += s.mass_kg;
            json!({"t0": round(s.t0, 3), "t1": round(s.t1, 3), "x0": round(s.from.0, 3), "y0": round(s.from.1, 3),
                   "x1": round(s.to.0, 3), "y1": round(s.to.1, 3), "phase": phase(s.kind),
                   "batt0_frac": s.batt0 / ipex_battery_j, "batt1_frac": s.batt1 / ipex_battery_j,
                   "cum_mass_kg": round(cum, 1)})
        })
        .collect();
    json!({"duration_s": round(plan.totals.time_s, 3), "battery_J": ipex_battery_j, "charger": xy(m.charger),
           "frames": frames, "provenance": provenance})
}
