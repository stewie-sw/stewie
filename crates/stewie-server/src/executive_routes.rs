//! The mission executive (RW-55c2a; Python `routers/executive`, `lode.mission_lifecycle`, `lode.mission_intent_compiler`
//! and the MO-01/MO-02 contracts): `POST /executive/advance` drives a canonical `MissionIntent` through DRAFT ->
//! ANALYZED -> REHEARSED -> REVIEWED -> RELEASED with real evidence at each edge (the compiled plan's content-hash
//! `plan_id`; the ranked forward comparison), signs the immutable revision, records the authority action on the EG-07
//! chain and freezes the release in the durable store. `POST /executive/release-plan` builds the intent from the
//! cockpit's build orders first. `GET /executive/revision/{hash}` and `GET /executive/audit` read them back.

use std::sync::Arc;

use axum::Router;
use axum::extract::{Path, Request, State};
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};

use crate::admin::{require_director, require_role};
use crate::app::{ApiError, AppState, Head, body_model, err, log, parse_body, split};
use crate::operators::py_repr;
use crate::plan_routes::{DEFAULTS, Opts, future, plan_with, rank};
use crate::validate::{Field, Kind, Model};

const fn text(default: Option<&'static str>) -> Kind {
    Kind::Str {
        min: 0,
        max: usize::MAX,
        nullable: false,
        default,
    }
}
const REQ: Kind = text(None);
const EMPTY: Kind = text(Some(""));
const VERSION: Field = Field("schema_version", text(Some("1.0")));
const FLOAT: Kind = Kind::Float {
    gt: None,
    ge: None,
    le: None,
    default: None,
};
const NON_NEG: Kind = Kind::Float {
    gt: None,
    ge: Some((0.0, "0")),
    le: None,
    default: None,
};
const POSITIVE: Kind = Kind::Float {
    gt: Some((0.0, "0")),
    ge: None,
    le: None,
    default: None,
};
const UNIT: Kind = Kind::Float {
    gt: None,
    ge: Some((0.0, "0")),
    le: Some((1.0, "1")),
    default: None,
};
const WINDOW: Kind = Kind::Opt(&Kind::FloatPair);

const ACCEPTANCE: Model = Model {
    fields: &[
        VERSION,
        Field("criterion_id", REQ),
        Field("statement", REQ),
        Field("measurable", REQ),
        Field("sensor", EMPTY),
        Field("tolerance_m", Kind::Opt(&POSITIVE)),
    ],
    forbid_extra: true,
};
const CONTINGENCY: Model = Model {
    fields: &[
        VERSION,
        Field(
            "policy",
            Kind::Enum(&["retry", "observe", "replan", "skip", "return", "safe"]),
        ),
        Field("detail", EMPTY),
    ],
    forbid_extra: true,
};
const CONSTRAINT: Model = Model {
    fields: &[
        VERSION,
        Field("constraint_id", REQ),
        Field("kind", Kind::Enum(&["hard", "flight_rule", "soft"])),
        Field("statement", REQ),
        Field("weight", Kind::Opt(&UNIT)),
    ],
    forbid_extra: true,
};
const OBJECTIVE: Model = Model {
    fields: &[
        VERSION,
        Field("objective_id", REQ),
        Field("revision", Kind::IntReq { ge: 0 }),
        Field("statement", REQ),
        Field("rationale", REQ),
        Field("priority", Kind::Enum(&["primary", "secondary", "stretch"])),
        Field("mandatory", Kind::BoolReq),
        Field("target_row", FLOAT),
        Field("target_col", FLOAT),
        Field("frame", text(Some("MOON_ME"))),
        Field("order_kind", text(Some("cut"))),
        Field(
            "acceptance",
            Kind::List {
                min: 1,
                max: usize::MAX,
                item: &ACCEPTANCE,
            },
        ),
        Field("confidence_required", UNIT),
        Field("time_window_s", WINDOW),
        Field("illumination_window_s", WINDOW),
        Field("comms_window_s", WINDOW),
        Field("energy_budget_j", Kind::Opt(&NON_NEG)),
        Field("material_budget_kg", Kind::Opt(&NON_NEG)),
        Field("data_budget_bytes", Kind::Opt(&Kind::IntReq { ge: 0 })),
        Field("prerequisites", Kind::StrList),
        Field("hold_threshold", EMPTY),
        Field("abort_threshold", EMPTY),
        Field("contingency", Kind::Nested(&CONTINGENCY)),
        Field("approver", REQ),
        Field("evidence", EMPTY),
    ],
    forbid_extra: true,
};
const COORD: Kind = Kind::Opt(&FLOAT);
const KEEPOUT: Model = Model {
    fields: &[
        VERSION,
        Field("region_id", REQ),
        Field("reason", EMPTY),
        Field("x", COORD),
        Field("y", COORD),
        Field("radius_m", Kind::Opt(&POSITIVE)),
        Field("x0", COORD),
        Field("y0", COORD),
        Field("x1", COORD),
        Field("y1", COORD),
        Field(
            "points",
            Kind::Opt(&Kind::TupleList {
                n: 2,
                max: usize::MAX,
            }),
        ),
    ],
    forbid_extra: true,
};
/// Python `MissionIntent` (MO-01): strict, every nested contract version-stamped.
const INTENT: Model = Model {
    fields: &[
        VERSION,
        Field("mission_id", REQ),
        Field("revision", Kind::IntReq { ge: 0 }),
        Field("statement", REQ),
        Field("objectives", Kind::ListDefault(&OBJECTIVE)),
        Field("constraints", Kind::ListDefault(&CONSTRAINT)),
        Field("keep_outs", Kind::ListDefault(&KEEPOUT)),
        Field("task_graph_ref", EMPTY),
    ],
    forbid_extra: true,
};

