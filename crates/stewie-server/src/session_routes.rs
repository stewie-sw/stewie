//! The operator/director training sessions (RW-55b26; Python `routers/session` and `server/session`): a session runs
//! the closed loop once over the mission planned on its site's raw DEM, records every executed leg, and serves two
//! views of that record. The operator sees only the legs the mission link delivered (`telemetry_link`), with the
//! truth fields removed; a director also sees the believed-vs-true divergence. The scorecard and the summary persist
//! under `data_dir/sessions/`, so a trainer can still read a run after the live store has dropped it.

use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use axum::Router;
use axum::extract::{Path, Query, Request, State};
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use serde_json::{Map, Value, json};
use stewie_traverse::nav::py_round;

use crate::app::{
    ApiError, AppState, Head, blocking, body_model, err, log, parse_body, require_auth, split,
};
use crate::plan_routes::{DEFAULTS, Opts, plan_with};
use crate::telemetry_link::{TelemetryLink, load_profile};
use crate::validate::{Field, Kind, Model};

/// The fields the operator must never see (truth telemetry).
const TRUTH_FIELDS: [&str; 4] = ["true_J", "slip", "slope_deg", "true_energy_J"];
/// One status packet per leg on the sim clock [s].
const LEG_PERIOD_S: f64 = 1.0;
/// The status packet [bytes] (the Python's CCSDS-class housekeeping frame assumption).
const LEG_PACKET_BYTES: i64 = 256;
/// A live session's lifetime (about one training shift).
const SESSION_TTL: Duration = Duration::from_hours(6);
/// The most sessions held at once; the oldest goes first.
const SESSION_MAX: usize = 256;
/// The objective a session plans for, and that its makespan is scored on.
const OBJECTIVE: &str = "time";
/// The site the sun is computed at (the Python's single mission sun).
const SUN_LAT_DEG: f64 = -87.45;

const fn text(default: &'static str) -> Kind {
    Kind::Str {
        min: 0,
        max: usize::MAX,
        nullable: false,
        default: Some(default),
    }
}

/// Python `SessionRequest` (`extra="allow"`: the mission's own keys ride along).
const START: Model = Model {
    fields: &[
        Field("name", text("session")),
        Field("profile", text("ideal")),
    ],
    forbid_extra: false,
};

const DEBRIEF_Q: Model = Model {
    fields: &[Field(
        "fast_forward",
        Kind::Float {
            gt: None,
            ge: None,
            le: None,
            default: Some(1.0),
        },
    )],
    forbid_extra: false,
};

/// One recorded run: the closed loop's legs and counters, the link that carried them, what reached the operator.
#[derive(Debug)]
pub struct TrainingSession {
    id: String,
    profile: String,
    legs: Vec<Value>,
    n_trips: usize,
    recharges: u64,
    plant_time_s: f64,
    map_channel: Value,
    route_drive_m: f64,
    link: TelemetryLink,
    operator_legs: Vec<Value>,
    mission_t0_s: f64,
    /// The mission as posted, kept to re-plan the alternatives the makespan is scored against.
    mission: Map<String, Value>,
    site: String,
    created: Instant,
}

/// A session's trainer boards: the public one and the director's truth.
type Boards = (Map<String, Value>, Map<String, Value>);

/// The live sessions by id.
#[derive(Debug, Default)]
pub struct Sessions(Mutex<HashMap<String, Arc<TrainingSession>>>);

impl Sessions {
    /// Hold `s`, after dropping the expired sessions, then the oldest beyond the cap.
    fn insert(&self, s: TrainingSession) {
        let mut map = self
            .0
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        map.retain(|_, v| v.created.elapsed() <= SESSION_TTL);
        map.insert(s.id.clone(), Arc::new(s));
        while map.len() > SESSION_MAX {
            let Some(oldest) = map
                .iter()
                .min_by_key(|(_, v)| v.created)
                .map(|(k, _)| k.clone())
            else {
                break;
            };
            map.remove(&oldest);
        }
    }

