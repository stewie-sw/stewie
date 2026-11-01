//! Account administration (RW-55b1; Python `routers.operators_admin`, `routers.invites`, `deps.require_role`):
//! the director-only operator panel (list, create, approve, revoke, re-role, reset, delete) with the last-director
//! guard, one-time invites (a director mints, the token holder redeems), and the director-only ledger view
//! `/events`. Every mutation is audit-logged after it succeeds, as the Python does.

use std::sync::Arc;

use axum::Router;
use axum::extract::{Path, Query, Request, State};
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::routing::{delete, get, post};
use serde_json::{Map, Value, json};

use crate::app::{
    ApiError, AppState, Head, blocking, body_model, err, log, parse_body, require_auth, split,
};
use crate::operators::{py_repr, role_rank};
use crate::validate::{self, Field, Kind, Model, get_str};

const INVITE_MINT: Model = Model {
    fields: &[
        Field(
            "role",
            Kind::Str {
                min: 0,
                max: usize::MAX,
                nullable: false,
                default: Some("operator"),
            },
        ),
        Field(
            "ttl_s",
            Kind::Float {
                gt: Some((0.0, "0")),
                ge: None,
                le: Some((7_776_000.0, "7776000")),
                default: Some(604_800.0),
            },
        ),
        Field(
            "max_uses",
            Kind::Int {
                ge: 1,
                le: 1000,
                default: 1,
            },
        ),
    ],
    forbid_extra: true,
};

const INVITE_REDEEM: Model = Model {
    fields: &[
        Field(
            "token",
            Kind::Str {
                min: 8,
                max: 512,
                nullable: false,
                default: None,
            },
        ),
        Field(
            "email",
            Kind::Str {
                min: 3,
                max: 320,
                nullable: false,
                default: None,
            },
        ),
        Field(
            "password",
            Kind::Str {
                min: 1,
                max: 1024,
                nullable: false,
                default: None,
            },
        ),
    ],
    forbid_extra: true,
};

/// The identity iff its role is director.
pub(crate) fn require_director(st: &AppState, h: &Head) -> Result<String, ApiError> {
    let identity = require_auth(st, h)?;
    let role = st
        .auth(Some(&h.cid))
        .role_of(&identity)
        .map_err(|e| err(StatusCode::INTERNAL_SERVER_ERROR, e))?;
    if role != "director" {
        return Err(err(
            StatusCode::FORBIDDEN,
            format!(
                "director role required (signed in as operator {})",
                py_repr(&identity)
            ),
        ));
    }
    Ok(identity)
}

/// The identity iff its role ranks at or above `min` on the ladder (an unknown role ranks below guest).
pub(crate) fn require_role(st: &AppState, h: &Head, min: &str) -> Result<String, ApiError> {
    let identity = require_auth(st, h)?;
    let role = st
        .auth(Some(&h.cid))
        .role_of(&identity)
        .map_err(|e| err(StatusCode::INTERNAL_SERVER_ERROR, e))?;
    if role_rank(Some(&role)) < role_rank(Some(min)) {
        return Err(err(
            StatusCode::FORBIDDEN,
            format!(
                "{min}+ role required (signed in as {role} {})",
                py_repr(&identity)
            ),
        ));
    }
    Ok(identity)
}

/// Refuse a change that leaves no active director: only when the target is an active director that the change
/// demotes or removes, and no other active director exists.
fn guard_last_director(
    st: &AppState,
    email: &str,
    still_director_after: bool,
) -> Result<(), ApiError> {
    if still_director_after {
        return Ok(());
    }
    let e = email.trim().to_lowercase();
    let actives: Vec<Value> = st
        .store
        .list_all()?
        .into_iter()
        .filter(|r| r["status"] == "active" && r["role"] == "director")
        .collect();
    if actives.iter().any(|r| r["email"] == e.as_str())
        && actives.iter().all(|r| r["email"] == e.as_str())
    {
        return Err(err(
            StatusCode::CONFLICT,
            "refused: this is the last active director (would lock out admin)",
        ));
    }
    Ok(())
}