fn s<'a>(v: &'a Value, k: &str) -> &'a str {
    v[k].as_str().unwrap_or("")
}

fn items<'a>(v: &'a Value, k: &str) -> &'a [Value] {
    v[k].as_array().map_or(&[], Vec::as_slice)
}

/// The contracts' model validators (MO-01), in field order: a hard rule carries no weight, an objective lowers to a
/// build kind, a keep-out is exactly one well-formed shape.
fn model_errors(intent: &Value) -> Vec<String> {
    let mut out = Vec::new();
    for (i, o) in items(intent, "objectives").iter().enumerate() {
        let kind = s(o, "order_kind");
        if !matches!(kind, "cut" | "fill" | "sinter") {
            out.push(format!(
                "objectives.{i}: Value error, objective {} order_kind must be cut|fill|sinter, got {}",
                py_repr(s(o, "objective_id")),
                py_repr(kind)
            ));
        }
    }
    for (i, c) in items(intent, "constraints").iter().enumerate() {
        let kind = s(c, "kind");
        if matches!(kind, "hard" | "flight_rule") && !c["weight"].is_null() {
            out.push(format!(
                "constraints.{i}: Value error, MO-01: a {kind} constraint may not carry an optimization weight (a \
                 flight rule can never become a soft preference)"
            ));
        }
    }
    for (i, r) in items(intent, "keep_outs").iter().enumerate() {
        let set = |k: &str| !r[k].is_null();
        let circle = set("x") && set("y") && set("radius_m");
        let rect = ["x0", "y0", "x1", "y1"].iter().all(|k| set(k));
        let poly = set("points");
        let msg = if usize::from(circle) + usize::from(rect) + usize::from(poly) != 1 {
            Some(
                "MO-01: a KeepOutRegion must supply exactly one shape -- a circle (x,y,radius_m), a rectangle \
                 (x0,y0,x1,y1), or a polygon (points, >= 3 vertices)",
            )
        } else if poly && items(r, "points").len() < 3 {
            Some("MO-01: a KeepOutRegion polygon needs >= 3 vertices")
        } else if rect && (r["x0"] == r["x1"] || r["y0"] == r["y1"]) {
            Some("MO-01: a KeepOutRegion rectangle must have non-zero width and height")
        } else {
            None
        };
        if let Some(m) = msg {
            out.push(format!("keep_outs.{i}: Value error, {m}"));
        }
    }
    out
}

/// Validate a `MissionIntent` body into its full dump (every default filled, every number its field's type).
pub(crate) fn parse_intent(body: Option<&Value>) -> Result<Value, ApiError> {
    let v = Value::Object(body_model(body, INTENT)?);
    let errors = model_errors(&v);
    if errors.is_empty() {
        Ok(v)
    } else {
        Err(err(
            StatusCode::BAD_REQUEST,
            errors.into_iter().take(3).collect::<Vec<_>>().join("; "),
        ))
    }
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().fold(String::new(), |mut out, b| {
        use std::fmt::Write as _;
        let _ = write!(out, "{b:02x}");
        out
    })
}

