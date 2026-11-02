//! The director's maintenance operations (RW-55b21; Python `routers.admin_ops`, `server.ops_governance`): a
//! restorable snapshot of the default observed twin, the snapshot retention ladder, the off-host replica of the
//! journal and snapshots, and the PO-15 governance view (the declared recovery-point policy, each backup job's last
//! success read from its artifacts on disk against that policy, and the newest maintenance actions in the ledger).

use std::path::{Path, PathBuf};
use std::sync::Arc;

use axum::Router;
use axum::extract::{Query, Request, State};
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use serde_json::{Value, json};
use stewie_twin::backup;

use crate::admin::require_director;
use crate::app::{AppState, Head, blocking, err, log};
use crate::state::{DEFAULT_TWIN_SITE, DEFAULT_TWIN_SOURCE};
use crate::validate::{self, Field, Kind, Model};

/// The snapshot retention ladder `backup::apply_retention` enforces (the Python's signature defaults).
const KEEP_RECENT: usize = 5;
const LADDER: u64 = 10;
/// The maintenance actions the governance trail shows (account admin has its own view).
const OPS_ACTION_PREFIXES: [&str; 3] = ["admin.twin.", "admin.backup.", "admin.gates."];

fn internal(e: &dyn std::fmt::Display) -> crate::app::ApiError {
    err(StatusCode::INTERNAL_SERVER_ERROR, e.to_string())
}

/// The off-host replica: `STEWIE_BACKUP_DIR`, else `data_dir/replica`.
fn replica_dir(st: &AppState) -> PathBuf {
    st.settings
        .backup_dir
        .as_deref()
        .map_or_else(|| st.cfg.data_dir.join("replica"), PathBuf::from)
}

/// Snapshot the default observed twin (director).
async fn snapshot(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let h = Head::of(&req);
    blocking(st, move |st| {
        let director = require_director(st, &h)?;
        let tw = st
            .terrain
            .twin(DEFAULT_TWIN_SITE, DEFAULT_TWIN_SOURCE)
            .map_err(|e| internal(&e))?;
        let path = {
            let t = tw.lock().unwrap_or_else(std::sync::PoisonError::into_inner);
            backup::snapshot(&t, &st.cfg.data_dir.join("snapshots")).map_err(|e| internal(&e))?
        };
        let name = path
            .file_name()
            .and_then(|n| n.to_str())
            .unwrap_or("")
            .to_owned();
        log(st, &h, &director, "admin.twin.snapshot", &name);
        Ok(axum::Json(json!({"ok": true, "snapshot": path.display().to_string()})).into_response())
    })
    .await
}

/// Apply the snapshot retention ladder (director); the kept snapshots are reported (the Python names them
/// `removed`).
async fn retention(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let h = Head::of(&req);
    blocking(st, move |st| {
        let director = require_director(st, &h)?;
        let kept = backup::apply_retention(&st.cfg.data_dir.join("snapshots"), KEEP_RECENT, LADDER)
            .map_err(|e| internal(&e))?;
        log(
            st,
            &h,
            &director,
            "admin.twin.retention",
            &format!("{} removed", kept.len()),
        );
        Ok(axum::Json(json!({"ok": true, "removed": kept})).into_response())
    })
    .await
}

/// Mirror the journal and snapshots to the replica (director). As the Python's, a failed mirror is a 200 whose
/// body says `ok: false`.
async fn replicate(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let h = Head::of(&req);
    blocking(st, move |st| {
        let director = require_director(st, &h)?;
        let (data, dest) = (st.cfg.data_dir.clone(), replica_dir(st));
        let items: Vec<&str> = ["twin.journal", "snapshots", "twin"]
            .into_iter()
            .filter(|p| data.join(p).exists())
            .collect();
        let out = if items.is_empty() {
            std::fs::create_dir_all(&dest).map_err(|e| internal(&e))?;
            json!({"ok": false, "error": format!("nothing to replicate in {}", data.display())})
        } else {
            match backup::replicate(&data, &dest) {
                Ok(items) => json!({"ok": true, "items": items, "error": ""}),
                Err(e) => {
                    let msg = e.to_string();
                    let tail: String = msg
                        .chars()
                        .rev()
                        .take(300)
                        .collect::<Vec<_>>()
                        .into_iter()
                        .rev()
                        .collect();
                    json!({"ok": false, "items": items, "error": tail})
                }
            }
        };
        log(
            st,
            &h,
            &director,
            "admin.backup.replicate",
            &dest.display().to_string(),
        );
        Ok(axum::Json(out).into_response())
    })
    .await
}

