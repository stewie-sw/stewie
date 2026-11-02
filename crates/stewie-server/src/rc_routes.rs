//! The remote-control routes (RW-55c; Python `routers/rc`, the command and telemetry half): `POST /rc/command` (a
//! `GoTo`, Safe, `SetSim` or re-arm through the SF-01 watchdog, behind the AG-08 live-mission gate, the EG-05
//! live-execution token, the SF-02 teleop authority and the AS-12 eligibility interlock, durably audited before
//! it is submitted), `GET /rc/telemetry` and its SSE stream (drain the backend, tick the watchdog), `GET
//! /rc/eligibility` (every gate's verdict) and `POST /rc/ros_odom` (the live ROS rover's odometry, display only).

use std::sync::{Arc, Mutex};

use axum::Router;
use axum::body::Body;
use axum::extract::{Query, Request, State};
use axum::http::{StatusCode, header};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use hmac::{Hmac, Mac};
use serde_json::{Map, Value, json};
use sha2::Sha256;

use crate::admin::require_role;
use crate::app::{
    ApiError, AppState, Head, blocking, body_model, err, parse_body, require_auth, split,
};
use crate::objects::{Namespace, ns_dir, slug};
use crate::operators::py_repr;
use crate::rc::{
    Command, CommandContext, GoTo, SAFE_REASON_OPERATOR, SafingWatchdog, SimBackend,
    command_eligible, eligibility_report, teleop_authority,
};
use crate::validate::{Field, Kind, Model};

/// The live ROS rover's latest odometry, in the Python's key order, and when it arrived (monotonic).
#[derive(Debug, Clone)]
struct RosOdom {
    fields: Vec<(&'static str, Value)>,
    received: f64,
}

/// The rover-command state: the sim backend behind its watchdog, and the latest live ROS odometry.
#[derive(Debug)]
pub struct Rc {
    watchdog: Mutex<SafingWatchdog>,
    odom: Mutex<Option<RosOdom>>,
    /// The key live-execution tokens are signed under (`STEWIE_LIVE_TOKEN_SECRET`, else per-process random).
    pub(crate) token_secret: Vec<u8>,
}

impl Rc {
    /// The sim backend at the origin behind a watchdog of `deadline_s`; `secret` keys the live-execution tokens.
    #[must_use]
    pub fn new(deadline_s: f64, secret: Vec<u8>) -> Self {
        Self {
            watchdog: Mutex::new(SafingWatchdog::new(SimBackend::default(), deadline_s)),
            odom: Mutex::new(None),
            token_secret: secret,
        }
    }

    fn wd(&self) -> std::sync::MutexGuard<'_, SafingWatchdog> {
        self.watchdog
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }
}

/// The Python's `str(v)` of a JSON value.
fn py_str(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        other => stewie_twin::pyjson::repr(other),
    }
}

fn type_name(v: &Value) -> &'static str {
    match v {
        Value::Null => "NoneType",
        Value::Array(_) => "list",
        Value::Object(_) => "dict",
        Value::String(_) => "str",
        Value::Bool(_) => "bool",
        Value::Number(_) => "float",
    }
}

/// Python's digit-group underscores (`1_000`) dropped, when every one sits between two digits.
fn ungroup(s: &str) -> Option<String> {
    let b = s.as_bytes();
    let ok = b.iter().enumerate().all(|(i, c)| {
        *c != b'_'
            || (i > 0 && i + 1 < b.len() && b[i - 1].is_ascii_digit() && b[i + 1].is_ascii_digit())
    });
    ok.then(|| s.replace('_', ""))
}

/// Python's `float(v)`, with its error messages.
pub(crate) fn py_float(v: &Value) -> Result<f64, String> {
    match v {
        Value::Number(n) => Ok(n.as_f64().unwrap_or(0.0)),
        Value::Bool(b) => Ok(f64::from(u8::from(*b))),
        Value::String(s) => ungroup(s.trim())
            .and_then(|t| t.parse::<f64>().ok())
            .ok_or_else(|| format!("could not convert string to float: {}", py_repr(s))),
        other => Err(format!(
            "float() argument must be a string or a real number, not '{}'",
            type_name(other)
        )),
    }
}