/// MO-02 `SignedRevision.hash_intent`: SHA-256 of the intent's sorted compact JSON dump.
fn hash_intent(intent: &Value) -> Result<String, String> {
    let text = stewie_twin::pyjson::dumps_compact(intent).map_err(|e| format!("{e:?}"))?;
    Ok(hex(&Sha256::digest(text.as_bytes())))
}

fn float_repr(x: f64) -> String {
    stewie_twin::pyjson::float_repr(x).unwrap_or_else(|_| x.to_string())
}

/// The keyword map a soft constraint's statement names its metric by (Python `_SOFT_METRIC_KEYWORDS`, in its order).
const SOFT_METRICS: [(&str, &str); 8] = [
    ("average power", "average_power"),
    ("duration", "time"),
    ("distance", "distance"),
    ("energy", "energy"),
    ("charges", "charges"),
    ("power", "average_power"),
    ("time", "time"),
    ("mass", "mass"),
];

/// The soft constraints compiled into the weighted objective string (Python `_compile_soft_objective`).
#[allow(clippy::float_cmp)] // the Python's `w == 1.0`, exactly
fn soft_objective(intent: &Value) -> Result<String, String> {
    let mut merged: Vec<(&str, f64)> = Vec::new();
    for c in items(intent, "constraints") {
        let Some(w) = c["weight"].as_f64().filter(|_| s(c, "kind") == "soft") else {
            continue;
        };
        let text = s(c, "statement").to_lowercase().replace('_', " ");
        let found: Vec<(&str, &str)> = SOFT_METRICS
            .iter()
            .copied()
            .filter(|(kw, _)| text.contains(kw))
            .collect();
        // the longest keyword wins (`average power` over `power`); on a tie, the first found
        let Some(&(_, metric)) = found
            .iter()
            .reduce(|a, b| if b.0.len() > a.0.len() { b } else { a })
        else {
            let mut names: Vec<&str> = SOFT_METRICS.iter().map(|m| m.1).collect();
            names.sort_unstable();
            names.dedup();
            return Err(format!(
                "soft constraint {} statement {} names no known planner optimization metric; expected one of {}.",
                py_repr(s(c, "constraint_id")),
                py_repr(s(c, "statement")),
                stewie_twin::pyjson::repr_list(&names)
            ));
        };
        match merged.iter_mut().find(|(m, _)| *m == metric) {
            Some(e) => e.1 += w,
            None => merged.push((metric, w)),
        }
    }
    let spec = match merged.as_slice() {
        [] => return Ok("time".to_owned()),
        [(m, w)] if *w == 1.0 => (*m).to_owned(),
        [(m, w)] => format!("{m}:{}", float_repr(*w)),
        many => many
            .iter()
            .map(|(m, w)| format!("{m}:{}", float_repr(*w)))
            .collect::<Vec<_>>()
            .join(","),
    };
    stewie_plan::optimize::parse_objective(&spec)?;
    Ok(spec)
}

const NOMINAL_CUT_DEPTH_M: f64 = 0.1;

/// The body's bulk density (Python `planner_model.body_density`: the registry's exact key).
fn body_density(st: &AppState, body: &str) -> Result<f64, String> {
    st.planning
        .bodies
        .get(body)
        .and_then(|b| b.bulk_density)
        .ok_or_else(|| py_repr(body))
}