    fn get(&self, sid: &str) -> Option<Arc<TrainingSession>> {
        self.0
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .get(sid)
            .cloned()
    }
}

fn label(leg: &Value) -> &str {
    leg["leg"].as_str().unwrap_or("")
}

fn f(leg: &Value, k: &str) -> f64 {
    leg[k].as_f64().unwrap_or(0.0)
}

/// The routed drive distance [m]: the plan IR's `GoTo` waypoint polylines (any keep-out detour included).
fn route_drive_m(ir: &Value) -> f64 {
    ir["actions"]
        .as_array()
        .into_iter()
        .flatten()
        .fold(0.0, |total, a| {
            let wp: Vec<(f64, f64)> = a["waypoints"]
                .as_array()
                .into_iter()
                .flatten()
                .map(|p| (p[0].as_f64().unwrap_or(0.0), p[1].as_f64().unwrap_or(0.0)))
                .collect();
            total
                + wp.windows(2)
                    .fold(0.0, |s, w| s + (w[1].0 - w[0].0).hypot(w[1].1 - w[0].1))
        })
}

impl TrainingSession {
    fn sun(&self) -> Value {
        // the SPICE-preferring dispatcher the Python's `solar.sun_az_el` is bound to
        let (az, el, _) = crate::spec_routes::sun_az_el(SUN_LAT_DEG, self.mission_t0_s, 0.0);
        json!({"mission_t0_s": self.mission_t0_s, "az_deg": az, "el_deg": el,
               "authority": "stewie.specs.solar @ Haworth -87.45"})
    }

    fn missed(&self) -> Vec<String> {
        let seen: Vec<&str> = self.operator_legs.iter().map(label).collect();
        self.legs
            .iter()
            .map(label)
            .filter(|l| !seen.contains(l))
            .map(str::to_owned)
            .collect()
    }

    fn sums(&self) -> (f64, f64) {
        self.legs.iter().fold((0.0, 0.0), |(n, t), l| {
            (n + f(l, "nominal_J"), t + f(l, "true_J"))
        })
    }

    fn operator_view(&self) -> Value {
        json!({"session_id": self.id, "legs": self.operator_legs, "n_legs_total": self.legs.len(),
               "completed": true, "recharges": self.recharges,
               "link": {"profile": self.profile, "stats": self.link.stats()}, "sun": self.sun()})
    }

    /// The believed-vs-true pose gap per leg, with its mean and max (director truth).
    fn pose_divergence(&self) -> Value {
        let per_leg: Vec<Value> = self
            .legs
            .iter()
            .map(|l| {
                let err = (f(l, "bx") - f(l, "tx")).hypot(f(l, "by") - f(l, "ty"));
                json!({"leg": label(l), "err_m": py_round(err, 3), "bx": f(l, "bx"), "by": f(l, "by"),
                       "tx": f(l, "tx"), "ty": f(l, "ty")})
            })
            .collect();
        let errs: Vec<f64> = per_leg.iter().map(|p| f(p, "err_m")).collect();
        #[allow(clippy::cast_precision_loss)] // a leg count
        let (mean, max) = if errs.is_empty() {
            (0.0, 0.0)
        } else {
            (
                py_round(errs.iter().fold(0.0, |a, e| a + e) / errs.len() as f64, 3),
                py_round(errs.iter().copied().fold(f64::NEG_INFINITY, f64::max), 3),
            )
        };
        json!({"per_leg": per_leg, "mean_m": mean, "max_m": max})
    }

    /// The run's makespan against the fastest of the planner's alternatives (`auto`, `nearest`) on the same raw
    /// site DEM (the Python re-plans them flat, which D-R85 refuses); never faster than the run itself.
    fn makespan(&self, st: &AppState) -> Result<Value, ApiError> {
        let makespan = self.plant_time_s;
        let mut optimal = makespan;
        if makespan > 0.0 {
            for algorithm in ["auto", "nearest"] {
                let opts = Opts {
                    algorithm,
                    objective: OBJECTIVE,
                    raw_terrain: true,
                    site: Some(&self.site),
                    ..DEFAULTS
                };
                let t = plan_with(st, &self.mission, &opts)?.plan.totals.time_s;
                if t > 0.0 {
                    optimal = optimal.min(t);
                }
            }
        }
        let ratio = if optimal > 0.0 {
            makespan / optimal
        } else {
            1.0
        };
        Ok(
            json!({"makespan_s": py_round(makespan, 3), "optimal_s": py_round(optimal, 3),
                  "makespan_ratio": py_round(ratio, 4)}),
        )
    }

