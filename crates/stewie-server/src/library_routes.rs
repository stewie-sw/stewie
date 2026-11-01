//! The asset library (RW-55b10; Python `routers.library` over `server.asset_library`): browse, search, inspect and
//! export the durable assets (live missions, shared structure templates, reports, per-site Terrain Memory, the
//! observed-twin journals and the DEM bundles) as a public manifest, and recover a soft-deleted mission or template
//! as a director. Private per-owner scratch (drafts, runs, soils) is never listed.

use std::path::Path;
use std::sync::Arc;

use axum::Router;
use axum::extract::{Path as UrlPath, Query, Request, State};
use axum::http::{HeaderValue, Method, StatusCode, header};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use serde_json::{Map, Value, json};

use crate::admin::require_director;
use crate::app::{ApiError, AppState, Head, blocking, err, log, no_route_for};
use crate::objects::{self as obj, Namespace};
use crate::operators::py_repr;
use crate::validate::{self, Field, Kind, Model};

/// The asset types, in the Python's order.
const ASSET_TYPES: [&str; 6] = ["mission", "structure", "report", "site", "twin", "dem"];

fn server_error(e: impl Into<String>) -> ApiError {
    err(StatusCode::INTERNAL_SERVER_ERROR, e)
}

/// Python `os.path.getsize`, `0` on error.
fn size(path: &Path) -> u64 {
    std::fs::metadata(path).map_or(0, |m| m.len())
}

/// Python `os.walk` file sizes summed (directory links not followed).
fn dir_size(path: &Path) -> u64 {
    let Ok(rd) = std::fs::read_dir(path) else {
        return 0;
    };
    rd.filter_map(Result::ok)
        .map(|e| {
            if e.file_type().is_ok_and(|t| t.is_dir()) {
                dir_size(&e.path())
            } else {
                size(&e.path())
            }
        })
        .sum()
}

/// Python `os.path.getmtime`: seconds plus nanoseconds as one float.
fn mtime(path: &Path) -> Option<f64> {
    use std::os::unix::fs::MetadataExt as _;
    #[allow(clippy::cast_precision_loss)]
    std::fs::metadata(path)
        .ok()
        .map(|m| m.mtime() as f64 + m.mtime_nsec() as f64 * 1e-9)
}

/// The sorted names of a directory's entries, or nothing when it is absent.
fn listing(dir: &Path) -> Vec<String> {
    let mut out: Vec<String> = std::fs::read_dir(dir)
        .map(|rd| {
            rd.filter_map(Result::ok)
                .filter_map(|e| e.file_name().to_str().map(str::to_owned))
                .collect()
        })
        .unwrap_or_default();
    out.sort();
    out
}

fn manifest(atype: &str, id: &Value, rest: Value) -> Value {
    let key = validate::py_str(id);
    let mut m = json!({"type": atype, "id": id,
                       "inspect_href": format!("/library/{atype}/{key}"),
                       "export_href": format!("/library/{atype}/{key}/export")});
    if let (Some(m), Value::Object(r)) = (m.as_object_mut(), rest) {
        m.extend(r);
    }
    m
}

/// Python `v or fallback`.
fn truthy_or(v: Option<&Value>, fallback: &Value) -> Value {
    v.filter(|x| obj::truthy(x)).unwrap_or(fallback).clone()
}

fn mission_assets(st: &AppState) -> Result<Vec<Value>, String> {
    let data = &st.cfg.data_dir;
    let d0 = obj::ns_dir(data, "missions", Namespace::Live)?;
    Ok(obj::list_missions(data, Namespace::Live)?
        .into_iter()
        .map(|m| {
            let name = m.get("name").cloned().unwrap_or(json!(""));
            let owner = validate::py_str(&m["owner"]);
            manifest(
                "mission",
                &name,
                json!({
                    "title": truthy_or(m.get("title"), &name), "created": m["created_at"],
                    "provenance": format!("authored by {owner} (live namespace)"),
                    "size_bytes": size(&d0.join(format!("{}.json", validate::py_str(&name)))),
                    "namespace": "live", "recoverable": true,
                    "detail": {"body": m["body"], "n_orders": m["n_orders"], "owner": m["owner"]},
                    "payload_href": format!("/missions/{}", validate::py_str(&name)),
                }),
            )
        })
        .collect())
}