/// CP-04 (Python `compile_intent`): lower the intent to the planner's mission payload and weighted objective --
/// mandatory objectives as orders sized to their material budget, their prerequisites as precedence, the
/// structured hard budgets and the tightest acceptance tolerance, the keep-outs, and the soft constraints.
#[allow(clippy::too_many_lines)] // the Python's lowering, step by step
pub(crate) fn compile_intent(
    st: &AppState,
    intent: &Value,
) -> Result<(Map<String, Value>, String), String> {
    let objectives = items(intent, "objectives");
    let mandatory_ids: Vec<&str> = objectives
        .iter()
        .filter(|o| o["mandatory"] == true)
        .map(|o| s(o, "objective_id"))
        .collect();
    if mandatory_ids.is_empty() {
        return Err(
            "MissionIntent has no mandatory objective to plan (nothing to compile into orders)"
                .to_owned(),
        );
    }
    // the Python's `{id: objective}` map: a repeated id resolves to its last objective
    let by_id = |id: &str| objectives.iter().rev().find(|o| s(o, "objective_id") == id);
    let mandatory: Vec<&Value> = mandatory_ids.iter().filter_map(|id| by_id(id)).collect();
    let frames: std::collections::BTreeSet<&str> =
        objectives.iter().map(|o| s(o, "frame")).collect();
    if !frames
        .iter()
        .all(|f| matches!(*f, "MOON_ME" | "SITE_LOCAL" | "moon" | "MOON"))
    {
        return Err(format!(
            "MissionIntent objective frame(s) {} are not a known lunar planner frame; the planner is keyed by body \
             and these do not lower to 'moon'.",
            stewie_twin::pyjson::repr_list(&frames.into_iter().collect::<Vec<_>>())
        ));
    }
    let density = body_density(st, "moon")?;
    let mut orders = Vec::new();
    for o in &mandatory {
        let Some(mass) = o["material_budget_kg"].as_f64() else {
            return Err(format!(
                "objective {} has no material_budget_kg: MO-01 supplies no other work geometry the planner can size \
                 an order from, so a footprint cannot be derived (set material_budget_kg, or move the objective out \
                 of the mandatory set).",
                py_repr(s(o, "objective_id"))
            ));
        };
        orders.push(json!({"action": o["objective_id"], "kind": o["order_kind"], "x": o["target_col"],
                           "y": o["target_row"], "footprint_m2": mass / (NOMINAL_CUT_DEPTH_M * density),
                           "depth_m": NOMINAL_CUT_DEPTH_M, "note": o["statement"]}));
    }
    let mut precedence = Vec::new();
    for o in &mandatory {
        for pre in items(o, "prerequisites") {
            let pre = pre.as_str().unwrap_or("");
            let (oid, p) = (py_repr(s(o, "objective_id")), py_repr(pre));
            if by_id(pre).is_none() {
                return Err(format!(
                    "objective {oid} prerequisite {p} references an unknown objective"
                ));
            }
            if !mandatory_ids.contains(&pre) {
                return Err(format!(
                    "objective {oid} prerequisite {p} is not a mandatory objective; only mandatory objectives are \
                     compiled into orders, so its prerequisite must be too."
                ));
            }
            precedence.push(json!([pre, s(o, "objective_id")]));
        }
    }
    let mut budgets = Map::new();
    if mandatory.iter().any(|o| !o["energy_budget_j"].is_null()) {
        let e = mandatory
            .iter()
            .filter_map(|o| o["energy_budget_j"].as_f64())
            .fold(0.0, |a, x| a + x);
        budgets.insert("max_energy_J".into(), json!(e));
    }
    let closes: Vec<f64> = mandatory
        .iter()
        .filter_map(|o| o["time_window_s"][1].as_f64())
        .collect();
    if let Some(c) = closes.iter().copied().reduce(f64::max) {
        budgets.insert("max_time_s".into(), json!(c));
    }
    let tolerance = mandatory
        .iter()
        .filter_map(|o| {
            items(o, "acceptance")
                .iter()
                .filter_map(|c| c["tolerance_m"].as_f64())
                .reduce(f64::min)
        })
        .reduce(f64::min);
    let keepouts: Vec<Value> = items(intent, "keep_outs")
        .iter()
        .map(|r| {
            if !r["points"].is_null() {
                json!({"points": r["points"]})
            } else if !r["x0"].is_null() {
                json!({"x0": r["x0"], "y0": r["y0"], "x1": r["x1"], "y1": r["y1"]})
            } else {
                json!({"x": r["x"], "y": r["y"], "r": r["radius_m"]})
            }
        })
        .collect();
    let mut payload = Map::new();
    payload.insert("name".into(), intent["mission_id"].clone());
    payload.insert("body".into(), json!("moon"));
    payload.insert("orders".into(), json!(orders));
    if !precedence.is_empty() {
        payload.insert("precedence".into(), json!(precedence));
    }
    if !budgets.is_empty() {
        payload.insert("objective_constraints".into(), Value::Object(budgets));
    }
    if let Some(t) = tolerance {
        payload.insert("accept_flatness_tol_m".into(), json!(t));
    }
    if !keepouts.is_empty() {
        payload.insert("keepouts".into(), json!(keepouts));
    }
    st.planning.mission(&Value::Object(payload.clone()))?;
    Ok((payload, soft_objective(intent)?))
}

