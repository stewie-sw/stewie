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
use stewie_traverse::nav::py_round;

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
        Field("keepouts", Kind::TupleList { n: 3, max: 512 }),
        Field("rocks", Kind::TupleList { n: 3, max: 512 }),
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
        let cmd = nav::track_plan(&plan, cap("v_max", configured(st)?.drive_speed_ms), cap("omega_max", nav::DEFAULT_OMEGA_MAX), 1.0);
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

const PAIRS: Kind = Kind::TupleList { n: 2, max: 512 };

/// Python `ReactRequest` (`extra="forbid"`).
const REACT: Model = Model {
    fields: &[
        Field("pose", Kind::FloatPair),
        Field(
            "heading_rad",
            bounded(None, Some((-7.0, "-7")), (7.0, "7"), None),
        ),
        Field("goal", Kind::FloatPair),
        Field("planned_path", Kind::TupleList { n: 2, max: 4096 }),
        Field("rocks", Kind::TupleList { n: 3, max: 512 }),
        Field("known_hazards", PAIRS),
        Field("keepouts", Kind::TupleList { n: 3, max: 512 }),
        Field(
            "sensor_range_m",
            bounded(Some((0.0, "0")), None, (1e4, "10000"), Some(18.0)),
        ),
        Field(
            "deviation_max_m",
            bounded(None, Some((0.0, "0")), (1e4, "10000"), Some(8.0)),
        ),
        Field(
            "clearance_m",
            bounded(None, Some((0.0, "0")), (100.0, "100"), Some(1.0)),
        ),
        Field(
            "horizon_m",
            bounded(Some((0.0, "0")), None, (1000.0, "1000"), Some(8.0)),
        ),
    ],
    forbid_extra: true,
};

fn pairs(v: &Value) -> Vec<(f64, f64)> {
    v.as_array()
        .into_iter()
        .flatten()
        .map(|p| (p[0].as_f64().unwrap_or(0.0), p[1].as_f64().unwrap_or(0.0)))
        .collect()
}

fn arc_wire(arc: &[[f64; 3]]) -> Value {
    json!(
        arc.iter()
            .map(|p| json!([py_round(p[0], 4), py_round(p[1], 4), py_round(p[2], 5)]))
            .collect::<Vec<_>>()
    )
}

/// NV-05: the reactive replan decision, the updated keep-outs, the deviation, and the local arc when one avoids
/// them.
async fn react(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let (head, bytes) = split(req, st.settings.max_body).await;
    blocking(st, move |st| {
        let body = parse_body(&bytes?)?;
        let who = require_auth(st, &head)?;
        let v = body_model(body.as_ref(), REACT)?;
        let pair = |k: &str| (v[k][0].as_f64().unwrap_or(0.0), v[k][1].as_f64().unwrap_or(0.0));
        let num = |k: &str| v[k].as_f64().unwrap_or(0.0);
        let out = nav::react(
            pair("pose"),
            num("heading_rad"),
            pair("goal"),
            &pairs(&v["planned_path"]),
            &circles(&v["rocks"]),
            &pairs(&v["known_hazards"]),
            &circles(&v["keepouts"]),
            num("sensor_range_m"),
            num("deviation_max_m"),
            num("clearance_m"),
            num("horizon_m"),
        );
        log(st, &head, &who, "nav.react", &format!("replan={} scope={}", py_bool(out.replan), out.scope));
        let keepouts: Vec<Value> =
            out.keepouts.iter().map(|(x, y, r)| json!([py_round(*x, 3), py_round(*y, 3), py_round(*r, 3)])).collect();
        Ok(axum::Json(json!({
            "ok": true, "replan": out.replan, "scope": out.scope, "n_new_hazards": out.n_new_hazards,
            "deviation_m": py_round(out.deviation_m, 3), "keepouts": keepouts,
            "local_arc": out.local_plan.as_ref().map(|p| arc_wire(&p.arc)),
        }))
        .into_response())
    })
    .await
}

