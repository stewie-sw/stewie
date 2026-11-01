//! Plan release binding (RW-33f, new work: assessment #2): a release pins one executable plan IR to the exact
//! context it was planned for -- the plan id and the IR's own hash, the site and its local frame, the terrain the
//! routes were computed on (DEM content hash), the world-model state the plan read (Terrain Memory version and chain
//! head, observed-twin version and hash), the keep-outs, the constraints (objective budgets, mission windows, shared
//! resources, observations, precedence, the vehicle), and the physics backend and configuration. An executive
//! checks the release against its live context before running it; any difference refuses execution and names the
//! field. An infeasible IR is never released. (D-R100)

use serde_json::{Value, json};
use sha2::{Digest, Sha256};

use crate::mission::{Keepout, Mission};

/// The context a release is bound to; an executive supplies the same at run time.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Binding {
    pub site_id: String,
    /// The DEM content the routes were computed on (SHA-256 hex).
    pub dem_sha256: String,
    pub terrain_memory_version: u64,
    /// The Terrain Memory chain head.
    pub terrain_memory_head: String,
    pub twin_version: u64,
    pub twin_hash: String,
    pub physics_backend_id: String,
    /// The planner, report and acceptance parameters (SHA-256 hex of their canonical JSON).
    pub physics_config_sha256: String,
}

/// A released plan.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Release {
    pub plan_id: String,
    pub ir_sha256: String,
    /// The IR's frame (`crs`, origin and charger), canonical JSON.
    pub frame: String,
    pub keepouts_sha256: String,
    pub constraints_sha256: String,
    pub binding: Binding,
    /// SHA-256 over every field above.
    pub release_id: String,
}

fn sha256_hex(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .fold(String::new(), |mut s, b| {
            use std::fmt::Write as _;
            let _ = write!(s, "{b:02x}");
            s
        })
}

fn canon(v: &Value) -> Result<String, String> {
    stewie_twin::pyjson::dumps(v).map_err(|e| e.to_string())
}

fn keepouts(m: &Mission) -> Value {
    Value::Array(
        m.keepouts
            .iter()
            .map(|k| match k {
                Keepout::Circle { x, y, r } => json!({"x": x, "y": y, "r": r}),
                Keepout::Rect { x0, y0, x1, y1 } => json!({"x0": x0, "y0": y0, "x1": x1, "y1": y1}),
                Keepout::Polygon(p) => {
                    json!({"points": p.iter().map(|q| [q.0, q.1]).collect::<Vec<_>>()})
                }
            })
            .collect(),
    )
}

fn constraints(m: &Mission) -> Value {
    json!({
        "vehicle": m.vehicle,
        "objective_constraints": m.objective_constraints,
        "mission_windows": m.mission_windows,
        "shared_resources": m.shared_resources.iter().map(|r| json!({
            "id": r.id, "kind": r.kind, "capacity": r.capacity,
            "sites": r.sites.iter().map(|s| [s.0, s.1]).collect::<Vec<_>>()})).collect::<Vec<_>>(),
        "observations": m.observations.iter().map(|o| json!({
            "vehicle": o.vehicle, "x": o.x, "y": o.y, "t_start": o.t_start, "t_end": o.t_end,
            "kind": o.kind})).collect::<Vec<_>>(),
        "precedence": m.precedence,
        "charger_capacity": m.charger_capacity,
    })
}

/// The release fields as one canonical JSON document (the release id hashes it; the schema describes it).
fn document(r: &Release) -> Value {
    let b = &r.binding;
    json!({
        "plan_id": r.plan_id, "ir_sha256": r.ir_sha256, "frame": r.frame,
        "keepouts_sha256": r.keepouts_sha256, "constraints_sha256": r.constraints_sha256,
        "binding": {"site_id": b.site_id, "dem_sha256": b.dem_sha256,
                    "terrain_memory_version": b.terrain_memory_version,
                    "terrain_memory_head": b.terrain_memory_head, "twin_version": b.twin_version,
                    "twin_hash": b.twin_hash, "physics_backend_id": b.physics_backend_id,
                    "physics_config_sha256": b.physics_config_sha256},
    })
}

impl Release {
    /// The release as a contract document (`release.schema.json`).
    #[must_use]
    pub fn to_value(&self) -> Value {
        let mut d = document(self);
        d["release_id"] = json!(self.release_id);
        d
    }
}

/// Release `ir` (the executable IR of `m`) bound to `binding`.
///
/// # Errors
/// An infeasible IR, an IR without a plan id or frame, or a value with no canonical form.
pub fn bind(m: &Mission, ir: &Value, binding: Binding) -> Result<Release, String> {
    if ir["feasible"] != Value::Bool(true) {
        return Err("an infeasible plan IR is never released".to_owned());
    }
    let plan_id = ir["plan_id"]
        .as_str()
        .ok_or("the plan IR has no plan_id")?
        .to_owned();
    if !ir["frame"].is_object() {
        return Err("the plan IR has no frame".to_owned());
    }
    let mut r = Release {
        plan_id,
        ir_sha256: sha256_hex(canon(ir)?.as_bytes()),
        frame: canon(&ir["frame"])?,
        keepouts_sha256: sha256_hex(canon(&keepouts(m))?.as_bytes()),
        constraints_sha256: sha256_hex(canon(&constraints(m))?.as_bytes()),
        binding,
        release_id: String::new(),
    };
    r.release_id = sha256_hex(canon(&document(&r))?.as_bytes());
    Ok(r)
}

/// Check a release against the live execution context: the IR about to run, the mission it came from, and the
/// executive's own binding. Returns every mismatch by field; any one refuses execution.
///
/// # Errors
/// The mismatched fields, or a value with no canonical form.
pub fn check(r: &Release, m: &Mission, ir: &Value, live: &Binding) -> Result<(), Vec<String>> {
    let fresh = bind(m, ir, live.clone()).map_err(|e| vec![e])?;
    let mut bad = Vec::new();
    if r.release_id != sha256_hex(canon(&document(r)).map_err(|e| vec![e])?.as_bytes()) {
        bad.push("release_id".to_owned());
    }
    let pairs = [
        ("plan_id", &r.plan_id, &fresh.plan_id),
        ("ir_sha256", &r.ir_sha256, &fresh.ir_sha256),
        ("frame", &r.frame, &fresh.frame),
        (
            "keepouts_sha256",
            &r.keepouts_sha256,
            &fresh.keepouts_sha256,
        ),
        (
            "constraints_sha256",
            &r.constraints_sha256,
            &fresh.constraints_sha256,
        ),
        ("site_id", &r.binding.site_id, &live.site_id),
        ("dem_sha256", &r.binding.dem_sha256, &live.dem_sha256),
        (
            "terrain_memory_head",
            &r.binding.terrain_memory_head,
            &live.terrain_memory_head,
        ),
        ("twin_hash", &r.binding.twin_hash, &live.twin_hash),
        (
            "physics_backend_id",
            &r.binding.physics_backend_id,
            &live.physics_backend_id,
        ),
        (
            "physics_config_sha256",
            &r.binding.physics_config_sha256,
            &live.physics_config_sha256,
        ),
    ];
    bad.extend(
        pairs
            .iter()
            .filter(|(_, a, b)| a != b)
            .map(|(k, _, _)| (*k).to_owned()),
    );
    if r.binding.terrain_memory_version != live.terrain_memory_version {
        bad.push("terrain_memory_version".to_owned());
    }
    if r.binding.twin_version != live.twin_version {
        bad.push("twin_version".to_owned());
    }
    if bad.is_empty() { Ok(()) } else { Err(bad) }
}