/// Python's `format(x, "g")`: six significant digits, positional for exponents -4..6, trailing zeros dropped.
fn fmt_g(x: f64) -> String {
    if x == 0.0 {
        return if x.is_sign_negative() {
            "-0".to_owned()
        } else {
            "0".to_owned()
        };
    }
    let sci = format!("{x:.5e}");
    let (mant, exp) = sci.split_once('e').unwrap_or((&sci, "0"));
    let exp: i32 = exp.parse().unwrap_or(0);
    let strip = |t: String| {
        if t.contains('.') {
            t.trim_end_matches('0').trim_end_matches('.').to_owned()
        } else {
            t
        }
    };
    if (-4..6).contains(&exp) {
        let decimals = usize::try_from(5 - exp).unwrap_or(0);
        strip(format!("{x:.decimals$}"))
    } else {
        let sign = if exp < 0 { '-' } else { '+' };
        format!("{}e{sign}{:02}", strip(mant.to_owned()), exp.abs())
    }
}

/// The cockpit's build orders as a canonical intent (Python `intent_from_orders`): each cut, fill or sinter order is
/// one mandatory primary objective sized by its excavated mass, with a 0.02 m as-built acceptance; any other order is
/// skipped and reported.
pub(crate) fn intent_from_orders(
    st: &AppState,
    orders: &[Value],
    mission_id: &str,
    approver: &str,
    body: &str,
    revision: i64,
) -> Result<(Value, Vec<Value>), String> {
    let density = body_density(st, body)?;
    let frame = if body.to_lowercase() == "moon" {
        "MOON_ME".to_owned()
    } else {
        format!("{}_ME", body.to_uppercase())
    };
    // the Python's `float(o.get(k) or 0.0)`: a falsy value is 0
    let num = |o: &Value, k: &str| -> Result<f64, String> {
        o.get(k)
            .filter(|v| crate::objects::truthy(v))
            .map_or(Ok(0.0), crate::rc_routes::py_float)
    };
    let (mut objectives, mut skipped) = (Vec::new(), Vec::new());
    for (i, o) in orders.iter().enumerate() {
        let kind = o.get("kind").cloned().unwrap_or(Value::Null);
        let Some(k) = kind
            .as_str()
            .filter(|k| matches!(*k, "cut" | "fill" | "sinter"))
        else {
            skipped.push(
                json!({"action": o.get("action").cloned().unwrap_or(Value::Null), "kind": kind}),
            );
            continue;
        };
        let mass = num(o, "footprint_m2")? * num(o, "depth_m")? * density;
        let oid = o
            .get("action")
            .filter(|v| crate::objects::truthy(v))
            .map_or_else(|| format!("obj-{i}"), crate::validate::py_str);
        let (x, y) = (num(o, "x")?, num(o, "y")?);
        let statement = o
            .get("note")
            .filter(|v| crate::objects::truthy(v))
            .cloned()
            .unwrap_or_else(|| json!(format!("{k} at ({}, {})", fmt_g(x), fmt_g(y))));
        objectives.push(json!({
            "objective_id": oid, "revision": revision, "frame": frame, "statement": statement,
            "rationale": "operator-authored build order", "priority": "primary", "mandatory": true,
            "target_row": y, "target_col": x, "order_kind": k,
            "acceptance": [{"criterion_id": format!("{oid}-ac"), "statement": format!("as-built {k} within tolerance"),
                            "measurable": "as-built RMSE <= 0.02 m", "sensor": "stereo", "tolerance_m": 0.02}],
            "confidence_required": 0.8, "material_budget_kg": mass,
            "contingency": {"policy": "safe", "detail": "loss of localization / off-nominal"}, "approver": approver,
        }));
    }
    let n = objectives.len();
    let raw = json!({"mission_id": mission_id, "revision": revision,
                     "statement": format!("release of {n} build objective(s)"), "objectives": objectives});
    let intent = parse_intent(Some(&raw)).map_err(|e| e.1)?;
    Ok((intent, skipped))
}