/// Python's `int(v)` (a float truncated), with its error messages.
fn py_int(v: &Value) -> Result<i64, String> {
    match v {
        Value::Number(n) => n.as_i64().map_or_else(
            || {
                let x = n.as_f64().unwrap_or(0.0);
                #[allow(clippy::cast_possible_truncation)] // Python's int() truncates toward zero
                if x.is_finite() && x.abs() < 9.2e18 {
                    Ok(x.trunc() as i64)
                } else {
                    Err("cannot convert float infinity to integer".to_owned())
                }
            },
            Ok,
        ),
        Value::Bool(b) => Ok(i64::from(*b)),
        Value::String(s) => ungroup(s.trim())
            .filter(|t| {
                let d = t.strip_prefix(['+', '-']).unwrap_or(t);
                !d.is_empty() && d.bytes().all(|c| c.is_ascii_digit())
            })
            .and_then(|t| t.parse::<i64>().ok())
            .ok_or_else(|| format!("invalid literal for int() with base 10: {}", py_repr(s))),
        other => Err(format!(
            "int() argument must be a string, a bytes-like object or a real number, not '{}'",
            type_name(other)
        )),
    }
}

fn forbidden(msg: impl Into<String>) -> ApiError {
    err(StatusCode::FORBIDDEN, msg)
}

/// Python's float `repr`, the non-finite ones included (the token signature hashes it).
fn float_repr(x: f64) -> String {
    stewie_twin::pyjson::float_repr(x).unwrap_or_else(|_| {
        if x.is_nan() {
            "nan".to_owned()
        } else if x > 0.0 {
            "inf".to_owned()
        } else {
            "-inf".to_owned()
        }
    })
}

/// EG-05: the token's keyed HMAC-SHA256 over its identity and validity window (Python `live_gate._sign`).
pub(crate) fn sign_live(
    secret: &[u8],
    mission: &str,
    revision: &str,
    issued: f64,
    ttl: f64,
) -> String {
    let payload = format!(
        "live-exec:{mission}:{revision}:{}:{}",
        float_repr(issued),
        float_repr(ttl)
    );
    let Ok(mut mac) = Hmac::<Sha256>::new_from_slice(secret) else {
        return String::new();
    };
    mac.update(payload.as_bytes());
    mac.finalize()
        .into_bytes()
        .iter()
        .fold(String::new(), |mut out, b| {
            use std::fmt::Write as _;
            let _ = write!(out, "{b:02x}");
            out
        })
}

/// EG-05 step 8 (Python `require_live_token`): a token for exactly this mission and revision, its keyed HMAC over
/// the identity and validity window intact, and not expired.
fn require_live_token(
    secret: &[u8],
    tok: &Map<String, Value>,
    mission_id: &str,
    revision_id: &str,
    now: f64,
) -> Result<(), String> {
    let field = |k: &str| tok.get(k).cloned().unwrap_or(Value::Null);
    let (m, r) = (py_str(&field("mission_id")), py_str(&field("revision_id")));
    let (issued, ttl) = (py_float(&field("issued_at"))?, py_float(&field("ttl_s"))?);
    let signature = py_str(&field("signature"));
    if m != mission_id || r != revision_id {
        return Err(
            "live-execution token does not match the mission/revision being executed".to_owned(),
        );
    }
    let expected = sign_live(secret, &m, &r, issued, ttl);
    // constant-time, as `hmac.compare_digest`
    let same = expected.len() == signature.len()
        && expected
            .bytes()
            .zip(signature.bytes())
            .fold(0u8, |a, (x, y)| a | (x ^ y))
            == 0;
    if !same {
        return Err(
            "live-execution token signature invalid (forged, retargeted, or tampered)".to_owned(),
        );
    }
    if now > issued + ttl {
        return Err("live-execution token expired (re-run the training-to-live gate)".to_owned());
    }
    Ok(())
}

/// The mission a frozen release carries (Python `db.release_revision_mission_id`), failing closed on a missing or
/// contradictory identity.
pub(crate) fn release_mission_id(art: &Value) -> Result<String, String> {
    let text = |v: &Value| match v {
        Value::Null | Value::Bool(false) => String::new(),
        Value::String(s) => s.trim().to_owned(),
        other => py_str(other).trim().to_owned(),
    };
    let top = text(&art["mission_id"]);
    let nested = art["signed_revision"]["intent"]
        .as_object()
        .map(|i| text(i.get("mission_id").unwrap_or(&Value::Null)))
        .unwrap_or_default();
    if !top.is_empty() && !nested.is_empty() && top != nested {
        return Err(format!(
            "released revision mission identity mismatch: row={}, signed_intent={}",
            py_repr(&top),
            py_repr(&nested)
        ));
    }
    let id = if nested.is_empty() { top } else { nested };
    if id.is_empty() {
        return Err("released revision has no signed mission identity".to_owned());
    }
    Ok(id)
}

