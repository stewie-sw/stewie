//! The planning routes (RW-55b14; Python `routers.plan`): the plan request and its checks shared by every plan route
//! (validation as the Python's `PlanRequest`, an edit session's keep-outs folded in, the keep-out cap, the heavy
//! quota), the plan on the site's composed as-built surface, and the views over it: the per-trip math worksheet
//! (`/plan/math`) and the reusable `GoTo` command tape (`/plan/commands`).

use std::sync::Arc;

use axum::Router;
use axum::extract::{Request, State};
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::routing::post;
use serde_json::{Map, Value, json};
use stewie_plan::assemble::{Plan, PlanConfig, plan_and_simulate};
use stewie_plan::mission::Mission;
use stewie_plan::report::{energy_ledger, report_totals};
use stewie_plan::trips::{Context, TripKind, context};
use stewie_traverse::route::Dem;

use crate::app::{ApiError, AppState, Head, blocking, err, log, parse_body, split};
use crate::planning::Inputs;
use crate::validate::{self, Field, Kind, Model};

const ORDER: Model = Model {
    fields: &[
        Field(
            "action",
            Kind::Str {
                min: 0,
                max: 120,
                nullable: true,
                default: None,
            },
        ),
        Field(
            "kind",
            Kind::Str {
                min: 0,
                max: 40,
                nullable: true,
                default: None,
            },
        ),
        Field(
            "x",
            Kind::Float {
                gt: None,
                ge: None,
                le: None,
                default: Some(0.0),
            },
        ),
        Field(
            "y",
            Kind::Float {
                gt: None,
                ge: None,
                le: None,
                default: Some(0.0),
            },
        ),
        Field(
            "footprint_m2",
            Kind::Float {
                gt: Some((0.0, "0")),
                ge: None,
                le: Some((1e8, "100000000.0")),
                default: Some(1.0),
            },
        ),
        Field(
            "depth_m",
            Kind::Float {
                gt: None,
                ge: Some((-100.0, "-100.0")),
                le: Some((100.0, "100.0")),
                default: Some(0.0),
            },
        ),
    ],
    forbid_extra: false,
};

/// The Python's `PlanRequest` (extra fields allowed: the mission's own).
const PLAN_REQUEST: Model = Model {
    fields: &[
        Field(
            "name",
            Kind::Str {
                min: 0,
                max: 200,
                nullable: false,
                default: Some("mission"),
            },
        ),
        Field(
            "body",
            Kind::Str {
                min: 0,
                max: 40,
                nullable: false,
                default: Some("moon"),
            },
        ),
        Field(
            "orders",
            Kind::List {
                min: 0,
                max: 1000,
                item: &ORDER,
            },
        ),
        Field(
            "algorithm",
            Kind::Str {
                min: 0,
                max: 40,
                nullable: false,
                default: Some("nearest"),
            },
        ),
        Field(
            "objective",
            Kind::Str {
                min: 0,
                max: 40,
                nullable: false,
                default: Some("time"),
            },
        ),
        Field(
            "lat",
            Kind::Opt(&Kind::Float {
                gt: None,
                ge: Some((-90.0, "-90.0")),
                le: Some((90.0, "90.0")),
                default: None,
            }),
        ),
        Field(
            "lon",
            Kind::Opt(&Kind::Float {
                gt: None,
                ge: Some((-360.0, "-360.0")),
                le: Some((360.0, "360.0")),
                default: None,
            }),
        ),
        Field(
            "vehicles",
            Kind::Int {
                ge: 1,
                le: 16,
                default: 1,
            },
        ),
        Field(
            "site",
            Kind::Str {
                min: 0,
                max: 40,
                nullable: false,
                default: Some("haworth"),
            },
        ),
        Field(
            "max_traverse_slope_deg",
            Kind::Float {
                gt: None,
                ge: Some((5.0, "5.0")),
                le: Some((45.0, "45.0")),
                default: Some(25.0),
            },
        ),
        Field(
            "charger_capacity",
            Kind::Int {
                ge: 1,
                le: 8,
                default: 1,
            },
        ),
        Field(
            "edit_session",
            Kind::Str {
                min: 0,
                max: 64,
                nullable: true,
                default: None,
            },
        ),
        Field("anchor_xy", Kind::Opt(&Kind::FloatPair)),
    ],
    forbid_extra: false,
};