    /// The trainer boards: `public` for a trainee, `truth` (the divergence) for directors.
    fn scorecard(&self, st: &AppState) -> Result<Boards, ApiError> {
        let (nominal, truth_j) = self.sums();
        let missed = self.missed();
        #[allow(clippy::cast_precision_loss)] // leg counts
        let frac = self.operator_legs.len() as f64 / self.legs.len().max(1) as f64;
        let mut public = json!({
            "completed": true, "objectives_total": self.n_trips, "recharges": self.recharges, "replans": 0,
            "legs_total": self.legs.len(), "legs_delivered": self.operator_legs.len(), "legs_missed": missed.len(),
            "comm_delivered_frac": py_round(frac, 3), "stranded_packets": self.link.stranded.len(),
            "dropped_packets": self.link.dropped, "energy_MJ": py_round(nominal / 1e6, 3),
            "link_profile": self.profile,
        });
        if let (Some(p), Value::Object(mk)) = (public.as_object_mut(), self.makespan(st)?) {
            p.extend(mk);
        }
        let pd = self.pose_divergence();
        let truth = json!({"energy_divergence_J": py_round((truth_j - nominal).abs(), 1),
                           "true_energy_MJ": py_round(truth_j / 1e6, 3), "operator_missed_legs": missed,
                           "pose_divergence_mean_m": pd["mean_m"], "pose_divergence_max_m": pd["max_m"]});
        let obj = |v: Value| match v {
            Value::Object(m) => m,
            _ => Map::new(),
        };
        Ok((obj(public), obj(truth)))
    }

    fn debrief(&self, fast_forward: f64) -> Value {
        let divergence = self
            .legs
            .iter()
            .fold(0.0, |a, l| a + (f(l, "true_J") - f(l, "nominal_J")).abs());
        json!({"session_id": self.id, "fast_forward": fast_forward, "legs": self.legs,
               "n_legs_total": self.legs.len(), "operator_received": self.operator_legs.len(),
               "operator_missed_legs": self.missed(), "energy_divergence_J": divergence, "completed": true,
               "map_channel": self.map_channel, "sun": self.sun()})
    }