/// FS-05: the navigation contract, each stage naming the function of this server that implements it (all
/// compiled in, so present), and the live planner binary as the gated external tier (D-R171).
async fn contract(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let head = crate::app::Head::of(&req);
    blocking(st, move |st| {
        require_auth(st, &head)?;
        let mut stages: Vec<Value> = [
            ("global_route", "stewie_traverse::route::route_leg"),
            ("local_trajectory", "stewie_traverse::nav::plan_local"),
            ("tracker", "stewie_traverse::nav::track_plan"),
            ("recovery", "stewie_traverse::nav::recommend"),
            ("keepouts", "stewie_traverse::route::route_leg"),
            ("negative_obstacles", "stewie_traverse::costmap::negative_obstacle_mask"),
            ("illumination_risk", "stewie_traverse::layers::incidence_angle_deg"),
            ("slip_energy_budget", "stewie_plan::sim"),
            ("ros_action_lowering", "stewie_plan::lowering::lower_plan_ir"),
        ]
        .iter()
        .map(|(stage, seam)| json!({"stage": stage, "seam": seam, "present": true}))
        .collect();
        stages.push(json!({"stage": "live_planner_binary", "seam": "Autoware/Nav2 (external ROS host)",
                           "present": false,
                           "note": "gated: needs the live planner binary on a ROS / Space ROS host"}));
        Ok(axum::Json(json!({"ok": true, "version": "1.0", "stages": stages, "on_host_complete": true})).into_response())
    })
    .await
}

/// Python `NavRunRequest` (`extra="forbid"`).
const NAV_RUN: Model = Model {
    fields: &[
        Field("start", Kind::FloatPair),
        Field("goal", Kind::FloatPair),
        Field(
            "site",
            Kind::Str {
                min: 0,
                max: 64,
                nullable: false,
                default: Some("haworth"),
            },
        ),
        Field("keepouts", Kind::TupleList { n: 3, max: 512 }),
        Field("rocks", Kind::TupleList { n: 3, max: 512 }),
        Field(
            "max_slope_deg",
            bounded(Some((0.0, "0")), None, (89.0, "89"), Some(25.0)),
        ),
        Field(
            "dt",
            bounded(Some((0.0, "0")), None, (60.0, "60"), Some(2.0)),
        ),
        Field(
            "horizon_m",
            bounded(Some((0.0, "0")), None, (1000.0, "1000"), Some(8.0)),
        ),
        Field(
            "clearance_m",
            bounded(None, Some((0.0, "0")), (100.0, "100"), Some(1.0)),
        ),
        Field(
            "goal_tol_m",
            bounded(Some((0.0, "0")), None, (100.0, "100"), Some(2.0)),
        ),
        Field(
            "max_ticks",
            Kind::Int {
                ge: 1,
                le: 4000,
                default: 2000,
            },
        ),
    ],
    forbid_extra: true,
};

/// The canonical lunar terramechanics set the navigation slip ladder reads (Python `_TM_PARAMS`, exported).
fn constants_soil() -> Result<stewie_physics::soil::SoilParams, String> {
    let c: Value = serde_json::from_str(include_str!(
        "../../stewie-contracts/fixtures/terramechanics_constants.json"
    ))
    .map_err(|e| format!("terramechanics_constants: {e}"))?;
    let f = |k: &str| {
        c[k].as_f64()
            .ok_or_else(|| format!("terramechanics_constants has no {k}"))
    };
    Ok(stewie_physics::soil::SoilParams {
        k_c: f("k_c")?,
        k_phi: f("k_phi")?,
        n: f("n_sinkage")?,
        cohesion_pa: f("cohesion")?,
        phi_rad: f("phi_rad")?,
        k_shear_m: f("k_shear")?,
        slip_c1: f("slip_c1")?,
        slip_c2: f("slip_c2")?,
        rho_surface: f("rho_surface")?,
        rho_deep: f("rho_deep")?,
        analog: false,
    })
}