/// EG-05 on the live-write path (Python `_enforce_live_token`): a presented token is always verified against the
/// released revision it names, bound to the commanded mission; a missing one is refused only when live execution
/// is enabled.
async fn enforce_live_token(st: &AppState, body: &Map<String, Value>) -> Result<(), ApiError> {
    let tok = match body.get("live_token") {
        None | Some(Value::Null) => {
            if st.settings.rc.allow_live_exec {
                return Err(forbidden(
                    "live execution enabled: a mission-bound rover command requires a live-execution token bound \
                     to a released revision (POST /executive/run to obtain one)",
                ));
            }
            return Ok(());
        }
        Some(t) => t,
    };
    let rev = body
        .get("revision_hash")
        .filter(|v| crate::objects::truthy(v))
        .map(py_str);
    let rel = match &rev {
        Some(h) => st.edit_sessions.read_release_revision(h).await?,
        None => None,
    };
    let (Some(rev), Some(rel)) = (rev, rel) else {
        return Err(forbidden(
            "live_token requires a revision_hash of a released revision",
        ));
    };
    let commanded = body
        .get("mission")
        .filter(|v| crate::objects::truthy(v))
        .map(py_str)
        .unwrap_or_default();
    let released_for = release_mission_id(&rel).map_err(|e| {
        forbidden(format!(
            "live-execution token rejected: invalid released revision: {e}"
        ))
    })?;
    if commanded != released_for {
        return Err(forbidden(format!(
            "live-execution token rejected: revision {} was released for mission {}, not the commanded mission {}",
            rev.chars().take(12).collect::<String>(),
            py_repr(&released_for),
            py_repr(&commanded)
        )));
    }
    let Value::Object(tok) = tok else {
        return Err(forbidden(format!(
            "live-execution token rejected: the token must be an object, not {}",
            type_name(tok)
        )));
    };
    require_live_token(
        &st.rc.token_secret,
        tok,
        &released_for,
        &rev,
        st.clock.now(),
    )
    .map_err(|e| forbidden(format!("live-execution token rejected: {e}")))
}

fn role(st: &AppState, head: &Head, identity: &str) -> Result<String, ApiError> {
    st.auth(Some(&head.cid))
        .role_of(identity)
        .map_err(|e| err(StatusCode::INTERNAL_SERVER_ERROR, e))
}

fn audit(
    st: &AppState,
    head: &Head,
    actor: &str,
    action: &str,
    target: &str,
    fields: &[(&str, Value)],
) {
    let f: Map<String, Value> = fields
        .iter()
        .map(|(k, v)| ((*k).to_owned(), v.clone()))
        .collect();
    st.ledger
        .log_event(actor, action, target, Some(&head.cid), &f);
}

fn is_live_mission(st: &AppState, name: &str) -> bool {
    ns_dir(&st.cfg.data_dir, "missions", Namespace::Live)
        .is_ok_and(|d| d.join(format!("{}.json", slug(name))).exists())
}

/// Parse the command body into a command, with the Python's 400s and the director-only `SetSim`.
fn parse_command(
    st: &AppState,
    head: &Head,
    identity: &str,
    kind: &str,
    body: &Map<String, Value>,
) -> Result<Command, ApiError> {
    let get = |k: &str| body.get(k).cloned();
    let malformed = |e: String| {
        err(
            StatusCode::BAD_REQUEST,
            format!("malformed {} command: {e}", py_repr(kind)),
        )
    };
    let required = |k: &str| get(k).ok_or_else(|| py_repr(k));
    match kind {
        "goto" => {
            let leg_id = py_int(&get("leg_id").unwrap_or(json!(0))).map_err(malformed)?;
            let goal_row =
                py_float(&required("goal_row").map_err(malformed)?).map_err(malformed)?;
            let goal_col =
                py_float(&required("goal_col").map_err(malformed)?).map_err(malformed)?;
            let v_max_mps = py_float(&get("v_max_mps").unwrap_or(json!(0.3))).map_err(malformed)?;
            let goal_radius_cells =
                py_float(&get("goal_radius_cells").unwrap_or(json!(1.0))).map_err(malformed)?;
            Ok(Command::GoTo(GoTo {
                leg_id,
                goal_row,
                goal_col,
                v_max_mps,
                goal_radius_cells,
            }))
        }
        "safe" => Ok(Command::Safe(SAFE_REASON_OPERATOR)),
        "setsim" => {
            if role(st, head, identity)? != "director" {
                return Err(forbidden("SetSim (time-warp) is director-only"));
            }
            Ok(Command::SetSim(
                py_float(&get("time_factor").unwrap_or(json!(1.0))).map_err(malformed)?,
            ))
        }
        _ => Err(err(
            StatusCode::BAD_REQUEST,
            format!("unknown RC command kind {}", py_repr(kind)),
        )),
    }
}