    /// The per-run Markdown summary (route, energy, comm drops, slip events, divergence), from the record alone.
    #[allow(clippy::too_many_lines)] // the Python's summary, section by section
    fn summary(&self) -> String {
        let (nominal, truth_j) = self.sums();
        let n = self.legs.len();
        let received = self.operator_legs.len();
        let mut lines = vec![
            format!("# Mission summary — session {}", self.id),
            String::new(),
            format!("- completed: True · legs: {n} (operator received {received})"),
            format!("- recharges: {} · replans: 0", self.recharges),
            String::new(),
            "## Route".to_owned(),
            format!(
                "- routed drive distance: {:.1} m (executed path incl. any detour)",
                self.route_drive_m
            ),
            String::new(),
            "| leg | believed → true pose | SoC |".to_owned(),
            "|---|---|---|".to_owned(),
        ];
        for l in &self.legs {
            lines.push(format!(
                "| {} | ({:.1}, {:.1}) → ({:.1}, {:.1}) | {:.2} |",
                label(l),
                f(l, "bx"),
                f(l, "by"),
                f(l, "tx"),
                f(l, "ty"),
                f(l, "soc")
            ));
        }
        lines.extend([
            String::new(),
            "## Energy".to_owned(),
            format!(
                "- nominal (planned): {:.3} MJ · true (slip/grade physics): {:.3} MJ",
                nominal / 1e6,
                truth_j / 1e6
            ),
            String::new(),
            "| leg | nominal J | true J |".to_owned(),
            "|---|---|---|".to_owned(),
        ]);
        for l in &self.legs {
            lines.push(format!(
                "| {} | {:.0} | {:.0} |",
                label(l),
                f(l, "nominal_J"),
                f(l, "true_J")
            ));
        }
        let missed = self.missed();
        let missed = if missed.is_empty() {
            "none".to_owned()
        } else {
            stewie_twin::pyjson::repr_list(&missed)
        };
        lines.extend([
            String::new(),
            "## Link (comm drops)".to_owned(),
            format!(
                "- link profile: {} · stats: {}",
                self.profile,
                self.link.stats_repr()
            ),
            format!("- operator received {received} / {n} legs · missed: {missed}"),
            String::new(),
            "## Slip events".to_owned(),
        ]);
        let mut slipped: Vec<&Value> = self.legs.iter().filter(|l| f(l, "slip") > 0.0).collect();
        slipped.sort_by(|a, b| f(b, "slip").total_cmp(&f(a, "slip")));
        if slipped.is_empty() {
            lines.push("- none (every drive leg held traction on this route)".to_owned());
        } else {
            lines.extend([
                format!(
                    "- {} drive leg(s) slipped on the real DEM grade",
                    slipped.len()
                ),
                String::new(),
                "| leg | slip | slope° |".to_owned(),
                "|---|---|---|".to_owned(),
            ]);
            for l in slipped {
                lines.push(format!(
                    "| {} | {:.3} | {:.2} |",
                    label(l),
                    f(l, "slip"),
                    f(l, "slope_deg")
                ));
            }
        }
        let divergence = self
            .legs
            .iter()
            .fold(0.0, |a, l| a + (f(l, "true_J") - f(l, "nominal_J")).abs());
        lines.extend([
            String::new(),
            "## Divergence (seen vs actual)".to_owned(),
            format!("- energy divergence (true vs nominal): {divergence:.1} J"),
            format!(
                "- map channel: coverage {:.2}, mean uncertainty {:.2} m",
                f(&self.map_channel, "coverage"),
                f(&self.map_channel, "mean_uncertainty_m")
            ),
        ]);
        lines.join("\n")
    }
}

fn sessions_dir(st: &AppState) -> std::path::PathBuf {
    st.cfg.data_dir.join("sessions")
}

/// Write `bytes` under `data_dir/sessions/` atomically, its modification time stamped from the server's clock (the
/// trainer history's `recorded_at`).
fn persist(st: &AppState, name: &str, bytes: &[u8]) -> Result<(), ApiError> {
    let fail = |e: String| err(StatusCode::INTERNAL_SERVER_ERROR, e);
    let dir = sessions_dir(st);
    std::fs::create_dir_all(&dir).map_err(|e| fail(e.to_string()))?;
    let path = dir.join(name);
    crate::atomic_write(&path, bytes).map_err(fail)?;
    let at = std::time::UNIX_EPOCH + Duration::from_secs_f64(st.clock.now().max(0.0));
    std::fs::File::options()
        .write(true)
        .open(&path)
        .and_then(|fh| fh.set_modified(at))
        .map_err(|e| fail(e.to_string()))
}

