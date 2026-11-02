//! The navigation routes (RW-55b24; Python `routers/nav`): `POST /nav/faults` (NV-08), `/nav/executive` (NV-09 with
//! the NV-06/07 recovery and the NV-05 replan scope) and `/nav/local_plan` (NV-03 arc with its NV-04 command).
//! Read-only compute, so any authenticated caller; every request is observation only (`extra="forbid"`).

use std::sync::Arc;

use axum::Router;
use axum::extract::{Request, State};
use axum::response::{IntoResponse, Response};
use axum::routing::post;
use serde_json::{Map, Value, json};
use stewie_traverse::nav;

use crate::app::{AppState, blocking, body_model, log, parse_body, require_auth, split};
use crate::validate::{Field, Kind, Model};

const fn bounded(
    gt: Option<(f64, &'static str)>,
    ge: Option<(f64, &'static str)>,
    le: (f64, &'static str),
    default: Option<f64>,
) -> Kind {
    Kind::Float {
        gt,
        ge,
        le: Some(le),
        default,
    }
}

const TIP: Kind = bounded(None, Some((-90.0, "-90")), (90.0, "90"), None);
const UNIT: Kind = bounded(None, Some((0.0, "0")), (1.0, "1"), None);
const SIGMA: Kind = bounded(None, Some((0.0, "0")), (1e4, "10000"), None);
const TEMP: Kind = bounded(None, Some((-273.0, "-273")), (1000.0, "1000"), None);
const FLAG: Kind = Kind::Bool { default: false };
const PROGRESS: Kind = bounded(None, Some((0.0, "0")), (10.0, "10"), None);
const STALL: Kind = bounded(None, Some((0.0, "0")), (1e6, "1000000"), None);
const SCOPE: Kind = Kind::Pattern {
    pattern: "^(local|global)$",
    options: &["local", "global"],
};
const CAP: Kind = bounded(Some((0.0, "0")), None, (10.0, "10"), None);

/// Python `FaultRequest` (`extra="forbid"`).
const FAULTS: Model = Model {
    fields: &[
        Field("tip_margin_deg", Kind::Opt(&TIP)),
        Field("slip", Kind::Opt(&UNIT)),
        Field("loc_sigma_m", Kind::Opt(&SIGMA)),
        Field("battery_frac", Kind::Opt(&UNIT)),
        Field("temp_c", Kind::Opt(&TEMP)),
        Field("actuator_ok", Kind::Opt(&FLAG)),
    ],
    forbid_extra: true,
};

/// Python `ExecutiveRequest(FaultRequest)`.
const EXECUTIVE: Model = Model {
    fields: &[
        Field("tip_margin_deg", Kind::Opt(&TIP)),
        Field("slip", Kind::Opt(&UNIT)),
        Field("loc_sigma_m", Kind::Opt(&SIGMA)),
        Field("battery_frac", Kind::Opt(&UNIT)),
        Field("temp_c", Kind::Opt(&TEMP)),
        Field("actuator_ok", Kind::Opt(&FLAG)),
        Field("command_acked", Kind::Bool { default: true }),
        Field("plan_accepted", Kind::Bool { default: true }),
        Field("progress_ratio", Kind::Opt(&PROGRESS)),
        Field("stall_duration_s", Kind::Opt(&STALL)),
        Field("expected_progress_ratio", Kind::Opt(&UNIT)),
        Field("planner_failed", Kind::Bool { default: false }),
        Field("reactive_scope", Kind::Opt(&SCOPE)),
    ],
    forbid_extra: true,
};

/// Python `LocalPlanRequest` (`extra="forbid"`).
const LOCAL_PLAN: Model = Model {
    fields: &[
        Field("pose", Kind::FloatPair),
        Field(
            "heading_rad",
            bounded(None, Some((-7.0, "-7")), (7.0, "7"), None),
        ),
        Field("goal", Kind::FloatPair),
        Field("keepouts", Kind::FloatTripleList { max: 512 }),
        Field("rocks", Kind::FloatTripleList { max: 512 }),
        Field(
            "horizon_m",
            bounded(Some((0.0, "0")), None, (1000.0, "1000"), Some(8.0)),
        ),
        Field(
            "clearance_m",
            bounded(None, Some((0.0, "0")), (100.0, "100"), Some(1.0)),
        ),
        Field("v_max", Kind::Opt(&CAP)),
        Field("omega_max", Kind::Opt(&CAP)),
    ],
    forbid_extra: true,
};

/// Python's builtin `round(x, n)` (correctly rounded through the decimal form).
fn py_round(x: f64, n: usize) -> f64 {
    format!("{x:.n$}").parse().unwrap_or(x)
}

fn py_bool(b: bool) -> &'static str {
    if b { "True" } else { "False" }
}

fn telemetry(v: &Map<String, Value>) -> nav::Telemetry {
    let f = |k: &str| v.get(k).and_then(Value::as_f64);
    nav::Telemetry {
        tip_margin_deg: f("tip_margin_deg"),
        slip: f("slip"),
        loc_sigma_m: f("loc_sigma_m"),
        battery_frac: f("battery_frac"),
        temp_c: f("temp_c"),
        actuator_ok: v.get("actuator_ok").and_then(Value::as_bool),
    }
}

/// The configured planner parameters: the pack reserve and the drive speed come from the mission configuration
/// (RW-30, D-R115), so an unconfigured server answers 503 as `/plan` does.
fn configured(st: &AppState) -> Result<crate::planning::PlannerConfig, crate::app::ApiError> {
    st.planning
        .config
        .clone()
        .map_err(|e| crate::app::err(axum::http::StatusCode::SERVICE_UNAVAILABLE, e))
}

fn circles(v: &Value) -> Vec<nav::Circle> {
    v.as_array()
        .into_iter()
        .flatten()
        .map(|c| {
            (
                c[0].as_f64().unwrap_or(0.0),
                c[1].as_f64().unwrap_or(0.0),
                c[2].as_f64().unwrap_or(0.0),
            )
        })
        .collect()
}

/// NV-08: the active faults and their rollup.
async fn faults(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let (head, bytes) = split(req, st.settings.max_body).await;
    blocking(st, move |st| {
        let body = parse_body(&bytes?)?;
        let who = require_auth(st, &head)?;
        let v = body_model(body.as_ref(), FAULTS)?;
        let active = nav::classify_faults(&telemetry(&v), configured(st)?.reserve_frac);
        let summary = nav::fault_summary(&active);
        let msg = format!(
            "{} active, safety_critical={}",
            active.len(),
            py_bool(summary["safety_critical"].as_bool().unwrap_or(false))
        );
        log(st, &head, &who, "nav.faults", &msg);
        Ok(axum::Json(json!({"ok": true, "faults": active, "summary": summary})).into_response())
    })
    .await
}

/// NV-09: one executive step, the recovery recommendation folded in when the progress telemetry is complete.
async fn executive(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let (head, bytes) = split(req, st.settings.max_body).await;
    blocking(st, move |st| {
        let body = parse_body(&bytes?)?;
        let who = require_auth(st, &head)?;
        let v = body_model(body.as_ref(), EXECUTIVE)?;
        let active = nav::classify_faults(&telemetry(&v), configured(st)?.reserve_frac);
        let number = |k: &str| v.get(k).and_then(Value::as_f64);
        let flag = |k: &str, d: bool| v.get(k).and_then(Value::as_bool).unwrap_or(d);
        let recovery = match (
            number("progress_ratio"),
            number("stall_duration_s"),
            number("expected_progress_ratio"),
        ) {
            (Some(p), Some(s), Some(e)) => {
                Some(nav::recommend(p, s, e, flag("planner_failed", false)))
            }
            _ => None,
        };
        let out = nav::executive_step(
            &active,
            flag("command_acked", true),
            flag("plan_accepted", true),
            recovery.as_ref(),
            v.get("reactive_scope").and_then(Value::as_str),
        );
        log(
            st,
            &head,
            &who,
            "nav.executive",
            out["action"].as_str().unwrap_or(""),
        );
        let mut resp = out.as_object().cloned().unwrap_or_default();
        resp.insert("ok".into(), json!(true));
        resp.insert("fault_summary".into(), nav::fault_summary(&active));
        resp.insert("faults".into(), json!(active));
        Ok(axum::Json(Value::Object(resp)).into_response())
    })
    .await
}

/// NV-03/04: the best feasible local arc toward the goal and its bounded drive command, or `feasible: false`
/// so the global router takes over.
async fn local_plan(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let (head, bytes) = split(req, st.settings.max_body).await;
    blocking(st, move |st| {
        let body = parse_body(&bytes?)?;
        let who = require_auth(st, &head)?;
        let v = body_model(body.as_ref(), LOCAL_PLAN)?;
        let pair = |k: &str| (v[k][0].as_f64().unwrap_or(0.0), v[k][1].as_f64().unwrap_or(0.0));
        let num = |k: &str| v[k].as_f64().unwrap_or(0.0);
        let plan = nav::plan_local(
            pair("pose"),
            num("heading_rad"),
            pair("goal"),
            None,
            &circles(&v["keepouts"]),
            &circles(&v["rocks"]),
            num("clearance_m"),
            num("horizon_m"),
        );
        log(st, &head, &who, "nav.local_plan", &format!("feasible={}", py_bool(plan.feasible)));
        if !plan.feasible {
            return Ok(axum::Json(json!({"ok": true, "feasible": false,
                "reason": "all sampled arcs blocked (terrain / keep-out / rock)",
                "n_sampled": plan.n_sampled, "n_feasible": plan.n_feasible}))
            .into_response());
        }
        let cap = |k: &str, d: f64| v[k].as_f64().unwrap_or(d);
        let cmd = nav::track_plan(&plan, cap("v_max", configured(st)?.drive_speed_ms), cap("omega_max", nav::DEFAULT_OMEGA_MAX));
        let end = plan.arc[plan.arc.len() - 1];
        let arc: Vec<Value> =
            plan.arc.iter().map(|p| json!([py_round(p[0], 4), py_round(p[1], 4), py_round(p[2], 5)])).collect();
        Ok(axum::Json(json!({
            "ok": true, "feasible": true, "curvature": plan.curvature,
            "endpoint": [py_round(end[0], 4), py_round(end[1], 4)], "heading_end": py_round(end[2], 5),
            "progress_m": py_round(plan.progress_m, 4), "n_sampled": plan.n_sampled, "n_feasible": plan.n_feasible,
            "arc": arc,
            "command": {"v_cmd": py_round(cmd.v_cmd, 5), "omega_cmd": py_round(cmd.omega_cmd, 5),
                        "expected_speed_ms": py_round(cmd.expected_speed_ms, 5),
                        "duration_s": py_round(cmd.duration_s, 3), "arc_length_m": py_round(cmd.arc_length_m, 4)},
        }))
        .into_response())
    })
    .await
}

/// The navigation routes.
pub fn routes() -> Router<Arc<AppState>> {
    Router::new()
        .route("/nav/faults", post(faults))
        .route("/nav/executive", post(executive))
        .route("/nav/local_plan", post(local_plan))
}
