//! The evidence surfaces (RW-55b19; Python `routers.evidence`, `routers.nav.get_ros_evidence`): the navigation
//! evidence (comparison against the cited baselines, the capability matrix, the modality precision, the operational
//! cost), the ROS/Gazebo/RViz evidence read from the committed contract and configs, and the EV-01 evidence bundle
//! that reproduces what a mission ran on from the persisted sources, with the host-gated run captures shown as not
//! captured unless a run persisted one. The code-defined parts are exported from the Python (`evidence.json`).

use std::sync::{Arc, LazyLock};

use axum::Router;
use axum::extract::{Query, Request, State};
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::routing::get;
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};

use crate::app::{ApiError, AppState, Head, blocking, err, require_auth};
use crate::validate::{self, Field, Kind, Model};

static EVIDENCE: LazyLock<Value> = LazyLock::new(|| {
    serde_json::from_str(include_str!(
        "../../stewie-contracts/fixtures/evidence.json"
    ))
    .unwrap_or(Value::Null)
});

fn with_ok(v: &Value) -> Value {
    let mut out = Map::new();
    out.insert("ok".into(), json!(true));
    if let Some(o) = v.as_object() {
        out.extend(o.clone());
    }
    Value::Object(out)
}

/// The navigation evidence (public, published methodology).
async fn evidence() -> Response {
    axum::Json(with_ok(&EVIDENCE["evidence"])).into_response()
}

/// The ROS/Gazebo/RViz evidence (any authenticated caller, FS-27).
async fn ros_evidence(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let h = Head::of(&req);
    blocking(st, move |st| {
        require_auth(st, &h)?;
        Ok(axum::Json(with_ok(&EVIDENCE["ros_evidence"])).into_response())
    })
    .await
}

/// The plan inputs: the world log's plan transactions, and the persisted report artifacts (the 25 newest PDFs).
#[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)] // whole-second mtimes
fn plan_inputs(st: &AppState, mission: Option<&str>) -> Value {
    let txns: Vec<Value> = st
        .world
        .recent(500)
        .into_iter()
        .filter(|t| {
            t.get("plan_id")
                .is_some_and(|p| !p.is_null() && p != "" && p != false)
        })
        .filter(|t| {
            mission.is_none_or(|m| t.get("mission").and_then(Value::as_str).unwrap_or("") == m)
        })
        .collect();
    let dir = st.cfg.data_dir.join("reports");
    let mut pdfs: Vec<(std::path::PathBuf, f64, u64)> = std::fs::read_dir(&dir)
        .into_iter()
        .flatten()
        .flatten()
        .map(|e| e.path())
        .filter(|p| p.extension().is_some_and(|x| x == "pdf"))
        .filter_map(|p| {
            let m = std::fs::metadata(&p).ok()?;
            let t = m
                .modified()
                .ok()?
                .duration_since(std::time::UNIX_EPOCH)
                .ok()?
                .as_secs_f64();
            Some((p, t, m.len()))
        })
        .collect();
    pdfs.sort_by(|a, b| b.1.total_cmp(&a.1));
    let reports: Vec<Value> = pdfs
        .iter()
        .take(25)
        .map(|(p, t, len)| {
            let stem = p.file_stem().and_then(|s| s.to_str()).unwrap_or("").to_owned();
            let name = p.file_name().and_then(|s| s.to_str()).unwrap_or("");
            let md = dir.join(format!("{stem}.md")).is_file().then(|| format!("/reports/{stem}.md"));
            json!({"stem": stem, "pdf": format!("/reports/{name}"), "md": md, "size_bytes": len, "mtime": *t as i64})
        })
        .collect();
    json!({"plan_transactions": txns, "n_plans": txns.len(), "reports": reports, "n_reports": reports.len(),
           "note": "plan inputs are reproduced from the durable world-log record_plan transactions (which plan_id/mission \
                    ran) + the persisted report artifacts (the plan records). The executable Plan IR is a re-derivable \
                    view (POST /plan), not stored verbatim -- so it is not claimed as a persisted artifact here."})
}