/// Run the closed loop for the posted mission and hold the session.
fn start(st: &AppState, head: &Head, body: Option<&Value>) -> Result<Response, ApiError> {
    let who = require_auth(st, head)?;
    let v = body_model(body, START)?;
    let bad = |e: String| err(StatusCode::BAD_REQUEST, e);
    // the model's fields first, then the mission's own keys, as Pydantic dumps an `extra="allow"` model
    let mut mission = v.clone();
    if let Some(Value::Object(o)) = body {
        for (k, val) in o {
            mission.entry(k.clone()).or_insert_with(|| val.clone());
        }
    }
    let profile = mission
        .remove("profile")
        .and_then(|p| p.as_str().map(str::to_owned))
        .unwrap_or_else(|| "ideal".to_owned());
    let mission_t0_s = match mission.remove("mission_t0_s") {
        None | Some(Value::Null | Value::Bool(false)) => 0.0,
        Some(Value::Bool(true)) => 1.0,
        Some(Value::Number(n)) => n.as_f64().unwrap_or(0.0),
        Some(Value::String(s)) => s.trim().parse::<f64>().map_err(|_| {
            bad(format!(
                "could not convert string to float: {}",
                crate::operators::py_repr(&s)
            ))
        })?,
        Some(other) => return Err(bad(format!("mission_t0_s must be a number, not {other}"))),
    };
    let site = mission
        .get("site")
        .and_then(Value::as_str)
        .unwrap_or("haworth")
        .to_owned();
    let opts = Opts {
        algorithm: "auto",
        objective: OBJECTIVE,
        raw_terrain: true,
        site: Some(&site),
        ..DEFAULTS
    };
    let p = plan_with(st, &mission, &opts)?;
    let link_profile = load_profile(&profile).map_err(bad)?;
    let dem = p.dem();
    let cl = st
        .planning
        .closed_loop(&p.mission, &p.inputs, &p.plan, &dem, None)
        .map_err(bad)?;
    let slope = DEFAULTS.max_traverse_slope_deg;
    let ir = stewie_plan::ir::plan_ir(&p.mission, &p.plan, &p.ctx, dem, slope).map_err(bad)?;
    let legs = cl.leg_records(p.ctx.reserve_frac);
    let mut link = TelemetryLink::new(link_profile, 0);
    let mut operator_legs = Vec::new();
    #[allow(clippy::cast_precision_loss)] // a leg index
    for (i, leg) in legs.iter().enumerate() {
        let sent = i as f64 * LEG_PERIOD_S;
        if let Some(visible) = link.deliver_at(LEG_PACKET_BYTES, sent, "") {
            let mut shaped: Map<String, Value> = leg
                .as_object()
                .into_iter()
                .flatten()
                .filter(|(k, _)| !TRUTH_FIELDS.contains(&k.as_str()))
                .map(|(k, v)| (k.clone(), v.clone()))
                .collect();
            shaped.insert("sent_at_s".into(), json!(py_round(sent, 3)));
            shaped.insert("visible_at_s".into(), json!(py_round(visible, 3)));
            operator_legs.push(Value::Object(shaped));
        }
    }
    let id = crate::services::new_correlation_id(st.entropy);
    let n_legs = legs.len();
    st.training.insert(TrainingSession {
        id: id.clone(),
        profile,
        legs,
        n_trips: p.plan.trips.len(),
        recharges: p.plan.totals.charges,
        plant_time_s: p.plan.totals.time_s,
        map_channel: cl.map_channel.to_value(),
        route_drive_m: route_drive_m(&ir),
        link,
        operator_legs,
        mission_t0_s,
        mission,
        site,
        created: Instant::now(),
    });
    log(st, head, &who, "session.start", &id);
    Ok(
        axum::Json(json!({"ok": true, "session_id": id, "n_legs": n_legs,
                         "operator_url": format!("/session/{id}/operator"),
                         "debrief_url": format!("/session/{id}/debrief")}))
        .into_response(),
    )
}

fn unknown() -> Response {
    (
        StatusCode::NOT_FOUND,
        axum::Json(json!({"ok": false, "error": "unknown session"})),
    )
        .into_response()
}

async fn session_start(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let (head, bytes) = split(req, st.settings.max_body).await;
    blocking(st, move |st| {
        let body = parse_body(&bytes?)?;
        start(st, &head, body.as_ref())
    })
    .await
}

/// The operator-trainee view: only what the link delivered, truth-denied; any authenticated caller.
async fn operator(
    State(st): State<Arc<AppState>>,
    Path(sid): Path<String>,
    req: Request,
) -> Response {
    let head = Head::of(&req);
    blocking(st, move |st| {
        require_auth(st, &head)?;
        Ok(st
            .training
            .get(&sid)
            .map_or_else(unknown, |s| axum::Json(s.operator_view()).into_response()))
    })
    .await
}