/// The Python's `model_dump()` of a request: the validated fields (defaults filled) with the client's extra fields
/// kept, each order likewise.
fn dump(raw: &Map<String, Value>, valid: Map<String, Value>) -> Map<String, Value> {
    let mut out = valid;
    if let (Some(Value::Array(orders)), Some(Value::Array(raw_orders))) =
        (out.get_mut("orders"), raw.get("orders"))
    {
        for (o, r) in orders.iter_mut().zip(raw_orders) {
            if let (Value::Object(o), Value::Object(r)) = (o, r) {
                for (k, v) in r {
                    o.entry(k.clone()).or_insert_with(|| v.clone());
                }
            }
        }
    }
    for (k, v) in raw {
        out.entry(k.clone()).or_insert_with(|| v.clone());
    }
    out
}

/// A plan request checked as the Python's: the body, auth and the heavy quota, the model, the edit session's
/// keep-outs folded in, then the keep-out cap.
async fn request(
    st: &AppState,
    h: &Head,
    bytes: &[u8],
) -> Result<(String, Map<String, Value>), ApiError> {
    let mut body = parse_body(&bytes.to_vec().into())?;
    let identity = st.heavy(h)?;
    // the Python's `orders` defaults to an empty list (`default_factory=list`)
    if let Some(Value::Object(o)) = body.as_mut() {
        o.entry("orders").or_insert_with(|| json!([]));
    }
    let valid = validate::model(body.as_ref(), PLAN_REQUEST)
        .map_err(|e| err(StatusCode::BAD_REQUEST, e))?;
    let raw = body
        .as_ref()
        .and_then(Value::as_object)
        .cloned()
        .unwrap_or_default();
    let mut payload = dump(&raw, valid);
    let sid = payload
        .get("edit_session")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_owned();
    let extra = crate::edit_session::planner_keepouts(st, &sid, payload.get("anchor_xy")).await?;
    if !extra.is_empty() {
        let mut keepouts = payload
            .get("keepouts")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        keepouts.extend(extra);
        payload.insert("keepouts".to_owned(), Value::Array(keepouts));
    }
    let n = payload
        .get("keepouts")
        .and_then(Value::as_array)
        .map_or(0, Vec::len);
    if n > st.settings.max_keepouts {
        return Err(err(
            StatusCode::PAYLOAD_TOO_LARGE,
            format!(
                "too many keep-outs ({n} > {}); split the mission",
                st.settings.max_keepouts
            ),
        ));
    }
    Ok((identity, payload))
}

/// A planned mission with what its views need.
struct Planned {
    mission: Mission,
    inputs: Inputs,
    ctx: Context,
    plan: Plan,
}

/// Plan `payload` with the planner's defaults (Python `MP.plan(mission, dem=, dem_origin=)`: nearest, time, one
/// rover, the 25 deg slope budget) on the site's composed as-built surface (#242). The planner needs real terrain
/// (D-R85): a body or site without a DEM is refused rather than planned flat.
fn plan(st: &AppState, payload: &Map<String, Value>) -> Result<Planned, ApiError> {
    let bad = |e: String| err(StatusCode::BAD_REQUEST, e);
    let m = st
        .planning
        .mission(&Value::Object(payload.clone()))
        .map_err(bad)?;
    let inputs = st.planning.inputs(&m).map_err(|(unconfigured, e)| {
        if unconfigured {
            err(StatusCode::SERVICE_UNAVAILABLE, e)
        } else {
            bad(e)
        }
    })?;
    let site = payload
        .get("site")
        .and_then(Value::as_str)
        .unwrap_or("haworth")
        .to_owned();
    if m.body != "moon" {
        return Err(bad(format!(
            "body {} has no terrain model to plan on; the planner needs a real DEM (D-R85)",
            m.body
        )));
    }
    let (dem, origin) = st.terrain.moon_dem(&site).ok_or_else(|| {
        bad(format!(
            "site {site} has no imported DEM to plan on; the planner needs a real DEM (D-R85)"
        ))
    })?;
    let view = st.terrain.current_terrain_view(&site, &dem, origin);
    let d = Dem {
        z: &view.heights,
        width: dem.cols,
        height: dem.rows,
        cell_m: view.cell_m,
        origin,
    };
    let cfg = PlanConfig {
        algorithm: "nearest",
        objective: "time",
        vehicles: 1,
        idle_power_w: inputs.idle_power_w,
        reallocate_stranded: true,
    };
    let plan =
        plan_and_simulate(&m, &st.planning.fleet, &inputs.build(d, 25.0), &cfg).map_err(bad)?;
    let ctx = context(&m, &st.planning.fleet, &inputs.params).map_err(bad)?;
    Ok(Planned {
        mission: m,
        inputs,
        ctx,
        plan,
    })
}

