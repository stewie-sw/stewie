//! The stream service's HTTP surface (Python `stewie.stream.app`, its `FastAPI` shapes: errors are `{"detail": ...}`):
//! the setup and stream pages, the vendored ES module, the readiness probe, the real-site dropdown and preview, and
//! the saved command bags and mission routes. Every route but the exempt two passes the token gate; the page entries
//! (`/`, `/stream`) also count against the per-client connection window.

use std::net::SocketAddr;
use std::path::{Component, Path, PathBuf};
use std::sync::Arc;
use std::time::Instant;

use axum::Router;
use axum::extract::{ConnectInfo, Path as UrlPath, Query, Request, State};
use axum::http::{HeaderValue, StatusCode, header};
use axum::middleware::{self, Next};
use axum::response::{IntoResponse, Response};
use axum::routing::get;
use serde_json::{Value, json};

use crate::previews::{self, PreviewError};
use crate::py;
use crate::security::{self, Env, Limiter, Sessions};

/// The service's directories and environment.
#[derive(Clone)]
pub struct Config {
    /// `stewie/stream/static` (the pages and `vendor/`).
    pub static_dir: PathBuf,
    /// `samples/lunar_dem`.
    pub samples_dir: PathBuf,
    /// Saved command bags (`out/viz2_bags`).
    pub bags_dir: PathBuf,
    /// Saved mission routes (`out/viz2_routes`).
    pub routes_dir: PathBuf,
    pub env: Env,
}

impl std::fmt::Debug for Config {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Config")
            .field("static_dir", &self.static_dir)
            .field("samples_dir", &self.samples_dir)
            .field("bags_dir", &self.bags_dir)
            .field("routes_dir", &self.routes_dir)
            .finish_non_exhaustive()
    }
}

impl Config {
    /// The checkout's own layout (the Python's repo-relative paths) over `env`.
    #[must_use]
    pub fn for_checkout(repo: &Path, env: Env) -> Self {
        Self {
            static_dir: repo.join("stewie/stream/static"),
            samples_dir: repo.join("samples/lunar_dem"),
            bags_dir: repo.join("out/viz2_bags"),
            routes_dir: repo.join("out/viz2_routes"),
            env,
        }
    }
}

/// The service state: its configuration and the process-wide guards.
#[derive(Debug)]
pub struct Stream {
    pub cfg: Config,
    pub limiter: Limiter,
    pub sessions: Sessions,
}

impl Stream {
    /// A fresh service: no hits in the window, no live sessions.
    #[must_use]
    pub fn new(cfg: Config) -> Self {
        Self {
            cfg,
            limiter: Limiter::default(),
            sessions: Sessions::default(),
        }
    }
}

fn detail(status: StatusCode, msg: &str) -> Response {
    (status, axum::Json(json!({"detail": msg}))).into_response()
}

/// A file as Starlette's `FileResponse`: its media type, `text/*` with `charset=utf-8`.
fn file(path: &Path, media: &str) -> Response {
    match std::fs::read(path) {
        Ok(bytes) => {
            let ct = if media.starts_with("text/") {
                format!("{media}; charset=utf-8")
            } else {
                media.to_owned()
            };
            (
                [(
                    header::CONTENT_TYPE,
                    HeaderValue::from_str(&ct).unwrap_or(HeaderValue::from_static("text/plain")),
                )],
                bytes,
            )
                .into_response()
        }
        Err(_) => detail(StatusCode::NOT_FOUND, "Not Found"),
    }
}

/// The client of a request (see [`security::client_key`]).
fn client(req: &Request) -> String {
    let peer = req
        .extensions()
        .get::<ConnectInfo<SocketAddr>>()
        .map(|c| c.0.ip());
    security::client_key(peer, |h| {
        req.headers()
            .get(h)
            .and_then(|v| v.to_str().ok())
            .map(str::to_owned)
    })
}

/// The `token` query parameter, the last of repeats (Starlette's `query_params.get`).
fn query_token(uri: &axum::http::Uri) -> Option<String> {
    Query::<Vec<(String, String)>>::try_from_uri(uri)
        .ok()
        .and_then(|Query(q)| {
            q.into_iter()
                .rev()
                .find(|(k, _)| k == "token")
                .map(|(_, v)| v)
        })
}