/// SF-02 and AS-12 for a `GoTo`: mission-less teleop needs the dev/bench grant, and every motion command passes the
/// eligibility interlock (the SF-01 safed and NV-12 stale-link gates included).
fn motion_gates(
    st: &AppState,
    head: &Head,
    identity: &str,
    mission_less: bool,
    now: f64,
) -> Result<(), ApiError> {
    if mission_less {
        let profile = &st.settings.rc.runnable_profile;
        let (ok, reason) = teleop_authority(profile, st.settings.rc.allow_teleop);
        if !ok {
            audit(
                st,
                head,
                identity,
                "rc.teleop_refused",
                reason,
                &[("profile", json!(profile))],
            );
            return Err(forbidden(format!(
                "mission-less teleop refused ({reason}): a low-level rover command requires a released (live) \
                 mission, or an explicit dev/bench teleop grant (STEWIE_ALLOW_TELEOP) on a non-LIVE/OPERATE \
                 runnable profile"
            )));
        }
        audit(st, head, identity, "rc.teleop_grant", profile, &[]);
    }
    let r = role(st, head, identity)?;
    let (ok, reason) = {
        let wd = st.rc.wd();
        command_eligible(&CommandContext {
            role: Some(&r),
            mission_namespace: Some("live"),
            target_namespace: Some("live"),
            safed: wd.tripped,
            ack_age_s: wd.seconds_idle(now),
            ack_deadline_s: wd.deadline_s,
        })
    };
    if !ok {
        audit(st, head, identity, "rc.ineligible", reason, &[]);
        let status = if reason.starts_with("unauthorized") {
            StatusCode::FORBIDDEN
        } else {
            StatusCode::CONFLICT
        };
        let tail = if reason == "unsafe_safed" {
            "; an operator re-arm is required"
        } else {
            ""
        };
        return Err(err(status, format!("command ineligible: {reason}{tail}")));
    }
    Ok(())
}

async fn command(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let (head, bytes) = split(req, st.settings.max_body).await;
    command_on(&st, &head, bytes)
        .await
        .unwrap_or_else(IntoResponse::into_response)
}

async fn command_on(
    st: &AppState,
    head: &Head,
    bytes: Result<axum::body::Bytes, ApiError>,
) -> Result<Response, ApiError> {
    let body = parse_body(&bytes?)?;
    let identity = require_role(st, head, "operator")?;
    // a bare `dict` body, as FastAPI validates one
    let body = match body {
        Some(Value::Object(o)) => o,
        Some(_) => {
            return Err(err(
                StatusCode::BAD_REQUEST,
                "body: Input should be a valid dictionary",
            ));
        }
        None => return Err(err(StatusCode::BAD_REQUEST, "body: Field required")),
    };
    // AG-08: a command issued for a mission may target only a published (live) one
    let mission = body.get("mission").filter(|v| !v.is_null());
    if let Some(m) = mission
        && !is_live_mission(st, &py_str(m))
    {
        return Err(forbidden(format!(
            "mission {} is not published (live); only a live mission can be commanded to the rover",
            stewie_twin::pyjson::repr(m)
        )));
    }
    let kind = py_str(body.get("kind").unwrap_or(&json!(""))).to_lowercase();
    if kind == "goto" && mission.is_some() {
        enforce_live_token(st, &body).await?;
    }
    submit(st, head, &identity, &kind, &body, mission.is_some())
}

