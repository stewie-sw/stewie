//! Content reads (RW-55b7c/d; Python `routers.sample_missions`, `program`, `pages`, `profiles`, `figures`): the
//! bundled sample missions, the program board and its snapshot, the landing and 3D viewer pages, the saved
//! planning profiles, and the validation figures. The bundled files are the checkout's
//! (`stewie/server/sample_missions`, `stewie/server/program_snapshot.json`, `stewie/server/web/*.html`); the figures
//! are `Settings.validation_dir`'s and profiles live under the data directory.

use std::path::PathBuf;
use std::sync::Arc;

use axum::Router;
use axum::extract::{Path, Request, State};
use axum::http::{HeaderValue, StatusCode, header};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use serde_json::{Value, json};

use crate::admin::require_role;
use crate::app::{AppState, Head, blocking, body_model, err, log, parse_body, require_auth, split};
use crate::operators::py_repr;
use crate::validate::{Field, Kind, Model, Ordered};

/// The checkout this binary was built from (the Python's repo-relative paths).
fn repo() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..")
}

/// The bundled sample missions by name (file stem), sorted.
fn sample_missions() -> Vec<(String, PathBuf)> {
    let dir = repo().join("stewie/server/sample_missions");
    let mut out: Vec<(String, PathBuf)> = std::fs::read_dir(&dir)
        .map(|rd| {
            rd.filter_map(Result::ok)
                .map(|e| e.path())
                // glob's `*.json`: no dotfiles
                .filter(|p| p.extension().is_some_and(|x| x == "json"))
                .filter(|p| {
                    !p.file_name()
                        .and_then(|n| n.to_str())
                        .is_some_and(|n| n.starts_with('.'))
                })
                .filter_map(|p| Some((p.file_stem()?.to_str()?.to_owned(), p)))
                .collect()
        })
        .unwrap_or_default();
    out.sort();
    out
}

/// The bundled sample missions (public).
async fn list_sample_missions() -> Response {
    let samples: Vec<Value> = sample_missions()
        .into_iter()
        .map(|(n, _)| json!({"name": n, "url": format!("/sample_mission/{n}")}))
        .collect();
    axum::Json(json!({"ok": true, "samples": samples})).into_response()
}

/// One bundled sample mission by its listed name (the list is the allowlist, so no traversal).
async fn get_sample_mission(Path(name): Path<String>) -> Response {
    // Starlette routes the decoded path, where an encoded `/` leaves the one-segment route unmatched
    if name.contains('/') {
        return err(
            StatusCode::NOT_FOUND,
            format!("no route /sample_mission/{name}"),
        )
        .into_response();
    }
    let Some((_, p)) = sample_missions().into_iter().find(|(n, _)| *n == name) else {
        return err(StatusCode::NOT_FOUND, format!("no sample mission {name}")).into_response();
    };
    match std::fs::read_to_string(&p)
        .ok()
        .and_then(|t| serde_json::from_str::<Value>(&t).ok())
    {
        Some(v) => axum::Json(v).into_response(),
        None => err(
            StatusCode::INTERNAL_SERVER_ERROR,
            format!("unreadable sample mission {name}"),
        )
        .into_response(),
    }
}

/// A bundled HTML page (public), or the Python's 404 naming it when this build lacks it.
fn page(file: &str, what: &str) -> Response {
    match std::fs::read(repo().join("stewie/server/web").join(file)) {
        Ok(b) => {
            let mut r = b.into_response();
            r.headers_mut().insert(
                header::CONTENT_TYPE,
                HeaderValue::from_static("text/html; charset=utf-8"),
            );
            r
        }
        Err(_) => err(
            StatusCode::NOT_FOUND,
            format!("{what} missing from this build"),
        )
        .into_response(),
    }
}

/// The program board page.
async fn program_page() -> Response {
    page("program.html", "program board page")
}

/// The landing page (`/landing`, `/landing.html`).
async fn landing_page() -> Response {
    page("landing.html", "landing page")
}