/// A lifecycle run: the signed revision, the evidence and the ordered transitions.
pub(crate) struct Released {
    pub(crate) signed: Value,
    pub(crate) evidence: Value,
    pub(crate) transitions: Vec<Value>,
}

/// Drive a fresh executive through DRAFT -> RELEASED (Python `run_lifecycle`) with each edge's real evidence: the
/// compiled plan's `plan_id`, then the forward comparison of `auto` and `nearest` on the site's real surface (the
/// Python plans them flat, which D-R85 refuses), then the review and the director's signature.
pub(crate) fn run_lifecycle(st: &AppState, intent: &Value) -> Result<Released, ApiError> {
    let bad = |e: String| err(StatusCode::BAD_REQUEST, e);
    let (mission, objective) = compile_intent(st, intent).map_err(bad)?;
    let p = plan_with(
        st,
        &mission,
        &Opts {
            objective: &objective,
            ..DEFAULTS
        },
    )?;
    let ir = stewie_plan::ir::plan_ir(
        &p.mission,
        &p.plan,
        &p.ctx,
        p.dem(),
        DEFAULTS.max_traverse_slope_deg,
    )
    .map_err(bad)?;
    let plan_id = ir["plan_id"].clone();
    let n_orders = mission["orders"].as_array().map_or(0, Vec::len);
    let analyzed = format!(
        "ANALYZED: intent {} rev {} compiled to plan_id={} (objective={}, orders={n_orders})",
        s(intent, "mission_id"),
        intent["revision"],
        plan_id.as_str().unwrap_or(""),
        py_repr(&objective)
    );
    let compare_objective = if matches!(objective.as_str(), "time" | "duration") {
        "duration"
    } else {
        &objective
    };
    let futures = ["auto", "nearest"]
        .into_iter()
        .map(|a| future(st, &mission, a, compare_objective))
        .collect::<Result<Vec<_>, _>>()?;
    let (futures, recommended) = rank(futures, compare_objective);
    let head = futures
        .first()
        .map(|f| stewie_twin::pyjson::dumps(f).unwrap_or_default())
        .unwrap_or_default();
    let rehearsed = format!(
        "REHEARSED: forward_compare ran {} futures over candidates ['auto', 'nearest']; recommended={} ({head})",
        futures.len(),
        recommended.as_str().unwrap_or("None")
    );
    let reviewed = "REVIEWED: analysis + rehearsal evidence accepted by the review board";
    let released = "RELEASED: director release authorization";
    let hash = hash_intent(intent).map_err(bad)?;
    Ok(Released {
        signed: json!({"schema_version": "1.0", "revision": intent["revision"], "intent": intent,
                       "signed_by": "director", "content_hash": hash}),
        evidence: json!({"plan_id": plan_id, "objective": objective, "orders": n_orders,
                         "forward_compare": {"objective": compare_objective, "futures": futures,
                                             "recommended": recommended}}),
        transitions: vec![
            json!({"to": "analyzed", "role": "planner", "evidence": analyzed}),
            json!({"to": "rehearsed", "role": "operator", "evidence": rehearsed}),
            json!({"to": "reviewed", "role": "reviewer", "evidence": reviewed}),
            json!({"to": "released", "role": "director", "evidence": released}),
        ],
    })
}

/// One EG-07 authority record, stamped with the server clock's UTC time.
pub(crate) fn record_action(
    st: &AppState,
    actor: &str,
    action: &str,
    location: &str,
    reason: &str,
    states: (&str, &str),
    evidence: &str,
) -> Result<(), String> {
    let ts = crate::audit_chain::iso_utc(st.clock.now());
    crate::audit_chain::append(
        &st.cfg.data_dir,
        [
            actor, action, &ts, location, "sim", reason, states.0, states.1, evidence,
        ],
    )
    .map(|_| ())
}