fn structure_assets(st: &AppState) -> Result<Vec<Value>, String> {
    let data = &st.cfg.data_dir;
    let d0 = obj::ns_dir(data, "structures", Namespace::Live)?;
    Ok(obj::list_structures(data)?
        .into_iter()
        .map(|s| {
            let name = s["name"].clone();
            let owner = validate::py_str(&s["owner"]);
            manifest(
                "structure",
                &name,
                json!({
                    "title": truthy_or(s.get("title"), &name), "created": s["created_at"],
                    "provenance": format!("authored by {owner} (shared template)"),
                    "size_bytes": size(&d0.join(format!("{}.json", validate::py_str(&name)))),
                    "namespace": "live", "recoverable": true,
                    "detail": {"n_entries": s["n_entries"], "owner": s["owner"]},
                }),
            )
        })
        .collect())
}

/// One report stem's formats (extension to file name), newest mtime and total size.
type Report = (Map<String, Value>, Option<f64>, u64);

/// Reports grouped by stem: one asset with the formats (pdf, md) it has.
fn report_assets(st: &AppState) -> Vec<Value> {
    let rdir = st.cfg.data_dir.join("reports");
    let mut stems: std::collections::BTreeMap<String, Report> = std::collections::BTreeMap::new();
    for f in listing(&rdir) {
        let p = Path::new(&f);
        let (Some(stem), Some(ext)) = (
            p.file_stem().and_then(|s| s.to_str()),
            p.extension().and_then(|s| s.to_str()),
        ) else {
            continue;
        };
        if ext != "pdf" && ext != "md" {
            continue;
        }
        let path = rdir.join(&f);
        let rec = stems
            .entry(stem.to_owned())
            .or_insert_with(|| (Map::new(), None, 0));
        rec.0.insert(ext.to_owned(), json!(f));
        rec.2 += size(&path);
        if let Some(mt) = mtime(&path) {
            rec.1 = Some(rec.1.map_or(mt, |c| c.max(mt)));
        }
    }
    stems
        .into_iter()
        .map(|(stem, (fmts, created, bytes))| {
            let payload = fmts.get("pdf").or_else(|| fmts.get("md")).and_then(Value::as_str).unwrap_or(&stem).to_owned();
            manifest("report", &json!(stem), json!({
                "title": stem.replace('_', " "), "created": created,
                "provenance": "mission-control report (derived from a plan run)", "size_bytes": bytes,
                "namespace": "derived", "recoverable": false, "detail": {"formats": fmts.keys().collect::<Vec<_>>()},
                "payload_href": format!("/reports/{payload}"),
            }))
        })
        .collect()
}

/// Per-site Terrain Memory: a torn or legacy file still lists, with no summary.
fn site_assets(st: &AppState) -> Vec<Value> {
    let data = &st.cfg.data_dir;
    let tdir = data.join("terrain_memory");
    listing(&tdir)
        .into_iter()
        .filter_map(|f| f.strip_suffix(".npz").map(str::to_owned))
        .map(|site| {
            let path = tdir.join(format!("{site}.npz"));
            let detail = match stewie_twin::terrain_memory::load_site(data, &site) {
                Ok(Some(mem)) => {
                    let s = mem.summary();
                    json!({"version": s.version, "cells_changed": s.cells_changed, "net_volume_m3": s.net_volume_m3,
                           "chain_valid": mem.verify_chain(), "n_missions": s.missions.len()})
                }
                _ => json!({}),
            };
            let n = detail.get("n_missions").cloned().unwrap_or(json!(0));
            manifest("site", &json!(site), json!({
                "title": format!("{site} terrain memory"), "created": mtime(&path),
                "provenance": format!("terrain-memory world model (hash-chained, {n} recorded missions)"),
                "size_bytes": size(&path), "namespace": "world", "recoverable": false, "detail": detail,
            }))
        })
        .collect()
}

/// The observed-twin journals with their event counts; a journal that is not UTF-8 fails the type, as the Python's
/// decode error does.
fn twin_assets(st: &AppState) -> Result<Vec<Value>, String> {
    let tdir = st.cfg.data_dir.join("twin");
    listing(&tdir)
        .into_iter()
        .filter_map(|f| f.strip_suffix(".journal").map(str::to_owned))
        .map(|site| {
            let path = tdir.join(format!("{site}.journal"));
            let n_events = match std::fs::read(&path) {
                Ok(b) => String::from_utf8(b)
                    .map_err(|e| format!("{}: {e}", path.display()))?
                    .lines()
                    .filter(|l| !l.trim().is_empty())
                    .count(),
                Err(_) => 0,
            };
            Ok(manifest("twin", &json!(site), json!({
                "title": format!("{site} observed-twin journal"), "created": mtime(&path),
                "provenance": format!("observed-terrain event journal (hash-chained, {n_events} events)"),
                "size_bytes": size(&path), "namespace": "world", "recoverable": true,
                "detail": {"n_events": n_events},
            })))
        })
        .collect()
}

