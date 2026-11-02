//! The planning routes (RW-55b14; Python `routers.plan`): the plan request and its checks shared by every plan route
//! (validation as the Python's `PlanRequest`, an edit session's keep-outs folded in, the keep-out cap, the heavy
//! quota), the plan on the site's composed as-built surface, and the views over it: the per-trip math worksheet
//! (`/plan/math`) and the reusable `GoTo` command tape (`/plan/commands`).

use std::sync::{Arc, LazyLock};

use axum::Router;
use axum::extract::{Request, State};
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::routing::post;
use hmac::{Hmac, Mac};
use serde_json::{Map, Value, json};
use sha2::Sha256;
use stewie_plan::acceptance::{AcceptanceParams, execute_plan_acceptance, validate_plan};
use stewie_plan::assemble::{FleetTotals, Plan, PlanConfig, plan_and_simulate};
use stewie_plan::mission::Mission;
use stewie_plan::report::{energy_ledger, report_totals};
use stewie_plan::trips::{Context, context};
use stewie_traverse::route::Dem;
use stewie_twin::terrain_view::TerrainView;

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

/// Keep only what the client set (pydantic's `model_dump(exclude_unset=True)`), in each order too.
fn set_only(valid: &mut Map<String, Value>, raw: &Map<String, Value>) {
    valid.retain(|k, _| raw.contains_key(k));
    if let (Some(Value::Array(orders)), Some(Value::Array(raw_orders))) =
        (valid.get_mut("orders"), raw.get("orders"))
    {
        for (o, r) in orders.iter_mut().zip(raw_orders) {
            if let (Value::Object(o), Value::Object(r)) = (o, r) {
                o.retain(|k, _| r.contains_key(k));
            }
        }
    }
}

/// A plan request checked as the Python's: the body, auth and the heavy quota, the model, the edit session's
/// keep-outs folded in, then the keep-out cap. Returns the payload the mission is read from (only the fields the
/// client set when `exclude_unset`, as `/plan` dumps it) and the full model with its defaults.
async fn request(
    st: &AppState,
    h: &Head,
    bytes: &[u8],
    exclude_unset: bool,
) -> Result<(String, Map<String, Value>, Map<String, Value>), ApiError> {
    let mut body = parse_body(&bytes.to_vec().into())?;
    let identity = st.heavy(h)?;
    let raw = body
        .as_ref()
        .and_then(Value::as_object)
        .cloned()
        .unwrap_or_default();
    // the Python's `orders` defaults to an empty list (`default_factory=list`)
    if let Some(Value::Object(o)) = body.as_mut() {
        o.entry("orders").or_insert_with(|| json!([]));
    }
    let valid = validate::model(body.as_ref(), PLAN_REQUEST)
        .map_err(|e| err(StatusCode::BAD_REQUEST, e))?;
    let full = valid.clone();
    let mut valid = valid;
    if exclude_unset {
        set_only(&mut valid, &raw);
    }
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
    Ok((identity, payload, full))
}

/// A planned mission with what its views need.
struct Planned {
    mission: Mission,
    inputs: Inputs,
    ctx: Context,
    plan: Plan,
    /// The composed as-built surface it was planned on, row-major `cols` x `rows`.
    view: TerrainView,
    cols: usize,
    rows: usize,
    origin: (f64, f64),
    site: String,
}

impl Planned {
    fn dem(&self) -> Dem<'_> {
        Dem {
            z: &self.view.heights,
            width: self.cols,
            height: self.rows,
            cell_m: self.view.cell_m,
            origin: self.origin,
        }
    }
}

/// How a plan is asked for (the Python `MP.plan` keywords and the `/plan` site pick).
struct Opts<'a> {
    algorithm: &'a str,
    objective: &'a str,
    vehicles: usize,
    max_traverse_slope_deg: f64,
    /// A globe site pick (lon, lat) [deg] that replaces the flattest anchor.
    lonlat: Option<(f64, f64)>,
}

/// The planner's defaults (Python `MP.plan(mission, dem=, dem_origin=)`): nearest, time, one rover, 25 deg.
const DEFAULTS: Opts<'static> = Opts {
    algorithm: "nearest",
    objective: "time",
    vehicles: 1,
    max_traverse_slope_deg: 25.0,
    lonlat: None,
};