#[allow(clippy::unnecessary_wraps)] // the handlers' success tail, beside their `?` exits
fn ok(body: Value) -> Result<Response, ApiError> {
    Ok(axum::Json(body).into_response())
}

async fn list(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let h = Head::of(&req);
    blocking(st, move |st| {
        require_director(st, &h)?;
        ok(json!({"ok": true, "operators": st.store.list_all()?}))
    })
    .await
}

/// A director-gated `body: dict` mutation: malformed JSON first, then the gate, then the body shape (`FastAPI`'s
/// order), then `f` with the director and the body.
async fn mutate(
    st: Arc<AppState>,
    req: Request,
    f: impl FnOnce(&AppState, &Head, &str, &Map<String, Value>) -> Result<Response, ApiError>
    + Send
    + 'static,
) -> Response {
    let (h, bytes) = split(req, st.settings.max_body).await;
    blocking(st, move |st| {
        let body = parse_body(&bytes?)?;
        let director = require_director(st, &h)?;
        let m = validate::dict(body.as_ref()).map_err(|e| err(StatusCode::BAD_REQUEST, e))?;
        f(st, &h, &director, m)
    })
    .await
}

fn email_of(m: &Map<String, Value>) -> String {
    get_str(m, "email", "").trim().to_lowercase()
}

async fn create(State(st): State<Arc<AppState>>, req: Request) -> Response {
    mutate(st, req, |st, h, director, m| {
        let (email, role) = (email_of(m), get_str(m, "role", "operator"));
        let rec =
            st.store
                .create_active(&email, &get_str(m, "password", ""), &role, Some(director))?;
        log(
            st,
            h,
            director,
            "admin.operator.create",
            &format!("{email} as {role}"),
        );
        ok(json!({"ok": true, "operator": rec}))
    })
    .await
}

async fn approve(State(st): State<Arc<AppState>>, req: Request) -> Response {
    mutate(st, req, |st, h, director, m| {
        let (email, role) = (email_of(m), get_str(m, "role", "operator"));
        let rec = st.store.approve(&email, director, &role)?;
        log(
            st,
            h,
            director,
            "admin.operator.approve",
            &format!("{email} as {role}"),
        );
        ok(json!({"ok": true, "operator": rec}))
    })
    .await
}

async fn revoke(State(st): State<Arc<AppState>>, req: Request) -> Response {
    mutate(st, req, |st, h, director, m| {
        let email = email_of(m);
        guard_last_director(st, &email, false)?;
        let rec = st.store.revoke(&email, director)?;
        log(st, h, director, "admin.operator.revoke", &email);
        ok(json!({"ok": true, "operator": rec}))
    })
    .await
}

async fn set_role(State(st): State<Arc<AppState>>, req: Request) -> Response {
    mutate(st, req, |st, h, director, m| {
        let (email, role) = (email_of(m), get_str(m, "role", "operator"));
        guard_last_director(st, &email, role == "director")?;
        let rec = st.store.set_role(&email, &role, director)?;
        log(
            st,
            h,
            director,
            "admin.operator.role",
            &format!("{email} -> {role}"),
        );
        ok(json!({"ok": true, "operator": rec}))
    })
    .await
}

async fn reset(State(st): State<Arc<AppState>>, req: Request) -> Response {
    mutate(st, req, |st, h, director, m| {
        let email = email_of(m);
        st.store
            .set_password(&email, &get_str(m, "new_password", ""))?;
        log(st, h, director, "admin.operator.reset", &email);
        ok(json!({"ok": true, "message": format!("password reset for {email}")}))
    })
    .await
}

async fn remove(
    State(st): State<Arc<AppState>>,
    Path(email): Path<String>,
    req: Request,
) -> Response {
    let h = Head::of(&req);
    blocking(st, move |st| {
        let director = require_director(st, &h)?;
        let e = email.trim().to_lowercase();
        guard_last_director(st, &e, false)?;
        let removed = st.store.delete(&e)?;
        log(st, &h, &director, "admin.operator.delete", &e);
        ok(json!({"ok": removed}))
    })
    .await
}