/// The DEM bundles with a `metadata.json`, their provenance its producer.
fn dem_assets(st: &AppState) -> Vec<Value> {
    let base = st.terrain.dem_root();
    listing(&base)
        .into_iter()
        .filter_map(|name| {
            let bundle = base.join(&name);
            let meta_path = bundle.join("metadata.json");
            if !(bundle.is_dir() && meta_path.is_file()) {
                return None;
            }
            let meta: Value = std::fs::read_to_string(&meta_path)
                .ok()
                .and_then(|t| serde_json::from_str(&t).ok())
                .unwrap_or_else(|| json!({}));
            let grid = meta.get("grid").filter(|g| obj::truthy(g));
            Some(manifest(
                "dem",
                &json!(name),
                json!({
                    "title": name.replace('_', " "), "created": mtime(&meta_path),
                    "provenance": truthy_or(meta.get("producer"), &json!("real LOLA DEM bundle")),
                    "size_bytes": dir_size(&bundle), "namespace": "prior", "recoverable": false,
                    "detail": grid.map_or_else(|| json!({}), |g| json!({"grid": g})),
                }),
            ))
        })
        .collect()
}

/// One type's assets; an error is the Python's exception out of the enumerator.
fn enumerate(st: &AppState, atype: &str) -> Result<Vec<Value>, String> {
    match atype {
        "mission" => mission_assets(st),
        "structure" => structure_assets(st),
        "report" => Ok(report_assets(st)),
        "site" => Ok(site_assets(st)),
        "twin" => twin_assets(st),
        "dem" => Ok(dem_assets(st)),
        _ => Ok(Vec::new()),
    }
}

/// The Python's case-insensitive search over type, id, title and provenance.
fn matches(rec: &Value, q: &str) -> bool {
    let hay = ["type", "id", "title", "provenance"]
        .iter()
        .map(|k| rec.get(*k).map_or_else(String::new, validate::py_str))
        .collect::<Vec<_>>()
        .join(" ")
        .to_lowercase();
    hay.contains(&q.to_lowercase())
}

/// The soft-deleted live missions and templates a recover can restore.
fn trash_assets(st: &AppState) -> Vec<Value> {
    let mut out = Vec::new();
    for (kind, atype) in [("missions", "mission"), ("structures", "structure")] {
        let files = obj::trash_dir(&st.cfg.data_dir, kind, Namespace::Live)
            .and_then(|d| obj::json_files(&d))
            .unwrap_or_default();
        for f in files {
            let slug = f.split('.').next().unwrap_or("").to_owned();
            out.push(json!({"type": atype, "id": slug, "trash_file": f, "deleted": true, "recoverable": true,
                            "provenance": format!("soft-deleted {atype} (recoverable from .trash)")}));
        }
    }
    out
}

const LIST_QUERY: Model = Model {
    fields: &[Field("include_trash", Kind::Bool { default: false })],
    forbid_extra: false,
};

fn param<'a>(q: &'a [(String, String)], key: &str) -> Option<&'a str> {
    q.iter()
        .rev()
        .find(|(k, _)| k == key)
        .map(|(_, v)| v.as_str())
}

/// Browse the durable assets, with an optional search `q`, type filter `type` and the trash (public).
async fn list(
    State(st): State<Arc<AppState>>,
    Query(query): Query<Vec<(String, String)>>,
) -> Response {
    blocking(st, move |st| {
        let raw = crate::spec_routes::query(&query, LIST_QUERY)?;
        let include_trash = raw
            .get("include_trash")
            .and_then(validate::as_bool)
            .unwrap_or(false);
        let q = param(&query, "q").filter(|q| !q.is_empty());
        let types: Vec<&str> = match param(&query, "type") {
            Some(t) if ASSET_TYPES.contains(&t) => vec![t],
            _ => ASSET_TYPES.to_vec(),
        };
        // one broken store must not blank the whole library
        let mut assets: Vec<Value> = types
            .iter()
            .filter_map(|t| enumerate(st, t).ok())
            .flatten()
            .collect();
        if let Some(q) = q {
            assets.retain(|r| matches(r, q));
        }
        assets.sort_by_key(|r| (validate::py_str(&r["type"]), validate::py_str(&r["id"])));
        let mut counts = Map::new();
        for r in &assets {
            let t = validate::py_str(&r["type"]);
            let n = counts.get(&t).and_then(Value::as_u64).unwrap_or(0) + 1;
            counts.insert(t, json!(n));
        }
        let mut body = json!({"ok": true, "total": assets.len(), "assets": assets, "counts": counts,
                              "types": ASSET_TYPES});
        if include_trash {
            let mut trash = trash_assets(st);
            if let Some(q) = q {
                let q = q.to_lowercase();
                trash.retain(|t| {
                    format!(
                        "{} {}",
                        validate::py_str(&t["id"]),
                        validate::py_str(&t["type"])
                    )
                    .to_lowercase()
                    .contains(&q)
                });
            }
            body["trash"] = json!(trash);
        }
        Ok(axum::Json(body).into_response())
    })
    .await
}