/// The wire's bound on the executed path (the overlay needs its shape).
const TRAJ_WIRE_MAX: usize = 400;

/// FS-05 end to end: route the global corridor on the real site DEM, then drive it as a closed loop against the
/// same slope and drop-off hazard, the speed derated by the slip ladder, and score the executed path against the
/// route (a read-only preview: no state, no rover command).
#[allow(
    clippy::too_many_lines,
    clippy::cast_possible_truncation,
    clippy::cast_sign_loss,
    clippy::cast_possible_wrap
)] // the route's reply; grid sizes
async fn run(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let (head, bytes) = split(req, st.settings.max_body).await;
    blocking(st, move |st| {
        use stewie_traverse::costmap::{CostmapOptions, Keepout, slope_costmap};
        let body = parse_body(&bytes?)?;
        let who = require_auth(st, &head)?;
        let v = body_model(body.as_ref(), NAV_RUN)?;
        let bad = |e: String| crate::app::err(axum::http::StatusCode::BAD_REQUEST, e);
        let site = v["site"].as_str().unwrap_or("haworth").to_owned();
        let Some((dem, origin)) = st.terrain.moon_dem(&site) else {
            return Err(bad(format!("no DEM bundle for site {}", crate::operators::py_repr(&site))));
        };
        let cfg = configured(st)?;
        let m = st.planning.mission(&json!({"name": "nav", "body": "moon", "orders": [{"action": "nav", "kind": "goto", "x": 0.0, "y": 0.0}]})).map_err(bad)?;
        let inputs = st.planning.inputs(&m).map_err(|(_, e)| bad(e))?;
        let rover_mass = stewie_plan::trips::context(&m, &st.planning.fleet, &inputs.params).map_err(bad)?.rover_mass_kg;
        let pair = |k: &str| (v[k][0].as_f64().unwrap_or(0.0), v[k][1].as_f64().unwrap_or(0.0));
        let num = |k: &str| v[k].as_f64().unwrap_or(0.0);
        let (start, goal, max_slope) = (pair("start"), pair("goal"), num("max_slope_deg"));
        let keepouts = circles(&v["keepouts"]);
        let rocks = circles(&v["rocks"]);
        let opts = CostmapOptions { max_slope_deg: max_slope, slip_alpha: 2.0, max_drop_m: Some(2.0), illumination: None,
                                    map_uncertainty: None };
        let grid = stewie_traverse::route::Dem { z: &dem.z, width: dem.cols, height: dem.rows, cell_m: dem.cell_m, origin };
        let ko: Vec<Keepout> = keepouts.iter().map(|(x, y, r)| Keepout::Circle { x: *x, y: *y, r: *r }).collect();
        let leg = stewie_traverse::route::route_leg(grid, start, goal, &opts, 20.0, &ko).map_err(bad)?;
        let terms: Map<String, Value> = leg
            .breakdown
            .iter()
            .map(|(k, vals)| ((*k).to_owned(), json!(vals.iter().map(|x| py_round(*x, 4)).collect::<Vec<_>>())))
            .collect();
        let wire = |p: &(f64, f64)| json!([py_round(p.0, 3), py_round(p.1, 3)]);
        let mut reply = json!({"ok": true, "reached": false, "arrived": false, "reason": "no global corridor",
            "site": site, "waypoints": leg.waypoints.iter().map(wire).collect::<Vec<_>>(), "trajectory": [],
            "routed_m": py_round(leg.routed_m, 3), "n_ticks": 0, "n_recoveries": 0, "recovery_events": [],
            "deviation": {"mean_m": 0.0, "max_m": 0.0}, "route_terms": terms, "stages": ["global_route"]});
        if leg.reached && leg.waypoints.len() >= 2 {
            let cm = slope_costmap(&dem.z, dem.cols, dem.rows, dem.cell_m, &opts).map_err(bad)?;
            let slope = lunar_dem::slope_deg_grid(&dem.z, dem.cols, dem.rows, dem.cell_m);
            // the navigation slip ladder reads the canonical constants, not the body registry (Python _TM_PARAMS)
            let soil = constants_soil().map_err(|e| crate::app::err(axum::http::StatusCode::INTERNAL_SERVER_ERROR, e))?;
            let (cols, rows, cell) = (dem.cols as i64, dem.rows as i64, dem.cell_m);
            let at = |x: f64, y: f64| {
                let c = ((origin.0 + x) / cell).round_ties_even() as i64;
                let r = ((origin.1 + y) / cell).round_ties_even() as i64;
                (0..rows).contains(&r).then_some(()).and((0..cols).contains(&c).then_some(())).map(|()| (r * cols + c) as usize)
            };
            let blocked = |x: f64, y: f64| at(x, y).is_none_or(|i| !cm.passable[i]);
            let scale = |x: f64, y: f64| {
                at(x, y).map_or(1.0, |i| (1.0 - inputs.slip(&soil, slope[i], rover_mass).unwrap_or(0.0)).clamp(0.05, 1.0))
            };
            let mut route = leg.waypoints.clone();
            if let Some(last) = route.last()
                && (last.0 - goal.0).hypot(last.1 - goal.1) > 1e-6
            {
                route.push(goal);
            }
            let params = nav::DriveParams {
                v_max: cfg.drive_speed_ms,
                omega_max: nav::DEFAULT_OMEGA_MAX,
                dt: num("dt"),
                horizon_m: num("horizon_m"),
                lookahead_m: 6.0,
                clearance_m: num("clearance_m"),
                goal_tol_m: num("goal_tol_m"),
                max_ticks: v["max_ticks"].as_u64().unwrap_or(2000) as usize,
            };
            let drive = nav::drive_route(&route, &blocked, &scale, &rocks, &keepouts, &params);
            let (dev_mean, dev_max) = nav::deviation(&route, &drive.trajectory);
            let mut stages: Vec<&str> = drive.stages.clone();
            stages.extend(["global_route", "deviation"]);
            stages.sort_unstable();
            stages.dedup();
            let step = (drive.trajectory.len() / TRAJ_WIRE_MAX).max(1);
            let mut traj: Vec<Value> = drive.trajectory.iter().step_by(step).map(wire).collect();
            if step > 1
                && let Some(last) = drive.trajectory.last()
            {
                traj.push(wire(last));
            }
            let events: Vec<Value> = drive
                .recovery_events
                .iter()
                .map(|e| json!({"tick": e.tick, "reason": e.reason, "scope": e.scope, "xy": [py_round(e.pose.0, 3), py_round(e.pose.1, 3)]}))
                .collect();
            for (k, val) in [
                ("reached", json!(true)),
                ("arrived", json!(drive.arrived)),
                ("reason", json!(drive.reason)),
                ("trajectory", json!(traj)),
                ("n_ticks", json!(drive.n_ticks)),
                ("n_recoveries", json!(drive.recovery_events.len())),
                ("recovery_events", json!(events)),
                ("deviation", json!({"mean_m": dev_mean, "max_m": dev_max})),
                ("stages", json!(stages)),
            ] {
                reply[k] = val;
            }
        }
        let msg = format!(
            "{site}: reached={} n_recoveries={}",
            py_bool(reply["reached"].as_bool().unwrap_or(false)),
            reply["n_recoveries"]
        );
        log(st, &head, &who, "nav.run", &msg);
        Ok(axum::Json(reply).into_response())
    })
    .await
}

/// The navigation routes.
pub fn routes() -> Router<Arc<AppState>> {
    Router::new()
        .route("/nav/run", post(run))
        .route("/nav/react", post(react))
        .route("/nav/contract", axum::routing::get(contract))
        .route("/nav/faults", post(faults))
        .route("/nav/executive", post(executive))
        .route("/nav/local_plan", post(local_plan))
}