/// The standalone full-resolution 3D terrain viewer (`/viz`, `/viz_haworth.html`).
async fn viz_page() -> Response {
    page("viz_haworth.html", "viz page")
}

/// The program board's snapshot, generated from the committed PRD (public).
async fn program_snapshot() -> Response {
    match std::fs::read_to_string(repo().join("stewie/server/program_snapshot.json"))
        .ok()
        .and_then(|t| serde_json::from_str::<Value>(&t).ok())
    {
        Some(v) => axum::Json(v).into_response(),
        None => err(
            StatusCode::NOT_FOUND,
            "program_snapshot.json missing from this build; regenerate: scripts/gen_program_snapshot.py",
        )
        .into_response(),
    }
}

/// A profile name's file slug (Python `_profile_slug`): runs outside `[a-z0-9_-]` become `-`, trimmed of `-`.
fn profile_slug(name: &str) -> String {
    let mut out = String::new();
    let mut gap = false;
    for c in name.to_lowercase().chars() {
        if c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_' || c == '-' {
            if gap {
                out.push('-');
            }
            gap = false;
            out.push(c);
        } else {
            gap = true;
        }
    }
    let slug = out.trim_matches('-').to_owned();
    if slug.is_empty() {
        "profile".to_owned()
    } else {
        slug
    }
}

const PROFILE_REQ: Model = Model {
    fields: &[
        Field(
            "name",
            Kind::Str {
                min: 1,
                max: 80,
                nullable: false,
                default: None,
            },
        ),
        Field("profile", Kind::Dict),
    ],
    forbid_extra: false,
};