/// One asset by type and id.
fn find(st: &AppState, atype: &str, aid: &str) -> Result<Value, ApiError> {
    let not_found = || {
        err(
            StatusCode::NOT_FOUND,
            format!("no {atype} asset {}", py_repr(aid)),
        )
    };
    if !ASSET_TYPES.contains(&atype) {
        return Err(not_found());
    }
    enumerate(st, atype)
        .map_err(server_error)?
        .into_iter()
        .find(|r| validate::py_str(&r["id"]) == aid)
        .ok_or_else(not_found)
}

/// Inspect one asset's manifest record (public).
async fn inspect(
    State(st): State<Arc<AppState>>,
    UrlPath((atype, aid)): UrlPath<(String, String)>,
) -> Response {
    if atype.contains('/') || aid.contains('/') {
        return no_route_for(&Method::GET, &format!("/library/{atype}/{aid}"));
    }
    blocking(st, move |st| {
        Ok(axum::Json(json!({"ok": true, "asset": find(st, &atype, &aid)?})).into_response())
    })
    .await
}

/// The asset's descriptor as a JSON attachment, stamped `exported_at` (public); the Python's
/// `json.dumps(rec, indent=2, sort_keys=True)`.
async fn export(
    State(st): State<Arc<AppState>>,
    UrlPath((atype, aid)): UrlPath<(String, String)>,
) -> Response {
    if atype.contains('/') || aid.contains('/') {
        return no_route_for(&Method::GET, &format!("/library/{atype}/{aid}/export"));
    }
    blocking(st, move |st| {
        let mut rec = find(st, &atype, &aid)?;
        rec["schema"] = json!("stewie.asset_library.v1");
        rec["exported_at"] = json!(st.clock.now());
        let text =
            stewie_twin::pyjson::dumps_indent(&rec, 2).map_err(|e| server_error(e.to_string()))?;
        let fname = format!("stewie_{atype}_{aid}.json").replace('/', "_");
        let mut r = text.into_response();
        let h = r.headers_mut();
        h.insert(
            header::CONTENT_TYPE,
            HeaderValue::from_static("application/json"),
        );
        if let Ok(v) = HeaderValue::from_str(&format!("attachment; filename=\"{fname}\"")) {
            h.insert(header::CONTENT_DISPOSITION, v);
        }
        Ok(r)
    })
    .await
}

/// Recover a soft-deleted mission or template into live (director), never over an existing artifact.
async fn recover(
    State(st): State<Arc<AppState>>,
    UrlPath((atype, aid)): UrlPath<(String, String)>,
    req: Request,
) -> Response {
    if atype.contains('/') || aid.contains('/') {
        return no_route_for(&Method::POST, &format!("/library/{atype}/{aid}/recover"));
    }
    let h = Head::of(&req);
    blocking(st, move |st| {
        let identity = require_director(st, &h)?;
        let kind = match atype.as_str() {
            "mission" => "missions",
            "structure" => "structures",
            _ => {
                return Ok(axum::Json(json!({"ok": false, "restored": false, "type": atype, "id": aid,
                    "reason": format!("{atype} is not trash-recoverable (a report is regenerated; a twin cold-restores)")}))
                .into_response());
            }
        };
        let restored = match obj::restore(&st.cfg.data_dir, kind, &aid, Namespace::Live).map_err(server_error)? {
            obj::Restored::Yes => true,
            obj::Restored::Nothing => false,
            obj::Restored::Occupied(e) => {
                return Ok((StatusCode::CONFLICT, axum::Json(json!({"ok": false, "restored": false, "error": e})))
                    .into_response());
            }
        };
        if restored {
            log(st, &h, &identity, "asset.recover", &format!("{atype}:{aid}"));
        }
        Ok(axum::Json(json!({"ok": restored, "restored": restored, "type": atype, "id": aid,
                             "reason": if restored { Value::Null } else { json!("no trashed copy to restore") }}))
        .into_response())
    })
    .await
}

/// The library routes.
pub fn routes() -> Router<Arc<AppState>> {
    Router::new()
        .route("/library", get(list))
        .route("/library/{atype}/{aid}", get(inspect))
        .route("/library/{atype}/{aid}/export", get(export))
        .route("/library/{atype}/{aid}/recover", post(recover))
}
