//! The executive's SIM run (RW-55c2b; Python `routers/executive.executive_run`, `lode.sim_execution`,
//! `contracts.plan_gate`, `contracts.reconciliation_step`, `contracts.physics_model_control.physics_attribution`,
//! `runtime.replay_loop.terramechanics_comparison` and `server.traffic_fold`): `POST /executive/run` releases the plan
//! (or binds a frozen released revision), runs the closed loop on the site's as-built surface, steps the live chain
//! ARMED -> EXECUTING -> COMPLETED or SAFED leg by leg through the executive's safety decision, and commits the run as
//! world transactions with the terrain and traffic it left behind; then it reports the plan's executability, the
//! energy reconciliation, a live-execution token when every training-to-live step holds, the physics attribution and
//! the terramechanics comparison. `GET /executive/run/{id}` and its SSE stream replay a stored run.

use std::collections::BTreeSet;

use futures_util::StreamExt as _;
use std::sync::Arc;

use axum::Router;
use axum::body::Body;
use axum::extract::{Path, Query, Request, State};
use axum::http::{StatusCode, header};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use serde_json::{Map, Value, json};
use stewie_twin::terrain_memory;
use stewie_twin::traffic_memory;

use crate::admin::{require_director, require_role};
use crate::app::{ApiError, AppState, Head, body_model, err, log, parse_body, split};
use crate::executive_routes::{
    Released, compile_intent, intent_from_orders, record_action, run_lifecycle,
};
use crate::objects::{Namespace, ns_dir, owner_meta, slug};
use crate::operators::py_repr;
use crate::plan_routes::{DEFAULTS, Opts, Planned, plan_with};
use crate::rc_routes::{dumps, ordered};
use crate::validate::{Field, Kind, Model};

/// The most runs kept per owner (the oldest go first).
const RUN_MAX: usize = 200;

const fn text(max: usize, default: Option<&'static str>) -> Kind {
    Kind::Str {
        min: 0,
        max,
        nullable: default.is_none(),
        default,
    }
}

/// Python `RunRequest` (`orders` defaults to `[]`; the request's other keys are ignored).
const RUN: Model = Model {
    fields: &[
        Field("orders", Kind::DictList { min: 0, max: 1000 }),
        Field("body", text(usize::MAX, Some("moon"))),
        Field("site", text(40, Some("haworth"))),
        Field("mission_id", text(usize::MAX, Some("cockpit-run"))),
        Field(
            "revision",
            Kind::Int {
                ge: 0,
                le: i64::MAX,
                default: 0,
            },
        ),
        Field("revision_hash", text(64, None)),
    ],
    forbid_extra: false,
};

/// One run of the live chain (Python `run_sim_execution`).
struct SimRun {
    final_state: &'static str,
    transitions: Vec<&'static str>,
    /// `(leg, action)` for each leg executed before any safing.
    executed: Vec<(usize, String)>,
    n_legs: usize,
    safed: bool,
    nonnominal: usize,
}

/// ARMED -> EXECUTING, then each leg's faults through the executive's safety-precedence decision: a safety-critical
/// fault safes the run and halts it; otherwise it completes.
fn run_sim_execution(legs: &[Value]) -> SimRun {
    let mut transitions = vec!["armed", "executing"];
    let (mut executed, mut safed) = (Vec::new(), false);
    for (i, leg) in legs.iter().enumerate() {
        let faults = leg["faults"].as_array().cloned().unwrap_or_default();
        let d = stewie_traverse::nav::executive_step(&faults, true, true, None, None);
        if d["safety_critical"] == true {
            transitions.push("safed");
            safed = true;
            break;
        }
        executed.push((i, d["action"].as_str().unwrap_or("").to_owned()));
    }
    let nonnominal = executed
        .iter()
        .filter(|(_, a)| !matches!(a.as_str(), "continue" | "persist"))
        .count();
    if !safed {
        transitions.push("completed");
    }
    SimRun {
        final_state: if safed { "safed" } else { "completed" },
        transitions,
        executed,
        n_legs: legs.len(),
        safed,
        nonnominal,
    }
}

/// The FS-04 execution events of a stored run record (Python `execution_events`): one per executed leg (`t_s` is the
/// leg ordinal; a non-nominal action is `blocked`), then the terminal `safe` or `acceptance` event.
fn execution_events(rec: &Value) -> Vec<Value> {
    let mut out: Vec<Value> = Vec::new();
    for leg in rec["executed_legs"].as_array().into_iter().flatten() {
        let i = leg["leg"].as_i64().unwrap_or(0);
        let action = leg["action"].as_str().unwrap_or("continue");
        let outcome = if matches!(action, "continue" | "persist") {
            "ok"
        } else {
            "blocked"
        };
        #[allow(clippy::cast_precision_loss)] // a leg ordinal
        out.push(json!({"t_s": i as f64, "kind": "leg", "detail": format!("sim leg {i}: {action}"), "outcome": outcome}));
    }
    #[allow(clippy::cast_precision_loss)] // a leg count
    let t = out.len() as f64;
    out.push(if rec["safed"] == true {
        json!({"t_s": t, "kind": "safe", "detail": "SIM watchdog: run safed", "outcome": "safed"})
    } else {
        json!({"t_s": t, "kind": "acceptance",
               "detail": format!("SIM run {}", rec["final_state"].as_str().unwrap_or("completed")), "outcome": "ok"})
    });
    out
}