/// The plan's totals as the Python's `PlanResult.totals` of a single-rover plan: the core figures, the energy
/// ledger, the routed legs and the report figures.
fn totals(p: &Planned) -> Value {
    let t = &p.plan.totals;
    let routes: Vec<Value> = p
        .plan
        .meta
        .routes
        .iter()
        .map(|r| {
            json!({"from_xy": [r.from.0, r.from.1], "to_xy": [r.to.0, r.to.1], "reached": r.reached,
                   "waypoints": r.waypoints.iter().map(|w| json!([w.0, w.1])).collect::<Vec<_>>()})
        })
        .collect();
    let mut out = json!({
        "time_s": t.time_s, "mass_kg": t.mass_kg, "energy_J": t.energy_j, "charges": t.charges,
        "distance_m": t.distance_m, "avg_power_w": t.avg_power_w, "survival_energy_J": t.survival_energy_j,
        "idle_power_w": p.inputs.idle_power_w, "feasible": t.feasible, "infeasible_reasons": t.infeasible_reasons,
        "algorithm": t.algorithm, "resolved_algorithm": t.resolved_algorithm, "optimality": t.optimality,
        "objective_exact": t.objective_exact, "solved_metric": t.solved_metric, "n_precedence": t.n_precedence,
        "objective": t.objective, "vehicles": t.vehicles, "makespan_s": t.makespan_s,
        "vehicle_conflicts": t.vehicle_conflicts, "charger_conflicts": t.charger_conflicts,
        "vehicles_detail": [], "energy_ledger": energy_ledger(&p.plan, &p.ctx), "routes": routes,
        "blocked_legs": p.plan.meta.blocked_legs,
    });
    let report = report_totals(
        &p.mission,
        &p.plan,
        &p.ctx,
        p.inputs.body_density(),
        &p.inputs.profile,
        &p.inputs.report,
    );
    if let (Some(o), Value::Object(r)) = (out.as_object_mut(), report) {
        for (k, v) in r {
            o.entry(k).or_insert(v);
        }
    }
    out
}

fn kind_name(k: TripKind) -> &'static str {
    match k {
        TripKind::Goto => "goto",
        TripKind::Import => "import",
        TripKind::Dig => "dig",
        TripKind::CutFill => "cutfill",
    }
}

/// The per-trip math worksheet (Python `planner_views.plan_math`): every energy and time term with its formula and
/// substituted numbers.
fn worksheet(p: &Planned, cfg: &crate::planning::PlannerConfig) -> Value {
    let (dig_j, drive_j) = (cfg.ipex_dig_j_per_kg, cfg.ipex_drive_j_per_m);
    let (rate, g) = (cfg.dig_rate_kg_s, p.inputs.params.gravity_ms2);
    let r = stewie_twin::numpy::round;
    let legs: Vec<Value> = p
        .plan
        .trips
        .iter()
        .map(|tr| {
            let mass = tr.mass_kg;
            let mut terms = Vec::new();
            if tr.dig_e != 0.0 {
                terms.push(json!({"name": "dig energy", "unit": "J", "formula": "mass * DIG_J_PER_KG",
                    "substituted": format!("{mass:.1} * {dig_j:.1} = {:.1}", mass * dig_j), "value": r(tr.dig_e, 1)}));
            }
            if tr.dig_t != 0.0 {
                terms.push(json!({"name": "dig time", "unit": "s", "formula": "mass / DIG_RATE_KG_S",
                    "substituted": format!("{mass:.1} / {rate:.4} = {:.1}", mass / rate), "value": r(tr.dig_t, 1)}));
            }
            if tr.haul_m != 0.0 {
                terms.push(json!({"name": "haul distance", "unit": "m",
                    "formula": "2 * leg_distance * n_loads  (out + back per load)",
                    "substituted": format!("= {:.1}", tr.haul_m), "value": r(tr.haul_m, 1)}));
            }
            if tr.haul_e != 0.0 {
                terms.push(json!({"name": "haul energy", "unit": "J",
                    "formula": "haul_m * DRIVE_J_PER_M / (1 - slip)  (slip robs ground/wheel)",
                    "substituted": format!("~ {:.1} * {drive_j:.1} / (1-slip) = {:.1}", tr.haul_m, tr.haul_e),
                    "value": r(tr.haul_e, 1)}));
            }
            if tr.lift_e != 0.0 {
                terms.push(json!({"name": "lift energy", "unit": "J", "formula": "mass * g * dh  (exact gravity climb)",
                    "substituted": format!("{mass:.1} * {g:.3} * dh = {:.1}", tr.lift_e), "value": r(tr.lift_e, 1)}));
            }
            let label = if tr.label.is_empty() { kind_name(tr.kind).to_owned() } else { tr.label.clone() };
            json!({"label": label, "kind": kind_name(tr.kind), "site": [tr.site.0, tr.site.1], "terms": terms})
        })
        .collect();
    json!({
        "constants": {"DIG_J_PER_KG": r(dig_j, 1), "DRIVE_J_PER_M": r(drive_j, 2), "DRIVE_SPEED_MS": cfg.drive_speed_ms,
                      "DIG_RATE_KG_S": r(rate, 4), "g_m_s2": r(g, 3)},
        "legs": legs,
        "totals": totals(p),
    })
}

