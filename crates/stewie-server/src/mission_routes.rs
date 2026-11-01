//! Missions, drafts and soils (RW-55b9; Python `routers.missions` over `server.objects`). Every mission route is
//! namespace-aware (AG-07): a trainee or guest is confined to their own sandbox; an operator and above works on live
//! by default and may target their own sandbox with `?ns=sandbox`. Publishing promotes a sandbox draft into live.
//! Drafts and soils are per-owner and sandbox-only, under one autosave quota.

use std::sync::Arc;

use axum::Router;
use axum::extract::{Path, Query, Request, State};
use axum::http::{Method, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::{delete, get, post};
use serde_json::{Map, Value, json};

use crate::admin::require_role;
use crate::app::{
    ApiError, AppState, Head, blocking, err, log, no_route_for, parse_body, require_auth, split,
};
use crate::objects::{self as obj, ArtifactLock, Namespace};
use crate::operators::{py_repr, role_rank};
use crate::validate;

const MISSIONS: &str = "missions";
const MISSION_KEYS: [&str; 10] = [
    "body",
    "orders",
    "keepouts",
    "precedence",
    "vehicle",
    "tools",
    "soil",
    "lander",
    "mission_t0_s",
    "note",
];
const DRAFT_KEYS: [&str; 6] = [
    "body",
    "orders",
    "keepouts",
    "landmarks",
    "step_done",
    "wiz_step",
];
const SOIL_KEYS: [&str; 6] = [
    "bekker",
    "cohesion_pa",
    "friction_deg",
    "bulk_density",
    "confidence",
    "provenance",
];

fn server_error(e: impl Into<String>) -> ApiError {
    err(StatusCode::INTERNAL_SERVER_ERROR, e)
}

fn role(st: &AppState, h: &Head, identity: &str) -> Result<String, ApiError> {
    st.auth(Some(&h.cid))
        .role_of(identity)
        .map_err(server_error)
}

/// The last value of a repeated query key, as the Python reads a query parameter.
fn param<'a>(q: &'a [(String, String)], key: &str) -> Option<&'a str> {
    q.iter()
        .rev()
        .find(|(k, _)| k == key)
        .map(|(_, v)| v.as_str())
}

/// The request's namespace (Python `deps.namespace_for`): below operator, the caller's own sandbox whatever was
/// asked; otherwise live, or the caller's own sandbox on `ns=sandbox`.
fn namespace_for<'a>(
    st: &AppState,
    h: &Head,
    identity: &'a str,
    requested: &str,
) -> Result<Namespace<'a>, ApiError> {
    let rank = role_rank(Some(&role(st, h, identity)?));
    Ok(
        if rank < role_rank(Some("operator")) || requested == "sandbox" {
            Namespace::Sandbox(Some(identity))
        } else {
            Namespace::Live
        },
    )
}