fn is_director(st: &AppState, head: &Head, identity: &str) -> Result<bool, ApiError> {
    Ok(st
        .auth(Some(&head.cid))
        .role_of(identity)
        .map_err(|e| err(StatusCode::INTERNAL_SERVER_ERROR, e))?
        == "director")
}

/// The trainer board; asking for it persists the durable record, which serves the board once the session is gone.
async fn scorecard(
    State(st): State<Arc<AppState>>,
    Path(sid): Path<String>,
    req: Request,
) -> Response {
    let head = Head::of(&req);
    blocking(st, move |st| {
        let identity = require_auth(st, &head)?;
        let director = is_director(st, &head, &identity)?;
        let (mut board, truth) = if let Some(s) = st.training.get(&sid) {
            let (public, truth) = s.scorecard(st)?;
            let record = json!({"session_id": s.id, "profile": s.profile, "objective": OBJECTIVE,
                                "public": public, "truth": truth,
                                "makespan": {"makespan_s": public["makespan_s"], "optimal_s": public["optimal_s"],
                                             "makespan_ratio": public["makespan_ratio"]}});
            let text = stewie_twin::pyjson::dumps_indent(&record, 2)
                .map_err(|e| err(StatusCode::INTERNAL_SERVER_ERROR, format!("{e:?}")))?;
            persist(st, &format!("scorecard_{}.json", s.id), text.as_bytes())?;
            (public, truth)
        } else {
            let path = sessions_dir(st).join(format!("scorecard_{sid}.json"));
            let rec: Value = std::fs::read(&path)
                .ok()
                .and_then(|b| serde_json::from_slice(&b).ok())
                .ok_or_else(|| err(StatusCode::NOT_FOUND, "no such session"))?;
            let obj = |k: &str| rec[k].as_object().cloned().unwrap_or_default();
            (obj("public"), obj("truth"))
        };
        if director {
            board.extend(truth);
        }
        Ok(axum::Json(json!({"ok": true, "scorecard": board})).into_response())
    })
    .await
}

/// The director's full record and the seen-vs-actual divergence; `fast_forward` is a view rate only.
async fn debrief(
    State(st): State<Arc<AppState>>,
    Path(sid): Path<String>,
    Query(q): Query<Vec<(String, String)>>,
    req: Request,
) -> Response {
    let head = Head::of(&req);
    blocking(st, move |st| {
        crate::admin::require_director(st, &head)?;
        let raw = crate::spec_routes::query(&q, DEBRIEF_Q)?;
        let ff = raw
            .get("fast_forward")
            .and_then(|v| crate::validate::as_float(v).ok())
            .unwrap_or(1.0);
        Ok(st
            .training
            .get(&sid)
            .map_or_else(unknown, |s| axum::Json(s.debrief(ff)).into_response()))
    })
    .await
}

/// The director's believed-vs-true pose divergence per leg.
async fn divergence(
    State(st): State<Arc<AppState>>,
    Path(sid): Path<String>,
    req: Request,
) -> Response {
    let head = Head::of(&req);
    blocking(st, move |st| {
        crate::admin::require_director(st, &head)?;
        Ok(st.training.get(&sid).map_or_else(unknown, |s| {
            axum::Json(json!({"ok": true, "session_id": sid, "divergence": s.pose_divergence()}))
                .into_response()
        }))
    })
    .await
}

/// The persisted Markdown summary.
async fn summary(
    State(st): State<Arc<AppState>>,
    Path(sid): Path<String>,
    req: Request,
) -> Response {
    let head = Head::of(&req);
    blocking(st, move |st| {
        require_auth(st, &head)?;
        let Some(s) = st.training.get(&sid) else {
            return Ok(unknown());
        };
        let md = s.summary();
        persist(st, &format!("summary_{}.md", s.id), md.as_bytes())?;
        Ok((
            [(
                axum::http::header::CONTENT_TYPE,
                "text/markdown; charset=utf-8",
            )],
            md,
        )
            .into_response())
    })
    .await
}