/// Plan `payload` with the planner's defaults on the site's composed as-built surface (#242).
fn plan(st: &AppState, payload: &Map<String, Value>) -> Result<Planned, ApiError> {
    plan_with(st, payload, &DEFAULTS)
}

/// Plan `payload` as `opts` asks on the site's composed as-built surface (#242). The planner needs real terrain
/// (D-R85): a body or site without a DEM is refused rather than planned flat.
fn plan_with(
    st: &AppState,
    payload: &Map<String, Value>,
    opts: &Opts<'_>,
) -> Result<Planned, ApiError> {
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
    let (dem, mut origin) = st.terrain.moon_dem(&site).ok_or_else(|| {
        bad(format!(
            "site {site} has no imported DEM to plan on; the planner needs a real DEM (D-R85)"
        ))
    })?;
    if let Some((lon, lat)) = opts.lonlat {
        // M11: the pick's pixel-metres, absolute (the anchor frame), so no anchor is subtracted
        origin = st
            .terrain
            .latlon_to_order(&dem, (0.0, 0.0), lon, lat)
            .map_err(bad)?;
    }
    let view = st.terrain.current_terrain_view(&site, &dem, origin);
    let (cols, rows) = (dem.cols, dem.rows);
    let d = Dem {
        z: &view.heights,
        width: cols,
        height: rows,
        cell_m: view.cell_m,
        origin,
    };
    let cfg = PlanConfig {
        algorithm: opts.algorithm,
        objective: opts.objective,
        vehicles: opts.vehicles,
        idle_power_w: inputs.idle_power_w,
        reallocate_stranded: true,
    };
    let plan = plan_and_simulate(
        &m,
        &st.planning.fleet,
        &inputs.build(d, opts.max_traverse_slope_deg),
        &cfg,
    )
    .map_err(bad)?;
    let ctx = context(&m, &st.planning.fleet, &inputs.params).map_err(bad)?;
    Ok(Planned {
        mission: m,
        inputs,
        ctx,
        plan,
        view,
        cols,
        rows,
        origin,
        site,
    })
}

fn xy((x, y): (f64, f64)) -> Value {
    json!([x, y])
}