fn float_repr(x: f64) -> String {
    stewie_twin::pyjson::float_repr(x).unwrap_or_else(|_| x.to_string())
}

/// EG-08 / MP-11 (Python `reconcile_prediction` over the energy): the residual against the estimator's own sigma, a
/// world-update proposal whenever it is nonzero, and a model-update proposal when it exceeds the sigma.
fn reconcile(predicted: f64, observed: f64, tolerance: f64, stem: &str) -> Value {
    let residual = observed - predicted;
    let abs = residual.abs();
    let implicates = abs > tolerance;
    let confidence = if abs == 0.0 {
        0.0
    } else {
        abs / (abs + tolerance)
    };
    let (p, o, r) = (
        float_repr(predicted),
        float_repr(observed),
        float_repr(residual),
    );
    let mut proposals = Vec::new();
    if abs != 0.0 {
        proposals.push(json!({"proposal_id": format!("{stem}:world:energy_J"), "state": "proposed",
                              "confidence": confidence, "model_error": implicates,
                              "change": format!("set world belief energy_J = {o} (predicted {p}, residual {r})")}));
        if implicates {
            proposals.push(json!({"proposal_id": format!("{stem}:model:energy_J"), "state": "proposed",
                                  "confidence": confidence, "model_error": true,
                                  "change": format!("recalibrate model for energy_J: predicted {p} vs observed {o} \
                                                     (residual {r} exceeds sensor tolerance {})", float_repr(tolerance))}));
        }
    }
    json!({"quantity": "energy_J", "predicted": predicted, "observed": observed, "residual": residual,
           "implicates_model": implicates, "proposals": proposals})
}

/// PH-02 (Python `physics_attribution`): the producing backend's authority from the registry, and its live-eligible
/// calibration of record.
fn physics_attribution(backend: &str) -> Value {
    let auth = crate::model_routes::reg("backend_authority")
        .as_array()
        .and_then(|a| a.iter().find(|b| b["id"] == backend).cloned());
    let model = crate::model_routes::reg("physics_models")
        .as_array()
        .and_then(|a| {
            a.iter()
                .find(|m| {
                    m["backend_id"] == backend
                        && m["validated"] == true
                        && m["frozen"] == true
                        && m["deprecated"] == false
                })
                .cloned()
        });
    let flag = |k: &str| auth.as_ref().is_some_and(|a| a[k] == true);
    json!({"backend": backend, "conserves_mass": flag("conserves_mass"),
           "authority_scope": auth.as_ref().map_or(json!([]), |a| a["authority_scope"].clone()),
           "release_eligible": flag("valid_for_release"),
           "calibration": model.map(|m| json!({"model_id": m["model_id"], "calibration": m["calibration"],
                                                "validated": m["validated"], "frozen": m["frozen"], "live_eligible": true})),
           "attributed_quantities": ["energy_J", "conserved_terrain_delta_m3", "as_built_acceptance"]})
}

fn sum(legs: &[Value], k: &str) -> f64 {
    legs.iter()
        .fold(0.0, |a, l| a + l[k].as_f64().unwrap_or(0.0))
}

/// TM-04 (Python `terramechanics_comparison`): energy predicted versus observed, slip observed only, sinkage stated
/// as not telemetered.
fn terramechanics_comparison(legs: &[Value]) -> Value {
    let (pred, obs, tol) = (
        sum(legs, "nominal_J"),
        sum(legs, "true_J"),
        sum(legs, "energy_sigma_J"),
    );
    let slips: Vec<f64> = legs.iter().filter_map(|l| l["slip"].as_f64()).collect();
    #[allow(clippy::cast_precision_loss)] // a leg count
    let mean_slip =
        (!slips.is_empty()).then(|| slips.iter().fold(0.0, |a, x| a + x) / slips.len() as f64);
    json!({"backend": "tier2_numpy", "n_legs": legs.len(), "terms": [
        {"term": "energy_J", "available": true, "predicted": pred, "observed": obs, "residual": obs - pred,
         "within_tolerance": (obs - pred).abs() <= tol, "backend": "tier2_numpy"},
        {"term": "slip", "available": "observed_only", "predicted": null, "observed": mean_slip,
         "note": "SIM slip is the slip-truth model output; no separate nominal-slip prediction is logged per leg",
         "backend": "tier2_numpy"},
        {"term": "sinkage", "available": false, "predicted": null, "observed": null,
         "note": "not telemetered per leg in the current SIM; TM-02 exposes sinkage as an inspectable term",
         "backend": "tier2_numpy"}]})
}

fn sha_hex(bytes: &[u8]) -> String {
    use sha2::{Digest, Sha256};
    Sha256::digest(bytes)
        .iter()
        .fold(String::new(), |mut out, b| {
            use std::fmt::Write as _;
            let _ = write!(out, "{b:02x}");
            out
        })
}

/// The terrain fold's prepared half: the prior file (for the compensating restore) and the advanced authority hash.
struct Folded {
    prior: Option<Vec<u8>>,
    authority_sha: String,
}