fn submit(
    st: &AppState,
    head: &Head,
    identity: &str,
    kind: &str,
    body: &Map<String, Value>,
    has_mission: bool,
) -> Result<Response, ApiError> {
    let now = st.clock.monotonic();
    let reply = |accepted: &str, tripped: bool| {
        Ok(
            axum::Json(json!({"ok": true, "accepted": accepted, "watchdog_tripped": tripped}))
                .into_response(),
        )
    };
    if kind == "rearm" {
        let mut wd = st.rc.wd();
        wd.rearm(now);
        audit(st, head, identity, "rc.rearm", "", &[]);
        return reply("rearm", wd.tripped);
    }
    let cmd = parse_command(st, head, identity, kind, body)?;
    if kind == "goto" {
        motion_gates(st, head, identity, !has_mission, now)?;
    }
    let target = py_str(body.get("leg_id").unwrap_or(&json!("")));
    let mission = body
        .get("mission")
        .filter(|v| crate::objects::truthy(v))
        .map(py_str)
        .unwrap_or_default();
    let fields: Map<String, Value> = [
        ("mission", json!(mission)),
        (
            "goal_row",
            body.get("goal_row").cloned().unwrap_or(Value::Null),
        ),
        (
            "goal_col",
            body.get("goal_col").cloned().unwrap_or(Value::Null),
        ),
    ]
    .into_iter()
    .map(|(k, v)| (k.to_owned(), v))
    .collect();
    st.ledger
        .critical_event(
            identity,
            &format!("rc.{kind}"),
            &target,
            Some(&head.cid),
            &fields,
        )
        .map_err(|e| err(StatusCode::SERVICE_UNAVAILABLE, e.0))?;
    let mut wd = st.rc.wd();
    wd.submit(cmd, now)
        .map_err(|e| err(StatusCode::CONFLICT, e.to_string()))?;
    reply(kind, wd.tripped)
}

/// Python `json.dumps` of an object in the given key order (its default separators).
pub(crate) fn ordered(pairs: &[(&str, String)]) -> String {
    let items: Vec<String> = pairs
        .iter()
        .map(|(k, v)| {
            format!(
                "{}: {v}",
                stewie_twin::pyjson::dumps(&json!(k)).unwrap_or_default()
            )
        })
        .collect();
    format!("{{{}}}", items.join(", "))
}

pub(crate) fn dumps(v: &Value) -> String {
    stewie_twin::pyjson::dumps(v).unwrap_or_else(|_| "null".to_owned())
}

const POSE_KEYS: [&str; 11] = [
    "leg_id",
    "row",
    "col",
    "yaw_rad",
    "v_achieved_mps",
    "slip",
    "sinkage_m",
    "slope_rad",
    "soc",
    "entrapped",
    "kind",
];
const LEG_KEYS: [&str; 9] = [
    "leg_id",
    "status",
    "commanded_dist_m",
    "achieved_dist_m",
    "energy_J",
    "mass_kg",
    "final_row",
    "final_col",
    "kind",
];

/// One telemetry frame as the Python's `json.dumps` writes it: drain the backend (its sim pose carries no measured
/// state of charge, so `soc` is null), tick the watchdog, and attach the live ROS odometry with its age.
fn telemetry_frame(st: &AppState) -> String {
    let now = st.clock.monotonic();
    let (tripped, tlm, cell_m, deadline) = {
        let mut wd = st.rc.wd();
        let tripped = wd.tick(now);
        let tlm = wd.backend.poll();
        (tripped, tlm, wd.backend.cell_m, wd.deadline_s)
    };
    let frames: Vec<String> = tlm
        .iter()
        .map(|t| {
            let pose = t["kind"] == "pose";
            let keys: &[&str] = if pose { &POSE_KEYS } else { &LEG_KEYS };
            let pairs: Vec<(&str, String)> = keys
                .iter()
                .map(|k| {
                    (
                        *k,
                        if pose && *k == "soc" {
                            "null".to_owned()
                        } else {
                            dumps(&t[*k])
                        },
                    )
                })
                .collect();
            ordered(&pairs)
        })
        .collect();
    let odom = st
        .rc
        .odom
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
        .clone()
        .map_or_else(
            || "null".to_owned(),
            |o| {
                let mut pairs: Vec<(&str, String)> =
                    o.fields.iter().map(|(k, v)| (*k, dumps(v))).collect();
                pairs.push(("age_s", dumps(&json!((now - o.received).max(0.0)))));
                ordered(&pairs)
            },
        );
    ordered(&[
        ("ok", "true".to_owned()),
        ("telemetry", format!("[{}]", frames.join(", "))),
        ("cell_m", dumps(&json!(cell_m))),
        ("ros_odom", odom),
        (
            "watchdog",
            ordered(&[
                ("tripped", dumps(&json!(tripped))),
                ("deadline_s", dumps(&json!(deadline))),
            ]),
        ),
    ])
}