/// Every persisted scorecard, newest first by modification time; the truth block for directors only. An unreadable
/// record is skipped.
#[allow(clippy::case_sensitive_file_extension_comparisons)] // the Python's case-sensitive `scorecard_*.json` glob
async fn history(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let head = Head::of(&req);
    blocking(st, move |st| {
        let identity = require_auth(st, &head)?;
        let director = is_director(st, &head, &identity)?;
        let mut recs: Vec<(f64, Map<String, Value>)> = std::fs::read_dir(sessions_dir(st))
            .into_iter()
            .flatten()
            .flatten()
            .filter(|e| {
                let n = e.file_name().to_string_lossy().into_owned();
                n.starts_with("scorecard_") && n.ends_with(".json")
            })
            .filter_map(|e| {
                let mtime = e
                    .metadata()
                    .ok()?
                    .modified()
                    .ok()?
                    .duration_since(std::time::UNIX_EPOCH)
                    .ok()?
                    .as_secs_f64();
                let rec: Map<String, Value> = serde_json::from_slice(&std::fs::read(e.path()).ok()?).ok()?;
                rec.get("session_id")
                    .and_then(Value::as_str)
                    .is_some_and(|s| !s.is_empty())
                    .then_some((mtime, rec))
            })
            .collect();
        recs.sort_by(|a, b| b.0.total_cmp(&a.0));
        let sessions: Vec<Value> = recs
            .into_iter()
            .map(|(mtime, rec)| {
                let or = |k: &str, d: Value| rec.get(k).cloned().unwrap_or(d);
                let mut row = json!({"session_id": rec["session_id"], "profile": or("profile", json!("?")),
                                     "objective": or("objective", json!("?")), "recorded_at": py_round(mtime, 3),
                                     "public": or("public", json!({})), "makespan": or("makespan", json!({}))});
                if director {
                    row["truth"] = or("truth", json!({}));
                }
                row
            })
            .collect();
        Ok(axum::Json(json!({"ok": true, "is_director": director, "count": sessions.len(), "sessions": sessions}))
            .into_response())
    })
    .await
}

/// The training-session routes.
pub fn routes() -> Router<Arc<AppState>> {
    Router::new()
        .route("/session/start", post(session_start))
        .route("/session/{sid}/operator", get(operator))
        .route("/session/{sid}/scorecard", get(scorecard))
        .route("/session/{sid}/debrief", get(debrief))
        .route("/session/{sid}/divergence", get(divergence))
        .route("/session/{sid}/summary", get(summary))
        .route("/trainer/history", get(history))
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A SYNTHETIC empty session (labelled): only its id and creation time matter to the store.
    fn session(id: &str, created: Instant) -> TrainingSession {
        TrainingSession {
            id: id.to_owned(),
            profile: "ideal".to_owned(),
            legs: Vec::new(),
            n_trips: 0,
            recharges: 0,
            plant_time_s: 0.0,
            map_channel: Value::Null,
            route_drive_m: 0.0,
            link: TelemetryLink::new(load_profile("ideal").unwrap(), 0),
            operator_legs: Vec::new(),
            mission_t0_s: 0.0,
            mission: Map::new(),
            site: "haworth".to_owned(),
            created,
        }
    }

    #[test]
    fn the_store_drops_the_expired_then_the_oldest_beyond_its_cap() {
        let s = Sessions::default();
        let now = Instant::now();
        s.insert(session(
            "stale",
            now.checked_sub(SESSION_TTL + Duration::from_secs(1))
                .unwrap(),
        ));
        assert!(s.get("stale").is_some(), "held until the next insert");
        for i in 0..SESSION_MAX {
            s.insert(session(
                &format!("s{i}"),
                now + Duration::from_millis(i as u64),
            ));
        }
        assert!(s.get("stale").is_none(), "expired");
        assert!(s.get("s0").is_some(), "the cap is not yet exceeded");
        s.insert(session("newest", now + Duration::from_mins(1)));
        assert!(s.get("s0").is_none(), "the oldest goes first");
        assert!(s.get("s1").is_some() && s.get("newest").is_some());
    }
}