async fn invite_mint(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let (h, bytes) = split(req, st.settings.max_body).await;
    blocking(st, move |st| {
        let body = parse_body(&bytes?)?;
        let identity = require_role(st, &h, "director")?;
        let v = body_model(body.as_ref(), INVITE_MINT)?;
        let role = v["role"].as_str().unwrap_or("operator");
        let max_uses = v["max_uses"].as_i64().unwrap_or(1);
        let token = st.store.create_invite(
            &identity,
            role,
            v["ttl_s"].as_f64().unwrap_or(0.0),
            max_uses,
        )?;
        log(st, &h, &identity, "invite.mint", role);
        ok(json!({"ok": true, "token": token, "role": role, "max_uses": max_uses}))
    })
    .await
}

async fn invite_redeem(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let (h, bytes) = split(req, st.settings.max_body).await;
    blocking(st, move |st| {
        let body = parse_body(&bytes?)?;
        let v = body_model(body.as_ref(), INVITE_REDEEM)?;
        let s = |k: &str| v[k].as_str().unwrap_or("").to_owned();
        let rec = st
            .store
            .redeem_invite(&s("token"), &s("email"), &s("password"))?;
        let (email, role) = (rec["email"].as_str().unwrap_or(""), rec["role"].as_str());
        log(st, &h, email, "invite.redeem", role.unwrap_or(""));
        ok(json!({"ok": true, "email": email, "role": role.unwrap_or("operator")}))
    })
    .await
}

/// The newest-first ledger, director-only: the last `n` (1..=500, default 50) events, or with an `actor` (case-
/// insensitive) or `action` filter the whole live ledger scanned for up to `n` matches.
async fn events(
    State(st): State<Arc<AppState>>,
    Query(q): Query<Vec<(String, String)>>,
    req: Request,
) -> Response {
    let h = Head::of(&req);
    blocking(st, move |st| {
        require_director(st, &h)?;
        let last = |k: &str| q.iter().rev().find(|(n, _)| n == k).map(|(_, v)| v.clone());
        let n = match last("n") {
            Some(v) => {
                let m = validate::model(
                    Some(&json!({"n": v})),
                    Model {
                        fields: &[Field(
                            "n",
                            Kind::Int {
                                ge: i64::MIN,
                                le: i64::MAX,
                                default: 50,
                            },
                        )],
                        forbid_extra: false,
                    },
                )
                .map_err(|e| err(StatusCode::BAD_REQUEST, e))?;
                m["n"].as_i64().unwrap_or(50)
            }
            None => 50,
        };
        let cap = usize::try_from(n.clamp(1, 500)).unwrap_or(1);
        let actor = last("actor").unwrap_or_default().trim().to_lowercase();
        let action = last("action").unwrap_or_default();
        let filtering = !actor.is_empty() || !action.is_empty();
        let text = std::fs::read_to_string(st.ledger.path()).unwrap_or_default();
        let mut lines: Vec<&str> = text.lines().collect();
        if !filtering {
            lines = lines.split_off(lines.len().saturating_sub(cap));
        }
        let mut out = Vec::new();
        for line in lines.iter().rev() {
            let Ok(ev) = serde_json::from_str::<Value>(line) else {
                continue;
            };
            let ev_actor = validate::py_str(ev.get("actor").unwrap_or(&json!("")))
                .trim()
                .to_lowercase();
            if !actor.is_empty() && ev_actor != actor {
                continue;
            }
            if !action.is_empty()
                && validate::py_str(ev.get("action").unwrap_or(&json!(""))) != action
            {
                continue;
            }
            out.push(ev);
            if out.len() >= cap {
                break;
            }
        }
        ok(json!({"ok": true, "events": out}))
    })
    .await
}

/// The administration routes.
pub fn routes() -> Router<Arc<AppState>> {
    Router::new()
        .route("/admin/operators", get(list))
        .route("/admin/operators/create", post(create))
        .route("/admin/operators/approve", post(approve))
        .route("/admin/operators/revoke", post(revoke))
        .route("/admin/operators/role", post(set_role))
        .route("/admin/operators/reset", post(reset))
        .route("/admin/operators/{email}", delete(remove))
        .route("/admin/invite", post(invite_mint))
        .route("/auth/invite/redeem", post(invite_redeem))
        .route("/events", get(events))
}