/// The selected layers: the catalog's planning-eligible layers with their source-class confidence, and the site's
/// freshness (its observed twin and as-built versions).
fn selected_layers(st: &AppState, site: &str) -> Value {
    let cat: Value = serde_json::from_str(crate::world_routes::CATALOG).unwrap_or(Value::Null);
    let layers = cat["layers"].as_array().cloned().unwrap_or_default();
    let planning: Vec<Value> = layers
        .iter()
        .filter(|l| l["planning_eligible"].as_bool().unwrap_or(false))
        .map(|l| {
            let sc = l["source_class"].as_str().unwrap_or("");
            json!({"id": l["id"], "domain": l["domain"], "type": l["type"], "source_class": sc,
                   "confidence": crate::world_routes::layer_confidence(sc),
                   "release_execute_eligible": l["release_execute_eligible"].as_bool().unwrap_or(false)})
        })
        .collect();
    let freshness = crate::world_routes::enrichment(st, site).map(|e| {
        json!({"observed": e.observed, "observed_fraction": e.observed_fraction,
               "provenance_class": if e.observed_fraction > 0.0 { "observed" } else { "prior" },
               "dem_source": e.dem_source, "twin_version": e.twin_version, "as_built_version": e.as_built_version,
               "mutated": e.mutated})
    });
    json!({"catalog_count": layers.len(), "planning_layers": planning, "n_planning_layers": planning.len(),
           "freshness": freshness})
}

/// The executive audit chain (optionally narrowed to one mission's location) and an edit session's audit tail.
async fn audit(
    st: &AppState,
    mission: Option<&str>,
    session: Option<&str>,
) -> Result<Value, ApiError> {
    let chain = crate::audit_chain::load(&st.cfg.data_dir);
    let records: Vec<Value> = chain
        .records
        .iter()
        .filter(|r| {
            mission.is_none_or(|m| {
                r.get("location")
                    .map(value_str)
                    .unwrap_or_default()
                    .contains(m)
            })
        })
        .map(|r| Value::Object(r.clone()))
        .collect();
    let mut out = json!({"executive": {"verified": chain.integrity(), "count": chain.records.len(),
                                       "returned": records.len(), "records": records}});
    if let Some(sid) = session {
        out["edit_session"] = match crate::edit_session::session_audit(st, sid).await? {
            None => json!({"session": sid, "found": false,
                           "note": "no such edit session (a stale id is honestly reported, not faked)"}),
            Some((id, version, audit)) => {
                json!({"session": id, "found": true, "version": version, "audit": audit})
            }
        };
    }
    Ok(out)
}

/// Python `str()` of a JSON value.
fn value_str(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        other => stewie_twin::pyjson::repr(other),
    }
}

/// The run artifacts: the committed ROS/Gazebo/RViz evidence, and each host-gated capture kind, real when a run
/// persisted it under `data_dir/captures/<kind>`.
fn artifacts(st: &AppState) -> Value {
    let kinds = EVIDENCE["capture_kinds"]
        .as_array()
        .cloned()
        .unwrap_or_default();
    let captures: Vec<Value> = kinds
        .iter()
        .map(|k| {
            let kind = k["kind"].as_str().unwrap_or("");
            let mut present: Vec<String> = std::fs::read_dir(st.cfg.data_dir.join("captures").join(kind))
                .into_iter()
                .flatten()
                .flatten()
                .filter_map(|e| e.file_name().to_str().map(str::to_owned))
                .filter(|n| !n.starts_with('.'))
                .collect();
            present.sort();
            if present.is_empty() {
                json!({"kind": kind, "what": k["what"], "captured": false, "reason": k["reason"]})
            } else {
                let paths: Vec<String> = present.iter().take(20).map(|n| format!("/captures/{kind}/{n}")).collect();
                json!({"kind": kind, "what": k["what"], "captured": true, "paths": paths, "count": present.len()})
            }
        })
        .collect();
    let gated: Vec<Value> = kinds.iter().map(|k| k["kind"].clone()).collect();
    json!({"ros_gazebo_rviz": EVIDENCE["ros_evidence"], "captures": captures, "host_gated_kinds": gated})
}