/// Fold the executed mission's conserved terrain delta into the site's Terrain Memory under the site lock (Python
/// `_fold_sim_terrain`), before any world-journal write; `None` when nothing was moved.
fn fold_terrain(st: &AppState, p: &Planned, site: &str) -> Result<Option<Folded>, String> {
    let d = stewie_build::record::mission_terrain_delta(
        &p.mission,
        None,
        &p.inputs.acceptance(),
        &stewie_plan::acceptance::AcceptanceParams::default(),
    )?;
    if d.mass_moved_kg <= 0.0 {
        return Ok(None);
    }
    let lock = st.terrain.site_lock(site);
    let _g = lock
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    let prior = terrain_memory::snapshot_site(&st.cfg.data_dir, site).map_err(|e| e.to_string())?;
    let mut mem = match terrain_memory::load_site(&st.cfg.data_dir, site)
        .map_err(|e| e.to_string())?
    {
        Some(m) => m,
        None => terrain_memory::TerrainMemory::new(site, d.rows, d.cols, d.cell_m, (d.x0, d.y0))
            .map_err(|e| e.to_string())?,
    };
    mem.apply_subgrid(
        &d.delta,
        d.rows,
        d.cols,
        (d.x0, d.y0),
        d.cell_m,
        &p.mission.name,
        d.mass_moved_kg,
    )
    .map_err(|e| e.to_string())?;
    terrain_memory::save_site(&st.cfg.data_dir, &mem).map_err(|e| e.to_string())?;
    let bytes: Vec<u8> = mem
        .cumulative_delta()
        .iter()
        .flat_map(|x| x.to_le_bytes())
        .collect();
    Ok(Some(Folded {
        prior,
        authority_sha: sha_hex(&bytes),
    }))
}

/// The cells a straight drive crosses on the fixed work-area crop, sampled at half-cell spacing (Python
/// `traffic_fold._segment_cells`).
fn segment_cells(
    p0: (f64, f64),
    p1: (f64, f64),
    cell: f64,
    (r0, c0, rows, cols): (i64, i64, i64, i64),
) -> BTreeSet<(i64, i64)> {
    let dist = (p1.0 - p0.0).hypot(p1.1 - p0.1);
    #[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)] // a sample count
    let n = 2.max((dist / (cell * 0.5)) as usize + 1);
    let mut cells = BTreeSet::new();
    #[allow(clippy::cast_precision_loss, clippy::cast_possible_truncation)]
    // a sample index; grid indices
    for k in 0..n {
        // numpy's linspace: start + k * step, the last sample exactly the stop
        let t = if k + 1 == n {
            1.0
        } else {
            k as f64 * (1.0 / (n - 1) as f64)
        };
        let (x, y) = (p0.0 + (p1.0 - p0.0) * t, p0.1 + (p1.1 - p0.1) * t);
        let col = (x / cell).round_ties_even() as i64 - c0;
        let row = (y / cell).round_ties_even() as i64 - r0;
        if (0..rows).contains(&row) && (0..cols).contains(&col) {
            cells.insert((row, col));
        }
    }
    cells
}

/// Fold the run's true drive path into the site's Traffic Memory (Python `traffic_from_run`): `[charger]` then each
/// leg's true pose, placed at the site anchor and rasterised on the 128 x 128 work-area crop around it, one idempotent
/// event per leg at the dry static wheel load. `None` when nothing new hardened.
#[allow(clippy::many_single_char_names)] // the Python's cell, grid and anchor names
fn traffic_from_run(
    st: &AppState,
    p: &Planned,
    legs: &[Value],
    site: &str,
    mission_id: &str,
) -> Result<Option<traffic_memory::TrafficMemory>, String> {
    if legs.is_empty() {
        return Ok(None);
    }
    let cfg = st.planning.config.as_ref().map_err(Clone::clone)?;
    let cell = p.view.cell_m;
    #[allow(clippy::cast_possible_truncation, clippy::cast_possible_wrap)] // grid indices
    let (h, w) = (p.rows as i64, p.cols as i64);
    #[allow(clippy::cast_possible_truncation)] // Python's int(): toward zero
    let (r0, c0) = ((p.origin.1 / cell) as i64, (p.origin.0 / cell) as i64);
    let (r0, c0) = ((r0 - 64).min(h - 128).max(0), (c0 - 64).min(w - 128).max(0));
    // the dry static wheel load (Python `static_wheel_load_n(payload_kg=0)`: dry mass x lunar g / wheels)
    let vehicle = st
        .planning
        .fleet
        .vehicles
        .get("ipex")
        .ok_or("no ipex vehicle in the fleet registry")?;
    let g = st
        .planning
        .bodies
        .get("moon")
        .map(|b| b.g)
        .ok_or("no moon in the body registry")?;
    #[allow(clippy::cast_precision_loss)] // a wheel count
    let load = vehicle.dry_mass_kg * g / vehicle.n_wheels.get() as f64;
    let mut mem =
        match traffic_memory::load_site(&st.cfg.data_dir, site).map_err(|e| e.to_string())? {
            Some(m) => m,
            #[allow(clippy::cast_precision_loss)] // grid indices
            None => traffic_memory::TrafficMemory::new(
                site,
                128,
                128,
                cell,
                (c0 as f64 * cell, r0 as f64 * cell),
                cfg.traffic,
            )
            .map_err(|e| e.to_string())?,
        };
    let before = mem.version();
    // the poses are order-frame metres from the site anchor; the crop is in DEM cells, so the path is placed at the
    // anchor first (the Python rasterises the order frame as DEM metres, so every pose falls off the crop; D-R177)
    let at = |(x, y): (f64, f64)| (p.origin.0 + x, p.origin.1 + y);
    let mut path = vec![at(p.mission.charger)];
    path.extend(legs.iter().map(|l| {
        at((
            l["tx"].as_f64().unwrap_or(0.0),
            l["ty"].as_f64().unwrap_or(0.0),
        ))
    }));
    for (i, pair) in path.windows(2).enumerate() {
        let cells: Vec<(i64, i64)> = segment_cells(pair[0], pair[1], cell, (r0, c0, 128, 128))
            .into_iter()
            .collect();
        if !cells.is_empty() {
            mem.apply_path(&cells, load, mission_id, &format!("{mission_id}:leg{i}"))
                .map_err(|e| e.to_string())?;
        }
    }
    Ok((mem.version() != before).then_some(mem))
}