/// The token gate and, on the page entries, the connection window.
async fn guard(State(st): State<Arc<Stream>>, req: Request, next: Next) -> Response {
    let path = req.uri().path().to_owned();
    if security::is_exempt(&path) {
        return next.run(req).await;
    }
    if !security::token_ok(&st.cfg.env, query_token(req.uri()).as_deref()) {
        return detail(
            StatusCode::UNAUTHORIZED,
            "unauthorized: missing or invalid stream token",
        );
    }
    if (path == "/" || path == "/stream")
        && !st.limiter.allow(
            &client(&req),
            security::max_conn_per_min(&st.cfg.env),
            Instant::now(),
        )
    {
        return detail(
            StatusCode::TOO_MANY_REQUESTS,
            "rate limited: too many connections, try again shortly",
        );
    }
    next.run(req).await
}

async fn index(State(st): State<Arc<Stream>>) -> Response {
    file(&st.cfg.static_dir.join("index.html"), "text/html")
}

async fn stream_view(State(st): State<Arc<Stream>>) -> Response {
    file(&st.cfg.static_dir.join("stream.html"), "text/html")
}

/// A vendored asset: a plain relative path under `vendor/` (no `..`, no root), as `StaticFiles` serves.
async fn vendor(State(st): State<Arc<Stream>>, UrlPath(rel): UrlPath<String>) -> Response {
    let rel = Path::new(&rel);
    if !rel.components().all(|c| matches!(c, Component::Normal(_))) {
        return detail(StatusCode::NOT_FOUND, "Not Found");
    }
    let p = st.cfg.static_dir.join("vendor").join(rel);
    let media = match p.extension().and_then(|e| e.to_str()) {
        Some("js" | "mjs") => "text/javascript",
        Some("css") => "text/css",
        Some("json") => "application/json",
        Some("wasm") => "application/wasm",
        Some("png") => "image/png",
        _ => "application/octet-stream",
    };
    if p.is_file() {
        file(&p, media)
    } else {
        detail(StatusCode::NOT_FOUND, "Not Found")
    }
}

async fn healthz() -> Response {
    // exempt from the token gate: liveness only, no paths
    axum::Json(json!({"ok": true, "service": "viz2-stream"})).into_response()
}

async fn bundles(State(st): State<Arc<Stream>>) -> Response {
    match previews::list_real_bundles(&st.cfg.samples_dir) {
        Ok(rows) => axum::Json(json!({"bundles": rows, "default": crate::protocol::DEFAULT_SITE}))
            .into_response(),
        Err(e) => detail(StatusCode::INTERNAL_SERVER_ERROR, &e),
    }
}

/// The saved `*.json` files of `dir`, sorted, each parsed (unreadable or non-JSON files skipped).
fn saved(dir: &Path) -> Vec<(String, Value)> {
    let mut files: Vec<PathBuf> = std::fs::read_dir(dir)
        .map(|rd| {
            rd.filter_map(Result::ok)
                .map(|e| e.path())
                .filter(|p| {
                    p.extension().is_some_and(|x| x == "json")
                        && !p
                            .file_name()
                            .is_some_and(|n| n.to_string_lossy().starts_with('.'))
                })
                .collect()
        })
        .unwrap_or_default();
    files.sort_by(|a, b| {
        a.as_os_str()
            .as_encoded_bytes()
            .cmp(b.as_os_str().as_encoded_bytes())
    });
    files
        .into_iter()
        .filter_map(|p| {
            let v: Value = serde_json::from_slice(&std::fs::read(&p).ok()?).ok()?;
            Some((p.file_stem()?.to_string_lossy().into_owned(), v))
        })
        .collect()
}