#[allow(clippy::too_many_arguments)] // the Python's bracket, its two records' fields
/// Record the intent, freeze the release, log it and record the outcome (the Python's fail-closed audit bracket around
/// the best-effort persist); `Err` is the 503 to answer.
async fn sign_and_persist(
    st: &AppState,
    head: &Head,
    identity: &str,
    action: &str,
    location: &str,
    rel: &Released,
    outcome_reason: &str,
    log_target: &str,
) -> Result<bool, (bool, String)> {
    let hash = s(&rel.signed, "content_hash").to_owned();
    record_action(
        st,
        identity,
        &format!("{action}.intent"),
        location,
        "prepare durable signed-revision persistence",
        ("reviewed", "pending"),
        &hash,
    )
    .map_err(|e| {
        (
            false,
            format!("audit unavailable; released revision was not persisted: {e}"),
        )
    })?;
    let art = json!({"content_hash": hash, "revision": rel.signed["revision"], "mission_id": rel.signed["intent"]["mission_id"],
                     "signed_by": "director", "signed_revision": rel.signed, "evidence": rel.evidence,
                     "transitions": rel.transitions});
    let persisted = match st
        .edit_sessions
        .persist_release_revision(&art, st.clock.now())
        .await
    {
        Ok(p) => p,
        Err(e) => {
            eprintln!(
                "release-revision persist failed (release still valid): {}",
                e.1
            );
            false
        }
    };
    log(st, head, identity, action, log_target);
    let after = if persisted {
        "released"
    } else {
        "release_not_persisted"
    };
    record_action(
        st,
        identity,
        action,
        location,
        outcome_reason,
        ("pending", after),
        &hash,
    )
    .map_err(|e| {
        (
            persisted,
            format!("release completed but audit result append failed: {e}"),
        )
    })?;
    Ok(persisted)
}

async fn advance(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let (head, bytes) = split(req, st.settings.max_body).await;
    advance_on(&st, &head, bytes)
        .await
        .unwrap_or_else(IntoResponse::into_response)
}

async fn advance_on(
    st: &AppState,
    head: &Head,
    bytes: Result<axum::body::Bytes, ApiError>,
) -> Result<Response, ApiError> {
    let body = parse_body(&bytes?)?;
    let identity = require_director(st, head)?;
    let intent = parse_intent(body.as_ref())?;
    let rel = run_lifecycle(st, &intent)?;
    let (mission_id, revision) = (s(&intent, "mission_id"), &intent["revision"]);
    let target = format!("{mission_id} rev {revision} -> released");
    let persisted = match sign_and_persist(
        st,
        head,
        &identity,
        "executive.advance",
        mission_id,
        &rel,
        "signed revision persistence completed",
        &target,
    )
    .await
    {
        Ok(p) => p,
        Err((persisted, e)) => {
            let mut body = json!({"ok": false, "error": e});
            if e.starts_with("release completed") {
                body["revision_persisted"] = json!(persisted);
            }
            return Ok((StatusCode::SERVICE_UNAVAILABLE, axum::Json(body)).into_response());
        }
    };
    Ok(axum::Json(
        json!({"ok": true, "label": "sim", "state": "released", "signed_revision": rel.signed,
                         "revision_persisted": persisted, "evidence": rel.evidence,
                         "transitions": rel.transitions}),
    )
    .into_response())
}

/// Python `ReleasePlanRequest`.
const RELEASE: Model = Model {
    fields: &[
        Field("orders", Kind::DictList { min: 0, max: 1000 }),
        Field("body", text(Some("moon"))),
        Field("mission_id", text(Some("cockpit-release"))),
        Field(
            "revision",
            Kind::Int {
                ge: 0,
                le: i64::MAX,
                default: 0,
            },
        ),
    ],
    forbid_extra: false,
};

/// FS-28 / AR-003: the command-authority card frozen at sign time; live authority only for a durably stored release.
fn command_authority(st: &AppState, signed: &Value, persisted: bool) -> Value {
    let profile: Value = serde_json::from_str(st.settings.system_profile).unwrap_or(Value::Null);
    let selected = &profile["sensors"]["selected_depth_source"];
    let mut card = json!({"plan_hash": signed["content_hash"], "signed_by": signed["signed_by"],
                          "runtime_profile": profile["profile_id"],
                          "sensor_profile": if selected.is_null() { "None".to_owned() } else { crate::validate::py_str(selected) },
                          "watchdog_deadline_s": 5.0});
    if persisted {
        card["namespace"] = json!("live");
        card["authorized"] = json!(true);
    } else {
        card["namespace"] = json!("sandbox");
        card["authorized"] = json!(false);
        card["reason"] = json!(
            "revision not durably persisted (revision_persisted:false); command authority withheld \
                                until the release is durably stored"
        );
    }
    card
}