/// What the run executes: the released lifecycle, the planned mission, and the identity and binding it runs under.
struct Prepared {
    released: Released,
    planned: Planned,
    objectives: usize,
    mission_id: String,
    bound: Option<String>,
    body: String,
    skipped: Vec<Value>,
}

/// Bind the frozen released revision, or release the posted build orders (Python `executive_run`'s two paths).
#[allow(clippy::too_many_lines)] // the Python's two paths and their refusals
async fn prepare(
    st: &AppState,
    v: &Map<String, Value>,
    raw: &Map<String, Value>,
    identity: &str,
) -> Result<Result<Prepared, Response>, ApiError> {
    let refuse = |status: StatusCode, e: String, skipped: Option<Value>| {
        let mut body = json!({"ok": false, "error": e});
        if let Some(s) = skipped {
            body["skipped"] = s;
        }
        Ok(Err((status, axum::Json(body)).into_response()))
    };
    let site = v["site"].as_str().unwrap_or("haworth").to_owned();
    if let Some(hash) = v["revision_hash"].as_str().filter(|h| !h.is_empty()) {
        let Some(art) = st.edit_sessions.read_release_revision(hash).await? else {
            return refuse(
                StatusCode::BAD_REQUEST,
                format!(
                    "revision_hash {} is not a released revision (release the plan first)",
                    py_repr(hash)
                ),
                None,
            );
        };
        let mission_id = match crate::rc_routes::release_mission_id(&art) {
            Ok(m) => m,
            Err(e) => {
                return refuse(
                    StatusCode::CONFLICT,
                    format!("released revision identity is invalid: {e}"),
                    None,
                );
            }
        };
        // an explicitly supplied mission must match the frozen identity, or it is a retarget
        if let Some(asked) = raw.get("mission_id").and_then(Value::as_str)
            && asked != mission_id
        {
            return refuse(
                StatusCode::CONFLICT,
                format!(
                    "revision was released for mission {}, not {}",
                    py_repr(&mission_id),
                    py_repr(asked)
                ),
                None,
            );
        }
        let intent =
            crate::executive_routes::parse_intent(Some(&art["signed_revision"]["intent"]))?;
        let released = run_lifecycle(st, &intent)?;
        if released.signed["content_hash"] != hash {
            return refuse(
                StatusCode::CONFLICT,
                "released revision hash mismatch (store integrity)".to_owned(),
                None,
            );
        }
        let (mission, _) =
            compile_intent(st, &intent).map_err(|e| err(StatusCode::BAD_REQUEST, e))?;
        let planned = plan_with(
            st,
            &mission,
            &Opts {
                algorithm: "auto",
                objective: "time",
                site: Some(&site),
                ..DEFAULTS
            },
        )?;
        let objectives = intent["objectives"].as_array().map_or(0, Vec::len);
        return Ok(Ok(Prepared {
            released,
            planned,
            objectives,
            mission_id,
            bound: Some(hash.to_owned()),
            body: "moon".to_owned(),
            skipped: Vec::new(),
        }));
    }
    let mission_id = v["mission_id"].as_str().unwrap_or("cockpit-run").to_owned();
    let body = v["body"].as_str().unwrap_or("moon").to_owned();
    let orders = v["orders"].as_array().cloned().unwrap_or_default();
    let (intent, skipped) = match intent_from_orders(
        st,
        &orders,
        &mission_id,
        identity,
        &body,
        v["revision"].as_i64().unwrap_or(0),
    ) {
        Ok(r) => r,
        Err(e) => return refuse(StatusCode::BAD_REQUEST, e, Some(json!([]))),
    };
    let objectives = intent["objectives"].as_array().map_or(0, Vec::len);
    if objectives == 0 {
        return refuse(
            StatusCode::BAD_REQUEST,
            "no build orders to run (cut/fill/sinter)".to_owned(),
            Some(json!(skipped)),
        );
    }
    let released = match run_lifecycle(st, &intent) {
        Ok(r) => r,
        Err(e) if e.0 == StatusCode::BAD_REQUEST => {
            return refuse(StatusCode::BAD_REQUEST, e.1, Some(json!(skipped)));
        }
        Err(e) => return Err(e),
    };
    let payload: Map<String, Value> = [
        ("name", json!(mission_id)),
        ("body", json!(body)),
        ("orders", json!(orders)),
        ("charger", json!([0.0, 0.0])),
    ]
    .into_iter()
    .map(|(k, v)| (k.to_owned(), v))
    .collect();
    let planned = match plan_with(
        st,
        &payload,
        &Opts {
            algorithm: "auto",
            objective: "time",
            site: Some(&site),
            ..DEFAULTS
        },
    ) {
        Ok(p) => p,
        Err(e) if e.0 == StatusCode::BAD_REQUEST => {
            return refuse(StatusCode::BAD_REQUEST, e.1, Some(json!(skipped)));
        }
        Err(e) => return Err(e),
    };
    Ok(Ok(Prepared {
        released,
        planned,
        objectives,
        mission_id,
        bound: None,
        body,
        skipped,
    }))
}