/// Save a planning profile (operator and above): the whole config snapshot under a slug of its name, written
/// atomically and audited.
async fn post_profile(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let (h, bytes) = split(req, st.settings.max_body).await;
    blocking(st, move |st| {
        let bytes = bytes?;
        let body = parse_body(&bytes)?;
        let identity = require_role(st, &h, "operator")?;
        let v = body_model(body.as_ref(), PROFILE_REQ)?;
        let name = v["name"].as_str().unwrap_or("").to_owned();
        let slug = profile_slug(&name);
        let dir = st.cfg.data_dir.join("profiles");
        std::fs::create_dir_all(&dir)
            .map_err(|e| err(StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;
        // the file as the Python writes it: `json.dumps({"name", "profile"}, indent=2)`, the profile in the client's key order
        let ordered: Ordered = serde_json::from_slice(&bytes)
            .map_err(|e| err(StatusCode::BAD_REQUEST, e.to_string()))?;
        let doc = Ordered::Object(vec![
            ("name".to_owned(), Ordered::String(name)),
            (
                "profile".to_owned(),
                ordered
                    .get("profile")
                    .cloned()
                    .unwrap_or(Ordered::Object(Vec::new())),
            ),
        ])
        .py_dumps_indent2()
        .map_err(|e| err(StatusCode::BAD_REQUEST, e))?;
        crate::atomic_write(&dir.join(format!("{slug}.json")), doc.as_bytes())
            .map_err(|e| err(StatusCode::INTERNAL_SERVER_ERROR, e))?;
        log(st, &h, &identity, "profile.save", &slug);
        Ok(axum::Json(json!({"ok": true, "name": slug})).into_response())
    })
    .await
}

/// The saved profile slugs, sorted (any authenticated caller).
async fn get_profiles(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let h = Head::of(&req);
    blocking(st, move |st| {
        require_auth(st, &h)?;
        let mut names: Vec<String> = std::fs::read_dir(st.cfg.data_dir.join("profiles"))
            .map(|rd| {
                rd.filter_map(Result::ok)
                    .filter_map(|e| {
                        e.file_name()
                            .to_str()?
                            .strip_suffix(".json")
                            .map(str::to_owned)
                    })
                    .collect()
            })
            .unwrap_or_default();
        names.sort();
        Ok(axum::Json(json!({"ok": true, "profiles": names})).into_response())
    })
    .await
}

/// One saved profile by its slug (any authenticated caller).
async fn get_profile(
    State(st): State<Arc<AppState>>,
    Path(name): Path<String>,
    req: Request,
) -> Response {
    if name.contains('/') {
        return err(StatusCode::NOT_FOUND, format!("no route /profile/{name}")).into_response();
    }
    let h = Head::of(&req);
    blocking(st, move |st| {
        require_auth(st, &h)?;
        let slug = profile_slug(&name);
        let doc = std::fs::read_to_string(
            st.cfg
                .data_dir
                .join("profiles")
                .join(format!("{slug}.json")),
        )
        .ok()
        .and_then(|t| serde_json::from_str::<Value>(&t).ok())
        .ok_or_else(|| {
            err(
                StatusCode::NOT_FOUND,
                format!("no profile {}", py_repr(&slug)),
            )
        })?;
        Ok(axum::Json(doc).into_response())
    })
    .await
}

/// Every PNG under the checkout's `validation/` tree by its relative key (the allowlist `/figure` serves from).
fn validation_figures(base: &std::path::Path) -> Vec<(String, PathBuf)> {
    fn walk(base: &std::path::Path, dir: &std::path::Path, out: &mut Vec<(String, PathBuf)>) {
        let Ok(rd) = std::fs::read_dir(dir) else {
            return;
        };
        for e in rd.filter_map(Result::ok) {
            let p = e.path();
            // `os.walk` does not descend into symlinked directories
            if e.file_type().is_ok_and(|t| t.is_dir()) {
                walk(base, &p, out);
            } else if p.extension().is_some_and(|x| x == "png")
                && let Ok(rel) = p.strip_prefix(base)
            {
                out.push((rel.to_string_lossy().replace('\\', "/"), p.clone()));
            }
        }
    }
    let mut out = Vec::new();
    walk(base, base, &mut out);
    out.sort();
    out
}

/// The validation figures (any authenticated caller), by category.
async fn get_figures(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let h = Head::of(&req);
    blocking(st, move |st| {
        require_auth(st, &h)?;
        let figs: Vec<Value> = validation_figures(&st.settings.validation_dir)
            .into_iter()
            .map(|(k, _)| {
                let category = k.split('/').next().unwrap_or("").to_owned();
                json!({"key": k, "category": category, "url": format!("/figure/{k}")})
            })
            .collect();
        Ok(axum::Json(json!({"ok": true, "figures": figs})).into_response())
    })
    .await
}

/// One validation figure by its listed key (any authenticated caller).
async fn get_figure(
    State(st): State<Arc<AppState>>,
    Path(key): Path<String>,
    req: Request,
) -> Response {
    let h = Head::of(&req);
    blocking(st, move |st| {
        require_auth(st, &h)?;
        let Some((_, p)) = validation_figures(&st.settings.validation_dir)
            .into_iter()
            .find(|(k, _)| *k == key)
        else {
            return Err(err(StatusCode::NOT_FOUND, format!("no figure {key}")));
        };
        let bytes =
            std::fs::read(&p).map_err(|e| err(StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;
        let mut r = bytes.into_response();
        r.headers_mut()
            .insert(header::CONTENT_TYPE, HeaderValue::from_static("image/png"));
        Ok(r)
    })
    .await
}

/// The content routes.
pub fn routes() -> Router<Arc<AppState>> {
    Router::new()
        .route("/sample_missions", get(list_sample_missions))
        .route("/sample_mission/{name}", get(get_sample_mission))
        .route("/program", get(program_page))
        .route("/program/snapshot", get(program_snapshot))
        .route("/landing", get(landing_page))
        .route("/landing.html", get(landing_page))
        .route("/viz", get(viz_page))
        .route("/viz_haworth.html", get(viz_page))
        .route("/profile", post(post_profile))
        .route("/profiles", get(get_profiles))
        .route("/profile/{name}", get(get_profile))
        .route("/figures", get(get_figures))
        .route("/figure/{*key}", get(get_figure))
}