const BUNDLE_Q: Model = Model {
    fields: &[
        Field(
            "site",
            Kind::Str {
                min: 0,
                max: usize::MAX,
                nullable: false,
                default: Some("haworth"),
            },
        ),
        Field(
            "mission",
            Kind::Str {
                min: 0,
                max: usize::MAX,
                nullable: true,
                default: None,
            },
        ),
        Field(
            "session",
            Kind::Str {
                min: 0,
                max: usize::MAX,
                nullable: true,
                default: None,
            },
        ),
        Field(
            "limit",
            Kind::Int {
                ge: i64::MIN,
                le: i64::MAX,
                default: 50,
            },
        ),
    ],
    forbid_extra: false,
};

/// The EV-01 evidence bundle (public read): one assembly of what a mission ran on, self-attesting by a SHA-256 of
/// its sorted JSON (the same persisted state gives the same `bundle_sha`).
async fn bundle(
    State(st): State<Arc<AppState>>,
    Query(q): Query<Vec<(String, String)>>,
) -> Response {
    let raw = match crate::spec_routes::query(&q, BUNDLE_Q) {
        Ok(r) => r,
        Err(e) => return e.into_response(),
    };
    let s = |k: &str| raw.get(k).and_then(Value::as_str).map(str::to_owned);
    let (site, mission, session) = (
        s("site").unwrap_or_else(|| "haworth".to_owned()),
        s("mission"),
        s("session"),
    );
    let limit = raw
        .get("limit")
        .and_then(|v| validate::as_int(v).ok())
        .unwrap_or(50)
        .clamp(1, 500);
    let audit = match audit(&st, mission.as_deref(), session.as_deref()).await {
        Ok(a) => a,
        Err(e) => return e.into_response(),
    };
    blocking(st, move |st| {
        let txns: Vec<Value> = st
            .world
            .recent(usize::try_from(limit).unwrap_or(1))
            .into_iter()
            .filter(|t| {
                mission.as_deref().is_none_or(|m| t.get("mission").and_then(Value::as_str).unwrap_or("") == m)
            })
            .collect();
        let gated = EVIDENCE["capture_kinds"]
            .as_array()
            .map(|a| a.iter().map(|k| k["kind"].clone()).collect::<Vec<_>>())
            .unwrap_or_default();
        let mut body = json!({
            "ok": true, "site": site, "mission": mission, "session": session,
            "plan_inputs": plan_inputs(st, mission.as_deref()),
            "selected_layers": selected_layers(st, &site),
            "assumptions": EVIDENCE["assumptions"], "runtime_profile": EVIDENCE["runtime_profile"],
            "world_transactions": {"count": st.world.transaction_count(), "verified": st.world.verify_chain(),
                                   "transactions": txns, "returned": txns.len()},
            "audit": audit, "artifacts": artifacts(st),
            "reproduced": ["plan_inputs", "selected_layers", "assumptions", "runtime_profile", "world_transactions",
                           "audit"],
            "host_gated": gated,
        });
        let text = stewie_twin::pyjson::dumps(&body).map_err(|e| err(StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;
        let sha = Sha256::digest(text.as_bytes()).iter().fold(String::new(), |mut s, b| {
            use std::fmt::Write as _;
            let _ = write!(s, "{b:02x}");
            s
        });
        body["bundle_sha"] = json!(sha);
        Ok(axum::Json(body).into_response())
    })
    .await
}

/// The evidence routes.
pub fn routes() -> Router<Arc<AppState>> {
    Router::new()
        .route("/evidence", get(evidence))
        .route("/evidence/bundle", get(bundle))
        .route("/ros/evidence", get(ros_evidence))
}