/// Commit the run through the world log (Python's DT-03 sequence): fold the terrain first, then the released plan and
/// one event per execution event, then the as-built terrain and the run's final belief (restoring the terrain file if
/// the journal refuses), then the traffic it drove (best effort).
fn commit(
    st: &AppState,
    prep: &Prepared,
    rec: &Value,
    legs: &[Value],
    belief: Map<String, Value>,
    site: &str,
    safed: bool,
) -> Result<(), String> {
    let mid = prep.mission_id.as_str();
    let folded = if safed {
        None
    } else {
        fold_terrain(st, &prep.planned, site)?
    };
    let stamp = crate::world::Stamp {
        mission: Some(mid),
        site: Some(site),
        body: Some(&prep.body),
        mission_t_s: None,
    };
    let restore = |f: &Folded| {
        let lock = st.terrain.site_lock(site);
        let _g = lock
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let _ = terrain_memory::restore_site(&st.cfg.data_dir, site, f.prior.as_deref());
    };
    let journal = || -> Result<(), String> {
        st.world.record_plan(
            &st.terrain,
            mid,
            &format!("SIM run: released plan {mid}"),
            &stamp,
        )?;
        for ev in execution_events(rec) {
            let provenance = format!(
                "SIM {}: {} [{}]",
                s(&ev, "kind"),
                s(&ev, "detail"),
                s(&ev, "outcome")
            );
            let at = crate::world::Stamp {
                mission_t_s: ev["t_s"].as_f64(),
                ..stamp
            };
            st.world
                .record_execution_event(&st.terrain, &provenance, None, None, &at, 0.0)?;
        }
        Ok(())
    };
    if let Err(e) = journal() {
        if let Some(f) = &folded {
            restore(f);
        }
        return Err(e);
    }
    let Some(f) = folded else {
        return Ok(());
    };
    let terrain = st
        .world
        .record_terrain(
            &st.terrain,
            &f.authority_sha,
            &format!("SIM as-built: {mid}"),
            &stamp,
        )
        .and_then(|_| {
            st.world
                .record_belief(&st.terrain, belief, &format!("SIM run belief: {mid}"), None)
        });
    if let Err(e) = terrain {
        restore(&f);
        return Err(e);
    }
    // TW-11: an enhancement over the conserved fold, so a failure is logged, never fatal
    let traffic = || -> Result<(), String> {
        let lock = st.terrain.site_lock(site);
        let _g = lock
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let prior =
            traffic_memory::snapshot_site(&st.cfg.data_dir, site).map_err(|e| e.to_string())?;
        let Some(mem) = traffic_from_run(st, &prep.planned, legs, site, mid)? else {
            return Ok(());
        };
        traffic_memory::save_site(&st.cfg.data_dir, &mem).map_err(|e| e.to_string())?;
        if let Err(e) = st.world.record_execution_event(
            &st.terrain,
            &format!("SIM traffic hardening: {mid}"),
            None,
            None,
            &stamp,
            0.0,
        ) {
            let _ = traffic_memory::restore_site(&st.cfg.data_dir, site, prior.as_deref());
            return Err(e);
        }
        Ok(())
    };
    if let Err(e) = traffic() {
        eprintln!("SIM traffic fold for {mid} failed (non-fatal): {e}");
    }
    Ok(())
}

fn s<'a>(v: &'a Value, k: &str) -> &'a str {
    v[k].as_str().unwrap_or("")
}

fn runs_dir(st: &AppState, owner: &str) -> Result<std::path::PathBuf, String> {
    ns_dir(&st.cfg.data_dir, "runs", Namespace::Sandbox(Some(owner)))
}

/// Persist a run per owner (Python `save_run`), keeping the newest [`RUN_MAX`].
fn save_run(st: &AppState, run_id: &str, rec: &Value, owner: &str) -> Result<(), String> {
    let dir = runs_dir(st, owner)?;
    let id = slug(run_id);
    let path = dir.join(format!("{id}.json"));
    let (by, at) = owner_meta(&path, owner, st.clock.now());
    let mut doc = rec.as_object().cloned().unwrap_or_default();
    doc.insert("run_id".into(), json!(id));
    doc.insert("created_by".into(), by);
    doc.insert("created_at".into(), at);
    let text =
        stewie_twin::pyjson::dumps_indent(&Value::Object(doc), 1).map_err(|e| format!("{e:?}"))?;
    crate::atomic_write(&path, text.as_bytes())?;
    let mut files: Vec<(std::time::SystemTime, std::path::PathBuf)> = std::fs::read_dir(&dir)
        .map_err(|e| e.to_string())?
        .flatten()
        .filter(|e| e.path().extension().is_some_and(|x| x == "json"))
        .filter_map(|e| Some((e.metadata().ok()?.modified().ok()?, e.path())))
        .collect();
    if files.len() > RUN_MAX {
        files.sort();
        for (_, p) in &files[..files.len() - RUN_MAX] {
            let _ = std::fs::remove_file(p);
        }
    }
    Ok(())
}