/// The plan as a reusable `GoTo` tape (Python `rc_contract.commands_from_plan`): each trip's work site, then its
/// distinct haul destination, in cells of `cell_m` (row = y / cell, col = x / cell).
fn tape(p: &Planned, cell_m: f64) -> Vec<Value> {
    let mut cmds = Vec::new();
    for tr in &p.plan.trips {
        let mut waypoints = vec![tr.site];
        if tr.dest != tr.site {
            waypoints.push(tr.dest);
        }
        for (x, y) in waypoints {
            cmds.push(json!({"kind": "goto", "leg_id": cmds.len(), "goal_row": y / cell_m, "goal_col": x / cell_m,
                             "v_max_mps": 0.3, "goal_radius_cells": 1.0}));
        }
    }
    cmds
}

fn reply(r: Result<Response, ApiError>) -> Response {
    r.unwrap_or_else(IntoResponse::into_response)
}

/// The per-trip math worksheet of the planned mission (any authenticated caller, under the heavy quota).
async fn plan_math(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let (h, bytes) = split(req, st.settings.max_body).await;
    let checked = match bytes {
        Ok(b) => request(&st, &h, &b).await,
        Err(e) => Err(e),
    };
    match checked {
        Err(e) => e.into_response(),
        Ok((identity, payload)) => {
            blocking(st, move |st| {
                let cfg = *st
                    .planning
                    .config
                    .as_ref()
                    .map_err(|e| err(StatusCode::SERVICE_UNAVAILABLE, e.clone()))?;
                let p = plan(st, &payload)?;
                let mut out = worksheet(&p, &cfg);
                out["ok"] = json!(true);
                log(st, &h, &identity, "plan.math", &p.mission.name);
                Ok(axum::Json(out).into_response())
            })
            .await
        }
    }
}

/// The planned mission as a reusable `GoTo` command tape (any authenticated caller, under the heavy quota).
async fn plan_commands(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let (h, bytes) = split(req, st.settings.max_body).await;
    let checked = match bytes {
        Ok(b) => request(&st, &h, &b).await,
        Err(e) => Err(e),
    };
    reply(match checked {
        Err(e) => Err(e),
        Ok((identity, payload)) => Ok(blocking(st, move |st| {
            let p = plan(st, &payload)?;
            let cell_m = 5.0; // the Moon's LOLA cell, as the Python's (the only body the planner plans on, D-R85)
            let cmds = tape(&p, cell_m);
            log(
                st,
                &h,
                &identity,
                "plan.commands",
                &format!("{}: {} commands", p.mission.name, cmds.len()),
            );
            Ok(axum::Json(json!({"ok": true, "cell_m": cell_m, "commands": cmds})).into_response())
        })
        .await),
    })
}

/// The planning routes.
pub fn routes() -> Router<Arc<AppState>> {
    Router::new()
        .route("/plan/math", post(plan_math))
        .route("/plan/commands", post(plan_commands))
}