async fn release_plan(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let (head, bytes) = split(req, st.settings.max_body).await;
    release_plan_on(&st, &head, bytes)
        .await
        .unwrap_or_else(IntoResponse::into_response)
}

async fn release_plan_on(
    st: &AppState,
    head: &Head,
    bytes: Result<axum::body::Bytes, ApiError>,
) -> Result<Response, ApiError> {
    let body = parse_body(&bytes?)?;
    let identity = require_director(st, head)?;
    let v = body_model(body.as_ref(), RELEASE)?;
    let (mission_id, body_name) = (
        s(&Value::Object(v.clone()), "mission_id").to_owned(),
        v["body"].as_str().unwrap_or("moon").to_owned(),
    );
    let refuse = |e: String, skipped: Value| {
        Ok((
            StatusCode::BAD_REQUEST,
            axum::Json(json!({"ok": false, "error": e, "skipped": skipped})),
        )
            .into_response())
    };
    let orders = v["orders"].as_array().cloned().unwrap_or_default();
    let revision = v["revision"].as_i64().unwrap_or(0);
    let (intent, skipped) =
        match intent_from_orders(st, &orders, &mission_id, &identity, &body_name, revision) {
            Ok(r) => r,
            Err(e) => return refuse(e, json!([])),
        };
    let n = items(&intent, "objectives").len();
    if n == 0 {
        return refuse(
            "no build orders to release (cut/fill/sinter): the queue has only path/other orders"
                .to_owned(),
            json!(skipped),
        );
    }
    let rel = match run_lifecycle(st, &intent) {
        Ok(r) => r,
        Err(e) if e.0 == StatusCode::BAD_REQUEST => return refuse(e.1, json!([])),
        Err(e) => return Err(e),
    };
    let hash = s(&rel.signed, "content_hash").to_owned();
    let target = format!("{mission_id}: {n} objectives -> released");
    let persisted = match sign_and_persist(
        st,
        head,
        &identity,
        "executive.release_plan",
        &mission_id,
        &rel,
        &format!("{n} objectives released"),
        &target,
    )
    .await
    {
        Ok(p) => p,
        Err((persisted, e)) => {
            let mut body = json!({"ok": false, "error": e, "skipped": skipped});
            if e.starts_with("release completed") {
                body["revision_persisted"] = json!(persisted);
                body["signed_revision_hash"] = json!(hash);
            }
            return Ok((StatusCode::SERVICE_UNAVAILABLE, axum::Json(body)).into_response());
        }
    };
    Ok(axum::Json(json!({"ok": true, "label": "sim", "state": "released", "signed_revision": rel.signed,
                         "command_authority": command_authority(st, &rel.signed, persisted),
                         "revision_persisted": persisted, "evidence": rel.evidence,
                         "transitions": rel.transitions, "released_objectives": n, "skipped": skipped}))
    .into_response())
}

/// A durably frozen released revision by its content hash; operator+.
async fn revision(
    State(st): State<Arc<AppState>>,
    Path(hash): Path<String>,
    req: Request,
) -> Response {
    let head = Head::of(&req);
    async {
        require_role(&st, &head, "operator")?;
        Ok::<_, ApiError>(match st.edit_sessions.read_release_revision(&hash).await? {
            Some(rec) => axum::Json(json!({"ok": true, "revision": rec})).into_response(),
            None => err(
                StatusCode::NOT_FOUND,
                format!("no released revision {}", py_repr(&hash)),
            )
            .into_response(),
        })
    }
    .await
    .unwrap_or_else(IntoResponse::into_response)
}

/// The EG-07 executive audit chain with its three-valued integrity; operator+.
async fn audit(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let head = Head::of(&req);
    crate::app::blocking(st, move |st| {
        require_role(st, &head, "operator")?;
        let chain = crate::audit_chain::load(&st.cfg.data_dir);
        Ok(axum::Json(
            json!({"ok": true, "verified": chain.integrity(), "count": chain.records.len(),
                             "records": chain.records}),
        )
        .into_response())
    })
    .await
}

/// The executive routes (the SIM run, its stream and `/rc/plan_ros` come next).
pub fn routes() -> Router<Arc<AppState>> {
    Router::new()
        .route("/executive/advance", post(advance))
        .route("/executive/release-plan", post(release_plan))
        .route("/executive/revision/{content_hash}", get(revision))
        .route("/executive/audit", get(audit))
}