fn load_run(st: &AppState, run_id: &str, owner: &str) -> Result<Option<Value>, String> {
    let path = runs_dir(st, owner)?.join(format!("{}.json", slug(run_id)));
    crate::objects::load(&path)
}

async fn run(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let (head, bytes) = split(req, st.settings.max_body).await;
    run_on(&st, &head, bytes)
        .await
        .unwrap_or_else(IntoResponse::into_response)
}

#[allow(clippy::too_many_lines)] // the Python's route, step by step
async fn run_on(
    st: &AppState,
    head: &Head,
    bytes: Result<axum::body::Bytes, ApiError>,
) -> Result<Response, ApiError> {
    let body = parse_body(&bytes?)?;
    let identity = require_director(st, head)?;
    let mut with_orders = body.clone();
    if let Some(Value::Object(o)) = &mut with_orders {
        o.entry("orders").or_insert_with(|| json!([]));
    }
    let v = body_model(with_orders.as_ref(), RUN)?;
    let raw = body
        .and_then(|b| b.as_object().cloned())
        .unwrap_or_default();
    let site = v["site"].as_str().unwrap_or("haworth").to_owned();
    let prep = match prepare(st, &v, &raw, &identity).await? {
        Ok(p) => p,
        Err(r) => return Ok(r),
    };
    let p = &prep.planned;
    let cl = st
        .planning
        .closed_loop(&p.mission, &p.inputs, &p.plan, &p.dem(), None)
        .map_err(|e| err(StatusCode::BAD_REQUEST, e))?;
    let legs = cl.leg_records(p.ctx.reserve_frac);
    let sim = run_sim_execution(&legs);
    let mut b = [0_u8; 6];
    st.entropy.fill(&mut b);
    let run_id = b.iter().fold(String::new(), |mut out, x| {
        use std::fmt::Write as _;
        let _ = write!(out, "{x:02x}");
        out
    });
    let mid = prep.mission_id.clone();
    let executed: Vec<Value> = sim
        .executed
        .iter()
        .map(|(i, a)| json!({"leg": i, "action": a}))
        .collect();
    let backend = p.mission.physics_backend_id.clone();
    let rec = json!({"label": "sim", "final_state": sim.final_state, "transitions": sim.transitions,
                     "n_legs_total": sim.n_legs, "safed": sim.safed, "nonnominal_legs": sim.nonnominal,
                     "executed_legs": executed, "mission_id": mid, "site": site, "bound_revision": prep.bound,
                     "physics_backend": backend, "trajectory_kind": "forecast"});
    let at = format!("{mid}@{site}");
    let fail = |status: StatusCode, body: Value| Ok((status, axum::Json(body)).into_response());
    if let Err(e) = record_action(
        st,
        &identity,
        "executive.run.intent",
        &at,
        &format!("prepare SIM run {run_id}"),
        ("released", "pending"),
        &format!(
            "run_id={run_id};revision={}",
            prep.bound.as_deref().unwrap_or("legacy-unbound")
        ),
    ) {
        return fail(
            StatusCode::SERVICE_UNAVAILABLE,
            json!({"ok": false, "error": format!("audit unavailable; SIM run was not committed: {e}")}),
        );
    }
    let battery = p.ctx.battery_j;
    let belief: Map<String, Value> = [
        ("x", json!(cl.final_xy.0)),
        ("y", json!(cl.final_xy.1)),
        ("pos_sigma_m", json!(cl.pos_sigma_m)),
        ("energy_J", json!(battery)),
        ("energy_sigma_J", json!(cl.energy_sigma_j)),
        ("drum_kg", json!(0.0)),
        ("drum_sigma_kg", json!(0.0)),
        ("tasks_done", json!(legs.len())),
        ("tasks_total", json!(p.plan.trips.len())),
        ("t_s", json!(p.plan.totals.time_s)),
        ("battery_j", json!(battery)),
    ]
    .into_iter()
    .map(|(k, v)| (k.to_owned(), v))
    .collect();
    if let Err(e) = commit(st, &prep, &rec, &legs, belief, &site, sim.safed) {
        eprintln!("world-state commit for SIM run {run_id} failed; run not persisted: {e}");
        let _ = record_action(
            st,
            &identity,
            "executive.run.abort",
            &at,
            "world-state commit failed",
            ("pending", "aborted"),
            &format!("run_id={run_id};error=RuntimeError"),
        );
        return fail(
            StatusCode::INTERNAL_SERVER_ERROR,
            json!({"ok": false, "error": format!("world-state commit failed: {e}")}),
        );
    }
    if let Err(e) = save_run(st, &run_id, &rec, &identity) {
        let _ = record_action(
            st,
            &identity,
            "executive.run.abort",
            &at,
            "run-record persistence failed",
            ("pending", "world_committed_run_record_failed"),
            &format!("run_id={run_id};error=OSError"),
        );
        return fail(
            StatusCode::INTERNAL_SERVER_ERROR,
            json!({"ok": false, "error": format!("run record persistence failed after world commit: {e}")}),
        );
    }
    log(
        st,
        head,
        &identity,
        "executive.run",
        &format!("{run_id} {mid}: {} ({} legs)", sim.final_state, sim.n_legs),
    );
    if let Err(e) = record_action(
        st,
        &identity,
        "executive.run",
        &at,
        &format!("SIM run {run_id}"),
        ("pending", sim.final_state),
        &format!(
            "run_id={run_id};legs={};safed={}",
            sim.n_legs,
            if sim.safed { "True" } else { "False" }
        ),
    ) {
        return fail(
            StatusCode::SERVICE_UNAVAILABLE,
            json!({"ok": false, "run_id": run_id, "world_committed": true,
                                                            "run_persisted": true,
                                                            "error": format!("SIM run committed but audit result append failed: {e}")}),
        );
    }
    // MP-07: the eight preconditions from the real released, rehearsed and run state
    let conserves = physics_attribution(&backend)["conserves_mass"] == true;
    let completed = sim.final_state == "completed";
    let pre = [
        ("required_capabilities", prep.objectives > 0),
        ("assigned_assets", prep.objectives > 0),
        ("physics_score", conserves),
        ("resource_budget", !sim.safed),
        ("rehearsal_result", !legs.is_empty()),
        ("safety_check", completed),
        ("approval_record", true),
        (
            "rollback_abort_rule",
            matches!(sim.final_state, "completed" | "safed"),
        ),
    ];
    let unmet: Vec<&str> = pre.iter().filter(|(_, ok)| !ok).map(|(k, _)| *k).collect();
    let executability = json!({"executable": unmet.is_empty(), "unmet": unmet,
                               "preconditions": pre.iter().map(|(k, v)| ((*k).to_owned(), json!(v))).collect::<Map<_, _>>()});
    let (predicted, observed, tolerance) = (
        sum(&legs, "nominal_J"),
        sum(&legs, "true_J"),
        sum(&legs, "energy_sigma_J"),
    );
    let reconciliation = reconcile(predicted, observed, tolerance, &format!("run:{run_id}"));
    if reconciliation["implicates_model"] == true {
        let n = reconciliation["proposals"].as_array().map_or(0, Vec::len);
        let residual = observed - predicted;
        record_action(
            st,
            &identity,
            "executive.reconcile",
            &at,
            "energy residual exceeds estimator sigma -> model-update proposed",
            (
                &format!("predicted={predicted:.1}J"),
                &format!("observed={observed:.1}J"),
            ),
            &format!("residual={residual:.1}J;proposals={n}"),
        )
        .map_err(|e| err(StatusCode::INTERNAL_SERVER_ERROR, e))?;
    }
    // EG-05 §29.5: a token only when all six training-to-live steps hold, bound to the released content hash
    let live = [
        ("mission_created", prep.objectives > 0),
        ("simulation_branch", true),
        ("rehearsal_completed", !legs.is_empty()),
        ("physics_passed", conserves),
        ("safety_passed", completed),
        ("human_approval", true),
    ];
    let live_unmet: Vec<&str> = live.iter().filter(|(_, ok)| !ok).map(|(k, _)| *k).collect();
    let rev = s(&prep.released.signed, "content_hash").to_owned();
    let live_token = if live_unmet.is_empty() {
        let (issued, ttl) = (st.clock.now(), st.settings.rc.live_token_ttl_s);
        json!({"issued": true, "mission_id": mid, "revision_id": rev,
               "signature": crate::rc_routes::sign_live(&st.rc.token_secret, &mid, &rev, issued, ttl),
               "issued_at": issued, "ttl_s": ttl, "expires_at": issued + ttl})
    } else {
        json!({"issued": false, "reason": format!("training-to-live gate not passed for {}: unmet steps {}",
                                                  py_repr(&mid), stewie_twin::pyjson::repr_list(&live_unmet))})
    };
    let mut out = rec.as_object().cloned().unwrap_or_default();
    for (k, v) in [
        ("ok", json!(true)),
        ("run_id", json!(run_id)),
        ("executability", executability),
        ("reconciliation", reconciliation),
        ("live_token", live_token),
        ("physics_attribution", physics_attribution(&backend)),
        (
            "terramechanics_comparison",
            terramechanics_comparison(&legs),
        ),
        ("skipped", json!(prep.skipped)),
    ] {
        out.insert(k.to_owned(), v);
    }
    Ok(axum::Json(Value::Object(out)).into_response())
}