fn label(ns: Namespace<'_>) -> &'static str {
    match ns {
        Namespace::Live => "live",
        Namespace::Sandbox(_) => "sandbox",
    }
}

/// A JSON body that must be an object (the `FastAPI` `doc: dict` parameter).
fn body_dict(body: Option<&Value>) -> Result<Map<String, Value>, ApiError> {
    validate::dict(body)
        .cloned()
        .map_err(|e| err(StatusCode::BAD_REQUEST, e))
}

/// Save a mission in the resolved namespace; overwriting needs its owner or a director (SR-01).
async fn save(
    State(st): State<Arc<AppState>>,
    Path(name): Path<String>,
    Query(query): Query<Vec<(String, String)>>,
    req: Request,
) -> Response {
    if name.contains('/') {
        return no_route_for(&Method::POST, &format!("/missions/{name}"));
    }
    let (h, bytes) = split(req, st.settings.max_body).await;
    blocking(st, move |st| {
        let body = parse_body(&bytes?)?;
        let identity = require_auth(st, &h)?;
        let doc = body_dict(body.as_ref())?;
        let ns = namespace_for(st, &h, &identity, param(&query, "ns").unwrap_or("live"))?;
        let director = role(st, &h, &identity)? == "director";
        let data = &st.cfg.data_dir;
        let _lock = ArtifactLock::take(data, MISSIONS, &name, ns).map_err(server_error)?;
        let path = obj::artifact_path(data, MISSIONS, &name, ns).map_err(server_error)?;
        if !obj::write_allowed(obj::owner_of(&path).as_deref(), &identity, director) {
            return Err(err(
                StatusCode::FORBIDDEN,
                format!(
                    "mission {} belongs to another operator; only its owner or a director may overwrite it",
                    py_repr(&name)
                ),
            ));
        }
        if let Some(u) = obj::unknown_fields(&doc, &MISSION_KEYS) {
            return Err(err(StatusCode::BAD_REQUEST, format!("unknown mission fields {u}")));
        }
        let slug = obj::slug(&name);
        let meta = obj::owner_meta(&path, &identity, st.clock.now());
        let created_by = meta.0.clone();
        obj::write_doc(&path, &[("name", json!(slug)), ("title", json!(name))], meta, &doc).map_err(server_error)?;
        log(st, &h, &identity, "mission.save", &slug);
        Ok(axum::Json(json!({"ok": true, "namespace": label(ns), "name": slug, "created_by": created_by})).into_response())
    })
    .await
}

/// The missions of the resolved namespace (any authenticated caller).
async fn list(
    State(st): State<Arc<AppState>>,
    Query(query): Query<Vec<(String, String)>>,
    req: Request,
) -> Response {
    let h = Head::of(&req);
    blocking(st, move |st| {
        let identity = require_auth(st, &h)?;
        let ns = namespace_for(st, &h, &identity, param(&query, "ns").unwrap_or("live"))?;
        let rows = obj::list_missions(&st.cfg.data_dir, ns).map_err(server_error)?;
        Ok(
            axum::Json(json!({"ok": true, "namespace": label(ns), "missions": rows}))
                .into_response(),
        )
    })
    .await
}

/// One mission of the resolved namespace (any authenticated caller).
async fn load(
    State(st): State<Arc<AppState>>,
    Path(name): Path<String>,
    Query(query): Query<Vec<(String, String)>>,
    req: Request,
) -> Response {
    if name.contains('/') {
        return no_route_for(&Method::GET, &format!("/missions/{name}"));
    }
    let h = Head::of(&req);
    blocking(st, move |st| {
        let identity = require_auth(st, &h)?;
        let ns = namespace_for(st, &h, &identity, param(&query, "ns").unwrap_or("live"))?;
        let path =
            obj::artifact_path(&st.cfg.data_dir, MISSIONS, &name, ns).map_err(server_error)?;
        let doc = obj::load(&path).map_err(server_error)?.ok_or_else(|| {
            err(
                StatusCode::NOT_FOUND,
                format!("no mission {}", py_repr(&name)),
            )
        })?;
        Ok(axum::Json(json!({"ok": true, "namespace": label(ns), "doc": doc})).into_response())
    })
    .await
}

/// Recoverable soft-delete in the resolved namespace: a live mission needs a director (BP-05); a sandbox one its
/// owner or a director. Audited with the namespace, even when nothing was deleted.
async fn remove(
    State(st): State<Arc<AppState>>,
    Path(name): Path<String>,
    Query(query): Query<Vec<(String, String)>>,
    req: Request,
) -> Response {
    if name.contains('/') {
        return no_route_for(&Method::DELETE, &format!("/missions/{name}"));
    }
    let h = Head::of(&req);
    blocking(st, move |st| {
        let identity = require_auth(st, &h)?;
        let ns = namespace_for(st, &h, &identity, param(&query, "ns").unwrap_or("live"))?;
        let director = role(st, &h, &identity)? == "director";
        let data = &st.cfg.data_dir;
        let ok = {
            let _lock = ArtifactLock::take(data, MISSIONS, &name, ns).map_err(server_error)?;
            let path = obj::artifact_path(data, MISSIONS, &name, ns).map_err(server_error)?;
            if !obj::deletion_allowed(obj::owner_of(&path).as_deref(), &identity, director, ns) {
                let reason = match ns {
                    Namespace::Live => "deleting a live (operational) mission requires a director",
                    Namespace::Sandbox(_) => {
                        "deleting another operator's mission requires a director"
                    }
                };
                return Err(err(StatusCode::FORBIDDEN, reason));
            }
            obj::soft_delete_unlocked(data, MISSIONS, &name, ns, st.clock.now())
                .map_err(server_error)?
        };
        log(
            st,
            &h,
            &identity,
            "mission.delete",
            &format!("{name} ns={}", label(ns)),
        );
        Ok(axum::Json(json!({"ok": ok, "recoverable": true})).into_response())
    })
    .await
}

/// Promote a sandbox draft into live (operator and above): your own, or another's as a director; the live
/// destination is authorized as an overwrite (SR-01).
async fn publish(
    State(st): State<Arc<AppState>>,
    Path(name): Path<String>,
    Query(query): Query<Vec<(String, String)>>,
    req: Request,
) -> Response {
    if name.contains('/') {
        return no_route_for(&Method::POST, &format!("/missions/{name}/publish"));
    }
    let h = Head::of(&req);
    blocking(st, move |st| {
        let identity = require_role(st, &h, "operator")?;
        let director = role(st, &h, &identity)? == "director";
        let target = param(&query, "owner").filter(|o| !o.is_empty()).unwrap_or(&identity).to_owned();
        if target != identity && !director {
            return Err(err(
                StatusCode::FORBIDDEN,
                "publishing another operator's sandbox draft requires a director",
            ));
        }
        let data = &st.cfg.data_dir;
        let ok = {
            let _lock = ArtifactLock::take(data, MISSIONS, &name, Namespace::Live).map_err(server_error)?;
            let live = obj::artifact_path(data, MISSIONS, &name, Namespace::Live).map_err(server_error)?;
            if !obj::write_allowed(obj::owner_of(&live).as_deref(), &identity, director) {
                return Err(err(
                    StatusCode::FORBIDDEN,
                    format!(
                        "a live mission {} owned by another operator already exists; only its owner or a director \
                         may replace it",
                        py_repr(&name)
                    ),
                ));
            }
            obj::publish_unlocked(data, MISSIONS, &name, &target).map_err(server_error)?
        };
        if ok {
            log(st, &h, &identity, "mission.publish", &name);
        }
        Ok(axum::Json(json!({"ok": ok})).into_response())
    })
    .await
}

/// Restore the newest trashed copy (operator and above); live recovery needs a director, and an occupied
/// destination is a conflict, never an overwrite.
async fn restore(
    State(st): State<Arc<AppState>>,
    Path(name): Path<String>,
    Query(query): Query<Vec<(String, String)>>,
    req: Request,
) -> Response {
    if name.contains('/') {
        return no_route_for(&Method::POST, &format!("/missions/{name}/restore"));
    }
    let h = Head::of(&req);
    blocking(st, move |st| {
        let identity = require_role(st, &h, "operator")?;
        let ns = namespace_for(st, &h, &identity, param(&query, "ns").unwrap_or("live"))?;
        let director = role(st, &h, &identity)? == "director";
        let data = &st.cfg.data_dir;
        // the sandbox is always the caller's own (namespace_for), so only live needs a director
        if ns == Namespace::Live && !director {
            return Err(err(
                StatusCode::FORBIDDEN,
                "restoring a shared (live) artifact requires a director",
            ));
        }
        let ok = match obj::restore(data, MISSIONS, &name, ns).map_err(server_error)? {
            obj::Restored::Yes => true,
            obj::Restored::Nothing => false,
            obj::Restored::Occupied(e) => return Err(err(StatusCode::CONFLICT, e)),
        };
        if ok {
            log(st, &h, &identity, "mission.restore", &name);
        }
        Ok(axum::Json(json!({"ok": ok})).into_response())
    })
    .await
}

/// The live mission trash (director), so a purge can name a file.
async fn trash(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let h = Head::of(&req);
    blocking(st, move |st| {
        require_role(st, &h, "director")?;
        let dir =
            obj::trash_dir(&st.cfg.data_dir, MISSIONS, Namespace::Live).map_err(server_error)?;
        Ok(
            axum::Json(json!({"ok": true, "trash": obj::json_files(&dir).map_err(server_error)?}))
                .into_response(),
        )
    })
    .await
}

/// Permanently purge one trashed live mission (director), confined to `.trash` by its base name.
async fn purge(
    State(st): State<Arc<AppState>>,
    Path(filename): Path<String>,
    req: Request,
) -> Response {
    if filename.contains('/') {
        return no_route_for(
            &Method::DELETE,
            &format!("/admin/trash/missions/{filename}"),
        );
    }
    let h = Head::of(&req);
    blocking(st, move |st| {
        let identity = require_role(st, &h, "director")?;
        let dir =
            obj::trash_dir(&st.cfg.data_dir, MISSIONS, Namespace::Live).map_err(server_error)?;
        #[allow(clippy::case_sensitive_file_extension_comparisons)]
        // the Python's `endswith(".json")`
        let ok = filename.ends_with(".json") && dir.join(&filename).exists();
        if ok {
            std::fs::remove_file(dir.join(&filename)).map_err(|e| server_error(e.to_string()))?;
            log(st, &h, &identity, "mission.purge", &filename);
        }
        Ok(axum::Json(json!({"ok": ok})).into_response())
    })
    .await
}

/// The caller's own sandbox file of a per-owner kind.
fn own_path(
    st: &AppState,
    kind: &str,
    identity: &str,
    file: &str,
) -> Result<std::path::PathBuf, ApiError> {
    Ok(
        obj::ns_dir(&st.cfg.data_dir, kind, Namespace::Sandbox(Some(identity)))
            .map_err(server_error)?
            .join(file),
    )
}

/// The caller's own authoring draft, or null (any authenticated caller).
async fn draft_load(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let h = Head::of(&req);
    blocking(st, move |st| {
        let identity = require_auth(st, &h)?;
        let doc =
            obj::load(&own_path(st, "draft", &identity, "current.json")?).map_err(server_error)?;
        Ok(axum::Json(json!({"ok": true, "doc": doc})).into_response())
    })
    .await
}

fn quota(st: &AppState, identity: &str, what: &str) -> Result<(), ApiError> {
    if st.draft_allowed(identity) {
        Ok(())
    } else {
        Err(err(
            StatusCode::TOO_MANY_REQUESTS,
            format!("{what} quota exceeded; slow down"),
        ))
    }
}

/// Autosave the caller's draft to their own sandbox (rate-limited per identity; unknown fields refused).
async fn draft_save(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let (h, bytes) = split(req, st.settings.max_body).await;
    blocking(st, move |st| {
        let body = parse_body(&bytes?)?;
        let identity = require_auth(st, &h)?;
        let doc = body_dict(body.as_ref())?;
        quota(st, &identity, "draft autosave")?;
        if let Some(u) = obj::unknown_fields(&doc, &DRAFT_KEYS) {
            return Err(err(
                StatusCode::BAD_REQUEST,
                format!("unknown draft fields {u}"),
            ));
        }
        let path = own_path(st, "draft", &identity, "current.json")?;
        let meta = obj::owner_meta(&path, &identity, st.clock.now());
        let created_by = meta.0.clone();
        obj::write_doc(&path, &[], meta, &doc).map_err(server_error)?;
        log(st, &h, &identity, "draft.save", "sandbox");
        Ok(axum::Json(json!({"ok": true, "created_by": created_by})).into_response())
    })
    .await
}

/// The caller's own soil overlay (any authenticated caller).
async fn soils(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let h = Head::of(&req);
    blocking(st, move |st| {
        let identity = require_auth(st, &h)?;
        let dir = obj::ns_dir(&st.cfg.data_dir, "soil", Namespace::Sandbox(Some(&identity))).map_err(server_error)?;
        let mut rows = Vec::new();
        for f in obj::json_files(&dir).map_err(server_error)? {
            let Some(d) = std::fs::read_to_string(dir.join(&f)).ok().and_then(|t| serde_json::from_str::<Value>(&t).ok())
            else {
                continue;
            };
            let get = |k: &str, default: Value| d.get(k).cloned().unwrap_or(default);
            rows.push(json!({"name": get("name", json!(f.trim_end_matches(".json"))), "title": get("title", json!("")),
                             "provenance": get("provenance", json!("")), "confidence": get("confidence", json!("")),
                             "owner": get("created_by", json!("unknown"))}));
        }
        Ok(axum::Json(json!({"ok": true, "soils": rows})).into_response())
    })
    .await
}

/// Save an operator-authored soil to the caller's own overlay; one without provenance and confidence is refused
/// (no fabricated moduli).
async fn soil_save(
    State(st): State<Arc<AppState>>,
    Path(name): Path<String>,
    req: Request,
) -> Response {
    if name.contains('/') {
        return no_route_for(&Method::POST, &format!("/soil/{name}"));
    }
    let (h, bytes) = split(req, st.settings.max_body).await;
    blocking(st, move |st| {
        let body = parse_body(&bytes?)?;
        let identity = require_auth(st, &h)?;
        let profile = body_dict(body.as_ref())?;
        quota(st, &identity, "soil-save")?;
        if let Some(u) = obj::unknown_fields(&profile, &SOIL_KEYS) {
            return Err(err(
                StatusCode::BAD_REQUEST,
                format!("unknown soil fields {u}"),
            ));
        }
        let missing: Vec<String> = ["provenance", "confidence"]
            .iter()
            .filter(|k| {
                profile
                    .get(**k)
                    .map_or_else(String::new, validate::py_str)
                    .trim()
                    .is_empty()
            })
            .map(|k| py_repr(k))
            .collect();
        if !missing.is_empty() {
            return Err(err(
                StatusCode::BAD_REQUEST,
                format!(
                    "a user soil must carry [{}] (no fabricated moduli -- cite a source)",
                    missing.join(", ")
                ),
            ));
        }
        let slug = obj::slug(&name);
        let path = own_path(st, "soil", &identity, &format!("{slug}.json"))?;
        let meta = obj::owner_meta(&path, &identity, st.clock.now());
        let created_by = meta.0.clone();
        obj::write_doc(
            &path,
            &[("name", json!(slug)), ("title", json!(name))],
            meta,
            &profile,
        )
        .map_err(server_error)?;
        log(st, &h, &identity, "soil.save", &slug);
        Ok(axum::Json(json!({"ok": true, "name": slug, "created_by": created_by})).into_response())
    })
    .await
}

/// The mission, draft and soil routes.
pub fn routes() -> Router<Arc<AppState>> {
    Router::new()
        .route("/missions", get(list))
        .route("/missions/{name}", get(load).post(save).delete(remove))
        .route("/missions/{name}/publish", post(publish))
        .route("/missions/{name}/restore", post(restore))
        .route("/admin/trash/missions", get(trash))
        .route("/admin/trash/missions/{filename}", delete(purge))
        .route("/draft", get(draft_load).put(draft_save))
        .route("/soils", get(soils))
        .route("/soil/{name}", post(soil_save))
}