/// The fleet planner's totals (Python `plan_multi`'s `totals.update`): the queue waits, the conflicts, the replan
/// trigger and each rover's own figures; the resource and observation fields only when the mission declares them.
fn fleet_totals(f: &FleetTotals, m: &Mission) -> Map<String, Value> {
    let (resources, observations) = (!m.shared_resources.is_empty(), !m.observations.is_empty());
    let detail: Vec<Value> = f
        .detail
        .iter()
        .map(|d| {
            let h = &d.health;
            let mut v = json!({
                "vehicle": d.vehicle, "n_trips": d.n_trips, "time_s": d.time_s, "energy_J": d.energy_j,
                "distance_m": d.distance_m, "charges": d.charges, "charger_wait_s": d.charger_wait_s,
                "crowd_wait_s": d.crowd_wait_s, "precedence_wait_s": d.precedence_wait_s,
                "track": d.track.iter().copied().map(xy).collect::<Vec<_>>(),
                "health": {"feasible": h.feasible, "min_batt_frac": h.min_batt_frac, "charges": h.charges,
                           "health": h.health, "infeasible_reasons": h.infeasible_reasons},
            });
            if resources {
                v["resource_wait_s"] = json!(d.resource_wait_s);
            }
            if observations {
                v["observation_wait_s"] = json!(d.observation_wait_s);
            }
            v
        })
        .collect();
    let mut out = json!({
        "makespan_parallel_s": f.makespan_parallel_s, "charger_wait_s": f.charger_wait_s,
        "charger_queue_modeled": true, "crowd_wait_s": f.crowd_wait_s, "crowd_resequenced": f.crowd_wait_s > 0.0,
        "precedence_wait_s": f.precedence_wait_s, "precedence_split": f.precedence_wait_s > 0.0,
        "vehicles_detail": detail, "fleet_needs_replan": f.fleet_needs_replan, "fleet_replanned": f.fleet_replanned,
        "unreallocatable_trips": f.unreallocatable_trips, "temporal_conflicts": f.temporal_conflicts,
        "haul_path_conflicts": f.haul_path_conflicts,
    });
    if resources {
        out["resource_wait_s"] = json!(f.resource_wait_s);
        out["resource_waits"] = Value::Object(
            f.resource_waits
                .iter()
                .map(|(k, w)| (k.clone(), json!(w)))
                .collect(),
        );
        out["shared_resources_modeled"] = json!(true);
    }
    if observations {
        out["observation_wait_s"] = json!(f.observation_wait_s);
        out["observation_vantages"] = Value::Object(
            f.observation_vantages
                .iter()
                .map(|(k, v)| (k.clone(), json!(v)))
                .collect(),
        );
        out["observation_vantages_modeled"] = json!(true);
    }
    match out {
        Value::Object(o) => o,
        _ => Map::new(),
    }
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
    if let (Some(o), Some(f)) = (out.as_object_mut(), &t.fleet) {
        o.extend(fleet_totals(f, &p.mission));
    }
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
            let label = if tr.label.is_empty() { tr.kind.name().to_owned() } else { tr.label.clone() };
            json!({"label": label, "kind": tr.kind.name(), "site": [tr.site.0, tr.site.1], "terms": terms})
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
        Ok(b) => request(&st, &h, &b, false).await,
        Err(e) => Err(e),
    };
    match checked {
        Err(e) => e.into_response(),
        Ok((identity, payload, _)) => {
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
        Ok(b) => request(&st, &h, &b, false).await,
        Err(e) => Err(e),
    };
    reply(match checked {
        Err(e) => Err(e),
        Ok((identity, payload, _)) => Ok(blocking(st, move |st| {
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

/// The spine contracts' version (Python `stewie.contracts.SPINE_VERSION`), stamped on the typed `PlanResult`.
const SPINE_VERSION: &str = "1.0";

/// The source commit a plan names (Python `_source_commit`): `$STEWIE_COMMIT`, else `git rev-parse` in the
/// checkout, else honestly unknown.
static COMMIT: LazyLock<String> = LazyLock::new(|| {
    let set = std::env::var("STEWIE_COMMIT").unwrap_or_default();
    if !set.trim().is_empty() {
        return set.trim().to_owned();
    }
    std::process::Command::new("git")
        .args(["rev-parse", "--short", "HEAD"])
        .current_dir(env!("CARGO_MANIFEST_DIR"))
        .output()
        .ok()
        .filter(|o| o.status.success())
        .map(|o| String::from_utf8_lossy(&o.stdout).trim().to_owned())
        .filter(|c| !c.is_empty())
        .unwrap_or_else(|| "unknown".to_owned())
});

/// Delete plan reports older than `STEWIE_REPORTS_TTL_S` (Python `services.prune_reports`); returns how many went.
pub fn prune_reports(st: &AppState) -> usize {
    let ttl = st.settings.reports_ttl_s;
    let Ok(entries) = std::fs::read_dir(st.cfg.data_dir.join("reports")) else {
        return 0;
    };
    if ttl <= 0.0 {
        return 0;
    }
    let now = st.clock.now();
    let mut removed = 0;
    for e in entries.flatten() {
        let path = e.path();
        let Ok(meta) = std::fs::metadata(&path) else {
            continue;
        };
        let age = meta
            .modified()
            .ok()
            .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
            .map(|t| now - t.as_secs_f64());
        if meta.is_file() && age.is_some_and(|a| a > ttl) && std::fs::remove_file(&path).is_ok() {
            removed += 1;
        }
    }
    removed
}

/// The report's opaque stem (Python `_plan_stem`, S-06): `report-` and 24 hex of the HMAC of the request payload
/// under the session-signing secret, so a report name cannot be derived from public mission knowledge, yet
/// re-planning the same request rewrites the same file.
fn plan_stem(st: &AppState, payload: &Map<String, Value>) -> Result<String, String> {
    let text =
        stewie_twin::pyjson::dumps(&Value::Object(payload.clone())).map_err(|e| e.to_string())?;
    let mut mac =
        Hmac::<Sha256>::new_from_slice(&st.cfg.signing_secret()).map_err(|e| e.to_string())?;
    mac.update(text.as_bytes());
    let hex = mac
        .finalize()
        .into_bytes()
        .iter()
        .fold(String::new(), |mut s, b| {
            use std::fmt::Write as _;
            let _ = write!(s, "{b:02x}");
            s
        });
    Ok(format!("report-{}", &hex[..24]))
}

/// The closed-loop overlay of the mission (Python `_autonomy_perception`): one rover at the 25 deg budget with the
/// request's sequencer, on the same surface and anchor. Additive: any refusal folds both blocks out.
fn overlay(
    st: &AppState,
    payload: &Map<String, Value>,
    p: &Planned,
    opts: &Opts<'_>,
) -> (Value, Value) {
    let solo;
    let q = if opts.vehicles == 1 && opts.max_traverse_slope_deg == DEFAULTS.max_traverse_slope_deg
    {
        p
    } else {
        let o = Opts {
            vehicles: 1,
            max_traverse_slope_deg: DEFAULTS.max_traverse_slope_deg,
            ..*opts
        };
        match plan_with(st, payload, &o) {
            Ok(r) => {
                solo = r;
                &solo
            }
            Err(e) => {
                eprintln!(
                    "autonomy/perception block folded out (additive; /plan still served): {}",
                    e.1
                );
                return (Value::Null, Value::Null);
            }
        }
    };
    st.planning
        .autonomy_perception(&q.mission, &q.inputs, &q.plan, &q.dem())
        .unwrap_or_else(|e| {
            eprintln!("autonomy/perception block folded out (additive; /plan still served): {e}");
            (Value::Null, Value::Null)
        })
}

/// The whole plan response (Python `_plan_impl`): one plan, and every view of it.
#[allow(clippy::too_many_lines)] // the Python's response, key by key
fn compose(
    st: &AppState,
    payload: &Map<String, Value>,
    full: &Map<String, Value>,
) -> Result<Response, ApiError> {
    prune_reports(st);
    let bad = |e: String| err(StatusCode::BAD_REQUEST, e);
    let text =
        |k: &str, d: &'static str| full.get(k).and_then(Value::as_str).unwrap_or(d).to_owned();
    let (algorithm, objective) = (text("algorithm", "nearest"), text("objective", "time"));
    let num = |k: &str| full.get(k).and_then(Value::as_f64);
    #[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)]
    // the model bounds it to 1..=16
    let vehicles = num("vehicles").map_or(1, |v| v as usize);
    let opts = Opts {
        algorithm: &algorithm,
        objective: &objective,
        vehicles,
        max_traverse_slope_deg: num("max_traverse_slope_deg").unwrap_or(25.0),
        lonlat: num("lon").zip(num("lat")),
    };
    let p = plan_with(st, payload, &opts)?;
    let dem = p.dem();
    let acceptance = p.inputs.acceptance();
    let mut params = AcceptanceParams::default();
    if let Some(tol) = p.mission.accept_flatness_tol_m {
        params.accept_flatness_tol_m = tol; // CP-04: the mission's compiled tolerance
    }
    let validation = validate_plan(&p.mission, Some(dem), &acceptance, &params).map_err(bad)?;
    let timeline = st
        .planning
        .timeline(
            &p.mission,
            &p.plan,
            p.origin,
            (&algorithm, &objective, vehicles),
            &COMMIT,
        )
        .map_err(bad)?;
    let endurance = st
        .planning
        .endurance(&p.mission, &p.inputs, Some(&dem), "psr_tower", None)
        .map_err(bad)?;
    let (autonomy, perception) = overlay(st, payload, &p, &opts);
    let mut plan_ir = stewie_plan::ir::plan_ir(
        &p.mission,
        &p.plan,
        &p.ctx,
        dem,
        opts.max_traverse_slope_deg,
    )
    .map_err(bad)?;
    let (ordered, _) = execute_plan_acceptance(
        &p.mission,
        &p.plan.trips,
        dem,
        &acceptance,
        &AcceptanceParams::default(),
    )
    .map_err(bad)?;
    let raw_totals = totals(&p);
    let md = st
        .planning
        .markdown(&p.mission, &p.inputs, &p.plan, &raw_totals, &endurance)
        .map_err(bad)?;
    let stem = plan_stem(st, payload).map_err(bad)?;
    let dir = st.cfg.data_dir.join("reports");
    std::fs::create_dir_all(&dir)
        .and_then(|()| std::fs::write(dir.join(format!("{stem}.md")), md))
        .map_err(|e| {
            err(
                StatusCode::INTERNAL_SERVER_ERROR,
                format!("the plan report: {e}"),
            )
        })?;
    // the Python's `_totals_json`: every non-bool number a float
    let totals = match raw_totals {
        Value::Object(o) => Value::Object(
            o.into_iter()
                .map(|(k, v)| match v.as_f64() {
                    Some(f) if v.is_number() => (k, json!(f)),
                    _ => (k, v),
                })
                .collect(),
        ),
        v => v,
    };
    let feasible = totals["feasible"].as_bool().unwrap_or(true);
    let reasons = totals["infeasible_reasons"].clone();
    if !feasible {
        // H-03: no executable action list for a plan with an unreachable or battery-infeasible leg
        plan_ir = json!({"executable": false, "feasible": false, "infeasible_reasons": reasons, "actions": [],
            "note": "execution IR suppressed (H-03): the plan has an infeasible leg -- unreachable corridor or \
                     battery-infeasible transit"});
    }
    let provenance = timeline["provenance"].clone();
    if feasible {
        plan_ir["provenance"] = provenance.clone(); // CT-07: the input hash of the one plan
    }
    let f = |k: &str| totals[k].as_f64().unwrap_or(0.0);
    #[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)]
    // whole counts the planner reports
    let int = |k: &str, d: u64| match totals[k].as_f64() {
        Some(v) if v != 0.0 => v as u64,
        _ => d,
    };
    let id = provenance["input_sha256"]
        .as_str()
        .map_or("", |h| &h[..h.len().min(16)]);
    let plan_result = json!({
        "schema_version": SPINE_VERSION, "plan_id": if id.is_empty() { "plan" } else { id },
        "feasible": feasible, "n_orders": p.mission.orders.len(), "vehicles": int("vehicles", 1),
        "makespan_s": f("makespan_s"), "energy_j": f("energy_J"), "mass_moved_kg": f("cut_kg") + f("fill_kg"),
        "blocked_legs": int("blocked_legs", 0), "recharges": int("charges", 0), "drum_cycles": int("drum_cycles", 0),
        "cut_passes": int("cut_passes", 1),
        "resolved_algorithm": totals["resolved_algorithm"].as_str().filter(|a| !a.is_empty())
            .or_else(|| totals["algorithm"].as_str()).unwrap_or(""),
    });
    Ok(axum::Json(json!({
        "ok": true, "feasible": feasible, "infeasible_reasons": reasons, "plan_result": plan_result,
        "mode": "DEM_KNOWN_POSE_MISSION_SIM", "site": p.site, "body": p.mission.body,
        "terrain_source": format!("{}_dem", p.site), "md": format!("/reports/{stem}.md"), "totals": totals, "validation": validation,
        "timeline": timeline, "endurance": endurance, "autonomy": autonomy, "perception": perception,
        "plan_ir": plan_ir, "ordered_acceptance": ordered, "provenance": provenance,
    }))
    .into_response())
}

/// Plan a mission and report every view of the one plan (any authenticated caller, under the heavy quota and the
/// `STEWIE_PLAN_DEADLINE_S` wall clock). The Markdown report is written to the reports dir; the PDF is not rendered
/// (D-R148).
async fn post_plan(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let (h, bytes) = split(req, st.settings.max_body).await;
    let checked = match bytes {
        Ok(b) => request(&st, &h, &b, true).await,
        Err(e) => Err(e),
    };
    let (identity, payload, full) = match checked {
        Ok(c) => c,
        Err(e) => return e.into_response(),
    };
    let name = payload
        .get("name")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_owned();
    let deadline = std::time::Duration::from_secs_f64(st.settings.plan_deadline_s);
    let work = blocking(st.clone(), move |st| compose(st, &payload, &full));
    match tokio::time::timeout(deadline, work).await {
        Err(_) => err(
            StatusCode::SERVICE_UNAVAILABLE,
            "plan exceeded the compute budget; reduce the mission size or retry",
        )
        .into_response(),
        Ok(r) => {
            if r.status() == StatusCode::OK {
                log(&st, &h, &identity, "plan.run", &name);
            }
            r
        }
    }
}

/// The planning routes.
pub fn routes() -> Router<Arc<AppState>> {
    Router::new()
        .route("/plan", post(post_plan))
        .route("/plan/math", post(plan_math))
        .route("/plan/commands", post(plan_commands))
}