/// A stored run of the caller's own; operator+.
async fn run_get(
    State(st): State<Arc<AppState>>,
    Path(run_id): Path<String>,
    req: Request,
) -> Response {
    let head = Head::of(&req);
    crate::app::blocking(st, move |st| {
        let identity = require_role(st, &head, "operator")?;
        match load_run(st, &run_id, &identity)
            .map_err(|e| err(StatusCode::INTERNAL_SERVER_ERROR, e))?
        {
            Some(Value::Object(mut rec)) => {
                rec.insert("ok".into(), json!(true));
                Ok(axum::Json(Value::Object(rec)).into_response())
            }
            _ => Err(err(
                StatusCode::NOT_FOUND,
                format!("no run {}", py_repr(&run_id)),
            )),
        }
    })
    .await
}

const STREAM_Q: Model = Model {
    fields: &[Field(
        "interval_s",
        Kind::Float {
            gt: None,
            ge: None,
            le: None,
            default: Some(0.6),
        },
    )],
    forbid_extra: false,
};

/// SSE playback of a stored run's execution events, paced by `interval_s` (0..5 s), resuming after `Last-Event-ID`.
async fn run_stream(
    State(st): State<Arc<AppState>>,
    Path(run_id): Path<String>,
    Query(q): Query<Vec<(String, String)>>,
    req: Request,
) -> Response {
    let head = Head::of(&req);
    let prep = (|| -> Result<(Value, f64), ApiError> {
        let identity = require_role(&st, &head, "operator")?;
        let raw = crate::spec_routes::query(&q, STREAM_Q)?;
        let interval = raw
            .get("interval_s")
            .and_then(|v| crate::validate::as_float(v).ok())
            .unwrap_or(0.6);
        let rec = load_run(&st, &run_id, &identity)
            .map_err(|e| err(StatusCode::INTERNAL_SERVER_ERROR, e))?
            .ok_or_else(|| {
                err(
                    StatusCode::NOT_FOUND,
                    format!("no run {}", py_repr(&run_id)),
                )
            })?;
        Ok((rec, interval.clamp(0.0, 5.0)))
    })();
    let (rec, interval) = match prep {
        Ok(p) => p,
        Err(e) => return e.into_response(),
    };
    let resume = head
        .headers
        .get("last-event-id")
        .and_then(|v| v.to_str().ok())
        .filter(|t| !t.is_empty() && t.bytes().all(|c| c.is_ascii_digit()))
        .and_then(|t| t.parse::<usize>().ok());
    let events = execution_events(&rec);
    let n = events.len();
    let mut frames: Vec<String> = events
        .iter()
        .enumerate()
        .filter(|(i, _)| resume.is_none_or(|r| *i > r))
        .map(|(i, ev)| {
            let data = ordered(&[
                ("kind", dumps(&ev["kind"])),
                ("detail", dumps(&ev["detail"])),
                ("outcome", dumps(&ev["outcome"])),
                ("t_s", dumps(&ev["t_s"])),
                ("vehicle_id", dumps(&json!("ipex"))),
                ("leg", i.to_string()),
            ]);
            format!("id: {i}\ndata: {data}\n\n")
        })
        .collect();
    let done = ordered(&[
        ("done", "true".to_owned()),
        ("final_state", dumps(&rec["final_state"])),
        ("n_legs_total", dumps(&rec["n_legs_total"])),
        ("trajectory_kind", dumps(&rec["trajectory_kind"])),
        ("safed", dumps(&rec["safed"])),
    ]);
    frames.push(format!("id: {n}\ndata: {done}\n\n"));
    let pause = std::time::Duration::from_secs_f64(interval);
    // the Python sleeps after each leg event, not after the terminal one
    let stream =
        futures_util::stream::iter(frames.into_iter().enumerate()).then(move |(i, f)| async move {
            if i > 0 && !pause.is_zero() {
                tokio::time::sleep(pause).await;
            }
            Ok::<_, std::convert::Infallible>(f)
        });
    (
        [
            (header::CONTENT_TYPE, "text/event-stream; charset=utf-8"),
            (header::CACHE_CONTROL, "no-cache"),
            (header::HeaderName::from_static("x-accel-buffering"), "no"),
        ],
        Body::from_stream(stream),
    )
        .into_response()
}