fn mtime(p: &Path) -> Option<f64> {
    std::fs::metadata(p)
        .ok()?
        .modified()
        .ok()?
        .duration_since(std::time::UNIX_EPOCH)
        .ok()
        .map(|d| d.as_secs_f64())
}

/// The newest file's mtime anywhere under `root` (Python `os.walk`).
fn newest_tree_mtime(root: &Path) -> Option<f64> {
    let mut best: Option<f64> = None;
    let mut stack = vec![root.to_path_buf()];
    while let Some(d) = stack.pop() {
        for e in std::fs::read_dir(&d).into_iter().flatten().flatten() {
            let p = e.path();
            if p.is_dir() {
                stack.push(p);
            } else if let Some(m) = mtime(&p) {
                best = Some(best.map_or(m, |b: f64| b.max(m)));
            }
        }
    }
    best
}

/// One job's signal: whether it ever ran, when, how long ago, and whether that is inside its RPO.
fn job(last: Option<f64>, rpo_s: f64, now: f64) -> Value {
    let r = stewie_twin::numpy::round;
    match last {
        None => {
            json!({"present": false, "last_success_ts": null, "age_s": null, "rpo_s": rpo_s, "within_rpo": false})
        }
        Some(t) => {
            let age = (now - t).max(0.0);
            json!({"present": true, "last_success_ts": r(t, 3), "age_s": r(age, 3), "rpo_s": rpo_s,
                   "within_rpo": age <= rpo_s})
        }
    }
}

const GOVERNANCE_Q: Model = Model {
    fields: &[Field(
        "n",
        Kind::Int {
            ge: i64::MIN,
            le: i64::MAX,
            default: 20,
        },
    )],
    forbid_extra: false,
};

/// The PO-15 operations governance (director): the declared policy, the monitored backup jobs, the newest
/// maintenance actions (account admin excluded).
async fn governance(
    State(st): State<Arc<AppState>>,
    Query(q): Query<Vec<(String, String)>>,
    req: Request,
) -> Response {
    let h = Head::of(&req);
    blocking(st, move |st| {
        require_director(st, &h)?;
        let raw = crate::spec_routes::query(&q, GOVERNANCE_Q)?;
        let n = raw.get("n").and_then(|v| validate::as_int(v).ok()).unwrap_or(20).clamp(1, 500);
        let now = st.clock.now();
        let (snap_rpo, rep_rpo) = (st.settings.snapshot_rpo_s, st.settings.replica_rpo_s);
        // the newest `twin_v*` snapshot is the last snapshot success
        let snap = std::fs::read_dir(st.cfg.data_dir.join("snapshots"))
            .into_iter()
            .flatten()
            .flatten()
            .filter(|e| e.file_name().to_str().is_some_and(|n| n.starts_with("twin_v")))
            .filter_map(|e| mtime(&e.path()))
            .fold(None, |b: Option<f64>, m| Some(b.map_or(m, |b| b.max(m))));
        let jobs = json!({"snapshot": job(snap, snap_rpo, now), "replica": job(newest_tree_mtime(&replica_dir(st)), rep_rpo, now)});
        let degraded = jobs.as_object().is_some_and(|j| j.values().any(|v| v["within_rpo"] != true));
        // the newest-first maintenance tail, over the whole ledger so sparse actions are not lost
        let text = std::fs::read_to_string(st.cfg.data_dir.join("events.jsonl")).unwrap_or_default();
        #[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)] // clamped to 1..=500
        let recent: Vec<Value> = text
            .lines()
            .rev()
            .filter_map(|l| serde_json::from_str::<Value>(l).ok())
            .filter(|ev| {
                let a = match &ev["action"] {
                    Value::String(s) => s.clone(),
                    Value::Null => String::new(),
                    other => stewie_twin::pyjson::repr(other),
                };
                OPS_ACTION_PREFIXES.iter().any(|p| a.starts_with(p))
            })
            .take(n as usize)
            .collect();
        Ok(axum::Json(json!({
            "ok": true,
            "policy": {"snapshot_rpo_s": snap_rpo, "replica_rpo_s": rep_rpo, "keep_recent": KEEP_RECENT, "ladder": LADDER},
            "jobs": jobs, "degraded": degraded, "checked_at": stewie_twin::numpy::round(now, 3),
            "recent_ops": recent,
        }))
        .into_response())
    })
    .await
}

/// The maintenance routes.
pub fn routes() -> Router<Arc<AppState>> {
    Router::new()
        .route("/admin/twin/snapshot", post(snapshot))
        .route("/admin/twin/retention", post(retention))
        .route("/admin/backup/replicate", post(replicate))
        .route("/admin/ops/governance", get(governance))
}