/// One telemetry frame.
async fn telemetry(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let head = Head::of(&req);
    blocking(st, move |st| {
        require_auth(st, &head)?;
        Ok((
            [(header::CONTENT_TYPE, "application/json")],
            telemetry_frame(st),
        )
            .into_response())
    })
    .await
}

const STREAM_Q: Model = Model {
    fields: &[
        Field(
            "interval_s",
            Kind::Float {
                gt: None,
                ge: None,
                le: None,
                default: Some(1.0),
            },
        ),
        Field(
            "max_frames",
            Kind::Opt(&Kind::Int {
                ge: i64::MIN,
                le: i64::MAX,
                default: 0,
            }),
        ),
    ],
    forbid_extra: false,
};

/// The telemetry as Server-Sent Events every `interval_s` (clamped to 0.1..10 s), `max_frames` of them when given.
async fn telemetry_stream(
    State(st): State<Arc<AppState>>,
    Query(q): Query<Vec<(String, String)>>,
    req: Request,
) -> Response {
    let head = Head::of(&req);
    let checked = (|| -> Result<(f64, Option<i64>), ApiError> {
        require_auth(&st, &head)?;
        let raw = crate::spec_routes::query(&q, STREAM_Q)?;
        let interval = raw
            .get("interval_s")
            .and_then(|v| crate::validate::as_float(v).ok())
            .unwrap_or(1.0);
        let max = raw
            .get("max_frames")
            .and_then(|v| v.as_str())
            .and_then(|s| s.trim().parse::<i64>().ok());
        Ok((interval.clamp(0.1, 10.0), max))
    })();
    let (interval, max) = match checked {
        Ok(p) => p,
        Err(e) => return e.into_response(),
    };
    let interval = std::time::Duration::from_secs_f64(interval);
    let stream = futures_util::stream::unfold(0_i64, move |n| {
        let st = st.clone();
        async move {
            if max.is_some_and(|m| n >= m) {
                return None;
            }
            if n > 0 {
                tokio::time::sleep(interval).await;
            }
            let frame = format!("data: {}\n\n", telemetry_frame(&st));
            Some((Ok::<_, std::convert::Infallible>(frame), n + 1))
        }
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

const ELIGIBILITY_Q: Model = Model {
    fields: &[Field(
        "mission",
        Kind::Str {
            min: 0,
            max: usize::MAX,
            nullable: true,
            default: None,
        },
    )],
    forbid_extra: false,
};

/// FS-28: every gate's verdict for a `GoTo` to `mission`, as the RS-01 `CommandEligibility` contract.
async fn eligibility(
    State(st): State<Arc<AppState>>,
    Query(q): Query<Vec<(String, String)>>,
    req: Request,
) -> Response {
    let head = Head::of(&req);
    blocking(st, move |st| {
        let identity = require_auth(st, &head)?;
        let raw = crate::spec_routes::query(&q, ELIGIBILITY_Q)?;
        let now = st.clock.monotonic();
        let r = role(st, &head, &identity)?;
        let mission = raw.get("mission").and_then(Value::as_str);
        let ns = match mission {
            Some(m) if is_live_mission(st, m) => Some("live"),
            Some(_) => Some("sandbox"),
            None => None,
        };
        let (tripped, idle, deadline) = {
            let wd = st.rc.wd();
            (wd.tripped, wd.seconds_idle(now), wd.deadline_s)
        };
        let rep = eligibility_report(&CommandContext {
            role: Some(&r),
            mission_namespace: ns,
            target_namespace: ns,
            safed: tripped,
            ack_age_s: idle,
            ack_deadline_s: deadline,
        });
        Ok(axum::Json(json!({"schema_version": "1.0", "eligible": rep["eligible"], "reason": rep["reason"],
            "profile": st.settings.rc.runnable_profile, "mode_ok": rep["authorized"], "released": rep["live"],
            "sensor_fresh": true, "map_fresh": true, "covariance_ok": true, "watchdog_alive": !tripped,
            "link_ack": rep["fresh"], "safe_inactive": rep["safe"]}))
        .into_response())
    })
    .await
}

const fn bounded(
    ge: f64,
    ge_s: &'static str,
    le: f64,
    le_s: &'static str,
    default: Option<f64>,
) -> Kind {
    Kind::Float {
        gt: None,
        ge: Some((ge, ge_s)),
        le: Some((le, le_s)),
        default,
    }
}

const UNIT: Kind = bounded(0.0, "0", 1.0, "1", None);
const STAMP: Kind = Kind::Float {
    gt: None,
    ge: Some((0.0, "0")),
    le: None,
    default: None,
};
const MODE: Kind = Kind::Str {
    min: 0,
    max: 16,
    nullable: true,
    default: None,
};

/// Python `RosOdomIngest`: bounded, so a malformed push cannot poison the live view.
const ODOM: Model = Model {
    fields: &[
        Field("x_m", bounded(-1e7, "-10000000", 1e7, "10000000", None)),
        Field("y_m", bounded(-1e7, "-10000000", 1e7, "10000000", None)),
        Field("yaw_rad", bounded(-7.0, "-7", 7.0, "7", Some(0.0))),
        Field("slip", Kind::Opt(&UNIT)),
        Field("soc", Kind::Opt(&UNIT)),
        Field("stamp_s", Kind::Opt(&STAMP)),
        Field("mode", MODE),
    ],
    forbid_extra: false,
};

/// Python `RosOdomFrame`: the rover's DEM-crop frame.
const FRAME: Model = Model {
    fields: &[
        Field(
            "dem",
            Kind::Str {
                min: 0,
                max: 32,
                nullable: false,
                default: None,
            },
        ),
        Field(
            "cell_m",
            Kind::Float {
                gt: Some((0.0, "0")),
                ge: None,
                le: Some((1e4, "10000")),
                default: None,
            },
        ),
        Field("dem_origin", Kind::FloatPair),
    ],
    forbid_extra: false,
};

/// The live ROS rover's odometry (latest wins; display only, never a command path).
async fn ros_odom(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let (head, bytes) = split(req, st.settings.max_body).await;
    blocking(st, move |st| {
        let body = parse_body(&bytes?)?;
        let identity = require_role(st, &head, "operator")?;
        let v = body_model(body.as_ref(), ODOM)?;
        // the nested frame model, its errors under `frame` (a non-object answered as the model's own refusal)
        let frame = match body
            .as_ref()
            .and_then(|b| b.get("frame"))
            .unwrap_or(&Value::Null)
        {
            Value::Null => Value::Null,
            f => {
                let fv = crate::validate::model(Some(f), FRAME).map_err(|e| {
                    let e = e.strip_prefix("body: ").map_or_else(
                        || {
                            e.split("; ")
                                .map(|p| format!("frame.{p}"))
                                .collect::<Vec<_>>()
                                .join("; ")
                        },
                        |rest| format!("frame: {rest}"),
                    );
                    err(StatusCode::BAD_REQUEST, e)
                })?;
                json!({"dem": fv["dem"], "cell_m": fv["cell_m"], "dem_origin": fv["dem_origin"]})
            }
        };
        let fields = vec![
            ("x_m", v["x_m"].clone()),
            ("y_m", v["y_m"].clone()),
            ("yaw_rad", v["yaw_rad"].clone()),
            ("slip", v["slip"].clone()),
            ("soc", v["soc"].clone()),
            ("stamp_s", v["stamp_s"].clone()),
            ("mode", v["mode"].clone()),
            ("frame", frame),
        ];
        *st.rc
            .odom
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner) = Some(RosOdom {
            fields,
            received: st.clock.monotonic(),
        });
        let (x, y) = (
            v["x_m"].as_f64().unwrap_or(0.0),
            v["y_m"].as_f64().unwrap_or(0.0),
        );
        audit(
            st,
            &head,
            &identity,
            "rc.ros_odom",
            &format!("{x:.1},{y:.1}"),
            &[],
        );
        Ok(axum::Json(json!({"ok": true})).into_response())
    })
    .await
}

/// The remote-control routes (the plan lowering, `/rc/plan_ros`, comes with the executive port).
pub fn routes() -> Router<Arc<AppState>> {
    Router::new()
        .route("/rc/command", post(command))
        .route("/rc/telemetry", get(telemetry))
        .route("/rc/telemetry/stream", get(telemetry_stream))
        .route("/rc/eligibility", get(eligibility))
        .route("/rc/ros_odom", post(ros_odom))
}