/// The SIM run routes.
pub fn routes() -> Router<Arc<AppState>> {
    Router::new()
        .route("/executive/run", post(run))
        .route("/executive/run/{run_id}", get(run_get))
        .route("/executive/run/{run_id}/stream", get(run_stream))
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    #[test]
    fn reconciliation_matches_the_pythons_proposals() {
        // expected values from `reconcile_prediction(pred, obs, quantity="energy_J", sensor_tolerance=tol, ...)`
        let model = super::reconcile(100.0, 130.0, 10.0, "run:x");
        assert_eq!(model["implicates_model"], true);
        assert_eq!(
            model["proposals"],
            json!([
                {"proposal_id": "run:x:world:energy_J", "state": "proposed", "confidence": 0.75, "model_error": true,
                 "change": "set world belief energy_J = 130.0 (predicted 100.0, residual 30.0)"},
                {"proposal_id": "run:x:model:energy_J", "state": "proposed", "confidence": 0.75, "model_error": true,
                 "change": "recalibrate model for energy_J: predicted 100.0 vs observed 130.0 (residual 30.0 exceeds \
                            sensor tolerance 10.0)"}
            ])
        );
        let world = super::reconcile(100.0, 104.5, 10.0, "run:x");
        assert_eq!(world["implicates_model"], false);
        assert_eq!(
            world["proposals"],
            json!([{"proposal_id": "run:x:world:energy_J", "state": "proposed", "confidence": 0.310_344_827_586_206_9,
                    "model_error": false, "change": "set world belief energy_J = 104.5 (predicted 100.0, residual 4.5)"}])
        );
        assert_eq!(
            super::reconcile(5.0, 5.0, 1.0, "run:x")["proposals"],
            json!([])
        );
    }
}
