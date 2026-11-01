//! Custom structure templates (RW-55b8; Python `routers.structures` over `server.objects`): save (operator and
//! above, owner or director to overwrite), list, expand at a point into queue-ready orders, and recoverable delete
//! (a live template needs a director).

use std::sync::Arc;

use axum::Router;
use axum::extract::{Path, Query, Request, State};
use axum::http::{Method, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::get;
use serde_json::{Map, Value, json};

use crate::admin::require_role;
use crate::app::{
    ApiError, AppState, Head, blocking, err, log, no_route_for, parse_body, require_auth, split,
};
use crate::objects::{self as obj, ArtifactLock, Namespace};
use crate::operators::py_repr;
use crate::validate::{self, Field, Kind, Model, Ordered};

const KIND: &str = "structures";
const ENTRY_KEYS: [&str; 5] = ["depth_m", "dx", "dy", "footprint_m2", "kind"];

fn server_error(e: impl Into<String>) -> ApiError {
    err(StatusCode::INTERNAL_SERVER_ERROR, e)
}

fn is_director(st: &AppState, h: &Head, identity: &str) -> Result<bool, ApiError> {
    Ok(st
        .auth(Some(&h.cid))
        .role_of(identity)
        .map_err(server_error)?
        == "director")
}

/// The Python's entry checks: a non-empty `kind_list` of at most 64 entries, each carrying every entry key and a
/// `kind` of cut, fill or goto. `ordered` is the same body in the client's key order, for the reprs.
fn check_entries(doc: &Map<String, Value>, ordered: &Ordered) -> Result<Vec<Value>, ApiError> {
    let bad = |m: String| err(StatusCode::BAD_REQUEST, m);
    let entries = match doc.get("kind_list") {
        Some(Value::Array(a)) if !a.is_empty() && a.len() <= 64 => a.clone(),
        _ => {
            return Err(bad(
                "kind_list must be a non-empty list (max 64 entries)".to_owned()
            ));
        }
    };
    let ordered_entries = match ordered.get("kind_list") {
        Some(Ordered::Array(a)) => a.clone(),
        _ => Vec::new(),
    };
    for (i, e) in entries.iter().enumerate() {
        // `set(e)`: an object's keys, a flat list's items; anything else the Python cannot hash
        let present: Vec<String> = match e {
            Value::Object(m) => m.keys().cloned().collect(),
            // a string's characters: never a whole key name
            Value::String(_) => Vec::new(),
            Value::Array(a) if a.iter().all(|x| !x.is_array() && !x.is_object()) => a
                .iter()
                .filter_map(|x| x.as_str().map(str::to_owned))
                .collect(),
            _ => {
                return Err(server_error(format!(
                    "entry {i} is not iterable as the Python reads it"
                )));
            }
        };
        let missing: Vec<&str> = ENTRY_KEYS
            .iter()
            .copied()
            .filter(|k| !present.iter().any(|p| p == k))
            .collect();
        if !missing.is_empty() {
            let list = missing
                .iter()
                .map(|k| py_repr(k))
                .collect::<Vec<_>>()
                .join(", ");
            return Err(bad(format!("entry {i} missing [{list}]")));
        }
        let Some(kind) = e.get("kind") else {
            return Err(server_error(format!("entry {i} is not an object")));
        };
        if !["cut", "fill", "goto"].iter().any(|k| kind == *k) {
            let repr = match ordered_entries.get(i).and_then(|o| o.get("kind")) {
                Some(o) => o.py_repr(),
                None => validate::py_str(kind),
            };
            return Err(bad(format!("entry {i} kind {repr} not in cut/fill/goto")));
        }
    }
    Ok(entries)
}

/// Save a custom template into the shared live library (operator and above; overwriting needs its owner or a
/// director). The file is the Python's `json.dumps(..., indent=1, sort_keys=True)`.
async fn save(State(st): State<Arc<AppState>>, Path(name): Path<String>, req: Request) -> Response {
    if name.contains('/') {
        return no_route_for(&Method::POST, &format!("/structures/custom/{name}"));
    }
    let (h, bytes) = split(req, st.settings.max_body).await;
    blocking(st, move |st| {
        let bytes = bytes?;
        let body = parse_body(&bytes)?;
        let identity = require_role(st, &h, "operator")?;
        let doc = validate::dict(body.as_ref()).map_err(|e| err(StatusCode::BAD_REQUEST, e))?;
        let ordered: Ordered = serde_json::from_slice(&bytes).map_err(|e| err(StatusCode::BAD_REQUEST, e.to_string()))?;
        let director = is_director(st, &h, &identity)?;
        let data = &st.cfg.data_dir;
        let _lock = ArtifactLock::take(data, KIND, &name, Namespace::Live).map_err(server_error)?;
        let path = obj::artifact_path(data, KIND, &name, Namespace::Live).map_err(server_error)?;
        if !obj::write_allowed(obj::owner_of(&path).as_deref(), &identity, director) {
            return Err(err(
                StatusCode::FORBIDDEN,
                format!(
                    "structure {} belongs to another operator; only its owner or a director may overwrite it",
                    py_repr(&name)
                ),
            ));
        }
        let entries = check_entries(doc, &ordered)?;
        let note = match ordered.get("note") {
            None => String::new(),
            Some(Ordered::String(s)) => s.clone(),
            Some(o) => o.py_repr(),
        };
        let slug = obj::slug(&name);
        let (created_by, created_at) = obj::owner_meta(&path, &identity, st.clock.now());
        let file = json!({"name": slug, "title": name, "kind_list": entries, "note": note,
                          "created_by": created_by, "created_at": created_at});
        let text = stewie_twin::pyjson::dumps_indent(&file, 1).map_err(|e| err(StatusCode::BAD_REQUEST, e.to_string()))?;
        crate::atomic_write(&path, text.as_bytes()).map_err(server_error)?;
        log(st, &h, &identity, "structure.save", &slug);
        Ok(axum::Json(json!({"ok": true, "name": slug, "created_by": created_by})).into_response())
    })
    .await
}

/// The live templates (any authenticated caller).
async fn list(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let h = Head::of(&req);
    blocking(st, move |st| {
        require_auth(st, &h)?;
        let rows = obj::list_structures(&st.cfg.data_dir).map_err(server_error)?;
        Ok(axum::Json(json!({"ok": true, "structures": rows})).into_response())
    })
    .await
}

const EXPAND_QUERY: Model = Model {
    fields: &[
        Field(
            "x",
            Kind::Float {
                gt: None,
                ge: None,
                le: None,
                default: None,
            },
        ),
        Field(
            "y",
            Kind::Float {
                gt: None,
                ge: None,
                le: None,
                default: None,
            },
        ),
    ],
    forbid_extra: false,
};

/// Python `float()` of a stored entry value.
fn py_float(v: &Value) -> Option<f64> {
    match v {
        Value::Number(n) => n.as_f64(),
        Value::Bool(b) => Some(f64::from(u8::from(*b))),
        Value::String(s) => s.trim().replace('_', "").parse().ok(),
        _ => None,
    }
}

/// A template expanded at `(x, y)` into queue-ready orders (any authenticated caller).
async fn expand(
    State(st): State<Arc<AppState>>,
    Path(name): Path<String>,
    Query(query): Query<Vec<(String, String)>>,
    req: Request,
) -> Response {
    if name.contains('/') {
        return no_route_for(&Method::GET, &format!("/structures/custom/{name}/expand"));
    }
    let h = Head::of(&req);
    blocking(st, move |st| {
        require_auth(st, &h)?;
        let raw = crate::spec_routes::query(&query, EXPAND_QUERY)?;
        let (x, y) = (
            validate::as_float(&raw["x"]).map_err(server_error)?,
            validate::as_float(&raw["y"]).map_err(server_error)?,
        );
        let path = obj::artifact_path(&st.cfg.data_dir, KIND, &name, Namespace::Live)
            .map_err(server_error)?;
        if !path.exists() {
            return Err(err(
                StatusCode::NOT_FOUND,
                format!("no structure {}", py_repr(&name)),
            ));
        }
        let template: Value = serde_json::from_str(
            &std::fs::read_to_string(&path).map_err(|e| server_error(e.to_string()))?,
        )
        .map_err(|e| server_error(e.to_string()))?;
        let stem = validate::py_str(&template["name"]);
        let entries = template["kind_list"]
            .as_array()
            .ok_or_else(|| server_error("a template without a kind_list"))?;
        let num = |e: &Value, k: &str| {
            py_float(&e[k]).ok_or_else(|| server_error(format!("a template entry's {k}")))
        };
        let mut orders = Vec::new();
        for (i, entry) in entries.iter().enumerate() {
            let kind = &entry["kind"];
            let mut order = json!({"action": format!("{stem}-{}", i + 1), "kind": kind,
                                   "x": x + num(entry, "dx")?, "y": y + num(entry, "dy")?});
            if kind != "goto" {
                order["footprint_m2"] = json!(num(entry, "footprint_m2")?);
                order["depth_m"] = json!(num(entry, "depth_m")?);
            }
            orders.push(order);
        }
        if orders.iter().any(|o| o["x"].is_null() || o["y"].is_null()) {
            return Err(server_error("a non-finite expanded position"));
        }
        Ok(axum::Json(json!({"ok": true, "orders": orders})).into_response())
    })
    .await
}

/// Recoverable soft-delete (any authenticated caller; a live template needs a director, AG-06).
async fn delete(
    State(st): State<Arc<AppState>>,
    Path(name): Path<String>,
    req: Request,
) -> Response {
    if name.contains('/') {
        return no_route_for(&Method::DELETE, &format!("/structures/custom/{name}"));
    }
    let h = Head::of(&req);
    blocking(st, move |st| {
        let identity = require_auth(st, &h)?;
        let director = is_director(st, &h, &identity)?;
        let data = &st.cfg.data_dir;
        let ok = {
            let _lock =
                ArtifactLock::take(data, KIND, &name, Namespace::Live).map_err(server_error)?;
            let path =
                obj::artifact_path(data, KIND, &name, Namespace::Live).map_err(server_error)?;
            if !obj::deletion_allowed(
                obj::owner_of(&path).as_deref(),
                &identity,
                director,
                Namespace::Live,
            ) {
                return Err(err(
                    StatusCode::FORBIDDEN,
                    "deleting a shared (live) structure template requires a director",
                ));
            }
            obj::soft_delete_unlocked(data, KIND, &name, Namespace::Live, st.clock.now())
                .map_err(server_error)?
        };
        log(
            st,
            &h,
            &identity,
            "structure.delete",
            &format!("{name} ns=live"),
        );
        Ok(axum::Json(json!({"ok": ok, "recoverable": true})).into_response())
    })
    .await
}

/// The structure routes.
pub fn routes() -> Router<Arc<AppState>> {
    Router::new()
        .route("/structures/custom", get(list))
        .route(
            "/structures/custom/{name}",
            axum::routing::post(save).delete(delete),
        )
        .route("/structures/custom/{name}/expand", get(expand))
}