/// Saved command bags: name, duration, command count and the recorded site and mode. A malformed bag is skipped
/// (the Python answered 500 for the whole list on some, D-R184).
async fn bags(State(st): State<Arc<Stream>>) -> Response {
    let rows: Vec<Value> = saved(&st.cfg.bags_dir)
        .into_iter()
        .filter_map(|(name, b)| {
            let b = b.as_object()?;
            let cfg = b.get("config").filter(|c| py::truthy(c)).cloned().unwrap_or_else(|| json!({}));
            let cfg = cfg.as_object()?;
            let dur = b.get("duration_s").map_or(Some(0.0), py::float).filter(|d| d.is_finite())?;
            let n = b.get("n_commands").map_or(Some(0), py::int)?;
            Some(json!({"name": name, "duration_s": stewie_twin::numpy::round(dur, 1), "n_commands": n,
                        "site": cfg.get("site").cloned().unwrap_or(Value::Null),
                        "mode": cfg.get("mode").cloned().unwrap_or(Value::Null)}))
        })
        .collect();
    axum::Json(json!({"bags": rows})).into_response()
}

/// Saved mission routes (GeoJSON): name, site, mode, goal count and planar route length; malformed ones skipped.
async fn routes_list(State(st): State<Arc<Stream>>) -> Response {
    let rows: Vec<Value> = saved(&st.cfg.routes_dir)
        .into_iter()
        .filter_map(|(name, r)| {
            let pr = r.as_object()?.get("properties").filter(|p| py::truthy(p)).cloned().unwrap_or_else(|| json!({}));
            let pr = pr.as_object()?;
            let n = pr.get("n_goals").map_or(Some(0), py::int)?;
            let len = pr.get("route_m").map_or(Some(0.0), py::float).filter(|d| d.is_finite())?;
            Some(json!({"name": name, "site": pr.get("site").cloned().unwrap_or(Value::Null),
                        "mode": pr.get("mode").cloned().unwrap_or(Value::Null), "n_goals": n, "route_m": len}))
        })
        .collect();
    axum::Json(json!({"routes": rows})).into_response()
}

/// A bag or route name kept to letters, digits, `-` and `_` (no traversal), at most 64 characters.
#[must_use]
pub fn safe_name(name: &str) -> String {
    let s: String = name
        .chars()
        .filter(|c| c.is_alphanumeric() || *c == '-' || *c == '_')
        .take(64)
        .collect();
    if s.is_empty() {
        "session".to_owned()
    } else {
        s
    }
}

async fn route_get(State(st): State<Arc<Stream>>, UrlPath(name): UrlPath<String>) -> Response {
    let p = st.cfg.routes_dir.join(format!("{}.json", safe_name(&name)));
    if p.is_file() {
        file(&p, "application/geo+json")
    } else {
        detail(StatusCode::NOT_FOUND, "route not found")
    }
}

async fn preview_heightmap(
    State(st): State<Arc<Stream>>,
    Query(q): Query<Vec<(String, String)>>,
) -> Response {
    // FastAPI takes the last of a repeated query parameter
    let site = q
        .iter()
        .rev()
        .find(|(k, _)| k == "site")
        .map_or(crate::protocol::DEFAULT_SITE, |(_, v)| v.as_str());
    match previews::real_heightmap_preview(site, &st.cfg.samples_dir, previews::PREVIEW_N) {
        Ok(out) => axum::Json(Value::Object(out)).into_response(),
        Err(PreviewError::NotFound(m)) => detail(StatusCode::NOT_FOUND, &m),
        Err(PreviewError::Invalid(m)) => detail(StatusCode::BAD_REQUEST, &m),
    }
}

/// The router over `st`.
pub fn router(st: Arc<Stream>) -> Router {
    Router::new()
        .route("/", get(index))
        .route("/stream", get(stream_view))
        .route("/vendor/{*path}", get(vendor))
        .route("/healthz", get(healthz))
        .route("/bundles", get(bundles))
        .route("/bags", get(bags))
        .route("/routes", get(routes_list))
        .route("/routes/{name}", get(route_get))
        .route("/preview/heightmap", get(preview_heightmap))
        .fallback(|| async { detail(StatusCode::NOT_FOUND, "Not Found") })
        .method_not_allowed_fallback(|| async {
            detail(StatusCode::METHOD_NOT_ALLOWED, "Method Not Allowed")
        })
        .layer(middleware::from_fn_with_state(Arc::clone(&st), guard))
        .with_state(st)
}
