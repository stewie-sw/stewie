//! The HTTP app (RW-55a2b; Python `stewie.server.server`, `deps`, `routers.auth`, `routers.health`): the identity
//! routes, `/healthz`, the `{ok: false, error}` envelopes, and the response middleware, in Axum. One shared
//! [`AppState`] holds the account store, the ledger and the rate limiters, so their locks and health are the
//! process's; an [`Auth`] is borrowed from it per request.
//!
//! Behaviour follows the Python's observable contract (status, body, hardening headers, cookies, audit lines): the
//! oracle replays a `FastAPI` `TestClient` session. Request bodies are validated by hand, with Pydantic's wording.

use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Instant;

use axum::Router;
use axum::body::{Body, Bytes};
use axum::extract::{ConnectInfo, DefaultBodyLimit, Request, State};
use axum::http::{HeaderMap, HeaderValue, Method, StatusCode, header};
use axum::middleware::{self, Next};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use serde_json::{Value, json};
use subtle::ConstantTimeEq;

use crate::auth::{Auth, AuthConfig, TOKEN_TTL_S};
use crate::operators::{Store, StoreError, py_repr};
use crate::services::{AUDIT_DEFAULT_MAX_BYTES, Ledger, RateLimiter, new_correlation_id};
use crate::validate::{self, Field, Kind, Model};
use crate::{Clock, Entropy};

/// The browser's session credential (`HttpOnly`).
pub const SESSION_COOKIE: &str = "stewie_session";
/// The double-submit CSRF token (readable by the page).
pub const CSRF_COOKIE: &str = "stewie_csrf";
const fn text(max: usize) -> Kind {
    Kind::Str {
        min: 0,
        max,
        nullable: false,
        default: Some(""),
    }
}
const OPTIONAL: Kind = Kind::Str {
    min: 0,
    max: 256,
    nullable: true,
    default: None,
};
const LOGIN: Model = Model {
    fields: &[Field("email", text(254)), Field("password", OPTIONAL)],
    forbid_extra: false,
};
const REGISTER: Model = Model {
    fields: &[Field("email", text(254)), Field("password", text(256))],
    forbid_extra: false,
};
const PASSWORD: Model = Model {
    fields: &[
        Field("new_password", text(256)),
        Field("old_password", OPTIONAL),
    ],
    forbid_extra: false,
};

/// The server settings beyond identity, from the environment.
#[derive(Debug, Clone, PartialEq)]
pub struct Settings {
    /// `STEWIE_OPERATOR_LOGIN` (default on): password and bootstrap sign-in.
    pub operator_login: bool,
    /// `STEWIE_REGISTRATION=1`: self-service access requests (default closed).
    pub registration_open: bool,
    /// `STEWIE_TRUST_PROXY=1`: rate-limit by the first `X-Forwarded-For` hop.
    pub trust_proxy: bool,
    /// `STEWIE_MAX_BODY_BYTES` (4 MiB).
    pub max_body: usize,
    /// `STEWIE_AUTH_RATE_MAX` per `STEWIE_AUTH_RATE_WINDOW_S` (10 per 60 s).
    pub rate_max: i64,
    pub rate_window_s: f64,
    /// `STEWIE_AUDIT_MAX_BYTES` (16 MiB).
    pub audit_max_bytes: u64,
}

impl Settings {
    /// # Errors
    /// A malformed number, `STEWIE_DATABASE_URL` set (the world-transaction projection is not ported), or
    /// `STEWIE_CORS_ORIGINS` set (cross-origin access is not served by this server yet;
    /// refusing beats silently ignoring a configured allowlist).
    pub fn from_env(get: &dyn Fn(&str) -> Option<String>) -> Result<Self, String> {
        let var = |k: &str| get(k).unwrap_or_default();
        let num = |k: &str, d: &str| -> Result<f64, String> {
            let v = Some(var(k))
                .filter(|v| !v.trim().is_empty())
                .unwrap_or_else(|| d.to_owned());
            v.trim()
                .parse::<f64>()
                .map_err(|e| format!("{k}={v:?}: {e}"))
        };
        if !var("STEWIE_DATABASE_URL").trim().is_empty() {
            return Err("STEWIE_DATABASE_URL is set, but the Rust server does not mirror world transactions to a \
                        database yet (D-R113); the journal is the authority. Unset it"
                .to_owned());
        }
        if !var("STEWIE_CORS_ORIGINS").trim().is_empty() {
            return Err("STEWIE_CORS_ORIGINS is set, but the Rust server serves same-origin only (D-R108); unset it"
                .to_owned());
        }
        #[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)]
        Ok(Self {
            operator_login: var("STEWIE_OPERATOR_LOGIN") != "0",
            registration_open: var("STEWIE_REGISTRATION") == "1",
            trust_proxy: var("STEWIE_TRUST_PROXY") == "1",
            max_body: num("STEWIE_MAX_BODY_BYTES", "4194304")? as usize,
            rate_max: num("STEWIE_AUTH_RATE_MAX", "10")? as i64,
            rate_window_s: num("STEWIE_AUTH_RATE_WINDOW_S", "60")?,
            audit_max_bytes: num(
                "STEWIE_AUDIT_MAX_BYTES",
                &AUDIT_DEFAULT_MAX_BYTES.to_string(),
            )? as u64,
        })
    }
}

/// The Moon's reference sphere, from the body registry.
fn moon_sphere() -> Result<lunar_frames::Sphere, String> {
    let reg: Value =
        serde_json::from_str(include_str!("../../stewie-contracts/fixtures/bodies.json"))
            .map_err(|e| format!("the body registry: {e}"))?;
    let r = reg["moon"]["ellipsoid_radius_m"]
        .as_f64()
        .ok_or("the body registry has no Moon radius")?;
    lunar_frames::Sphere::new(r).map_err(|e| e.to_string())
}

/// Everything a request may touch, built once.
pub struct AppState {
    pub cfg: AuthConfig,
    pub settings: Settings,
    pub store: Store<'static>,
    pub ledger: Ledger<'static>,
    pub clock: &'static dyn Clock,
    pub entropy: &'static dyn Entropy,
    /// The site DEMs, observed twins and composed terrain view.
    pub terrain: crate::state::Terrain,
    /// The linked world-state log (`data_dir/twin/world.journal`).
    pub world: crate::world::WorldState,
    /// The registries and planner parameters the planning routes share.
    pub planning: crate::planning::Planning,
    login_ip: RateLimiter,
    login_acct: RateLimiter,
    register_ip: RateLimiter,
    started: Instant,
}

impl std::fmt::Debug for AppState {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("AppState")
            .field("settings", &self.settings)
            .finish_non_exhaustive()
    }
}

impl AppState {
    /// Read and check the configuration, then seed the founding director from `STEWIE_BOOTSTRAP_DIRECTOR` /
    /// `STEWIE_BOOTSTRAP_PASSWORD` when none exists.
    ///
    /// # Errors
    /// Any startup guard, or an untrustworthy account store.
    pub fn from_env(
        get: &dyn Fn(&str) -> Option<String>,
        clock: &'static dyn Clock,
        entropy: &'static dyn Entropy,
    ) -> Result<Self, String> {
        let cfg = AuthConfig::from_env(get)?;
        let settings = Settings::from_env(get)?;
        let store = Store::new(cfg.data_dir.clone(), clock, entropy);
        let ledger = Ledger::new(cfg.data_dir.clone(), settings.audit_max_bytes, clock);
        let lim = || RateLimiter::new(settings.rate_max, settings.rate_window_s);
        let terrain = crate::state::Terrain::new(
            cfg.data_dir.clone(),
            get("STEWIE_SAMPLES_DIR")
                .filter(|d| !d.is_empty())
                .map_or_else(
                    // the bundles of the checkout this binary was built from, as the Python's repo-relative path
                    || {
                        std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                            .join("../../samples/lunar_dem")
                    },
                    std::path::PathBuf::from,
                ),
            get("STEWIE_DEM_DIR")
                .filter(|d| !d.is_empty())
                .map(std::path::PathBuf::from),
            serde_json::from_str(include_str!("../../stewie-contracts/fixtures/sites.json"))
                .map_err(|e| format!("the site registry: {e}"))?,
            moon_sphere()?,
        );
        let world =
            crate::world::WorldState::open(&cfg.data_dir.join("twin").join("world.journal"))?;
        let planning = crate::planning::Planning::from_env(get)?;
        let state = Self {
            terrain,
            world,
            planning,
            login_ip: lim(),
            login_acct: lim(),
            register_ip: lim(),
            cfg,
            settings,
            store,
            ledger,
            clock,
            entropy,
            started: Instant::now(),
        };
        let (email, password) = (
            get("STEWIE_BOOTSTRAP_DIRECTOR").unwrap_or_default(),
            get("STEWIE_BOOTSTRAP_PASSWORD").unwrap_or_default(),
        );
        if let Some(seeded) = state
            .store
            .bootstrap_director(&email, &password)
            .map_err(String::from)?
        {
            eprintln!(
                "bootstrap: seeded founding director {seeded:?} (sign in with STEWIE_BOOTSTRAP_PASSWORD)"
            );
        }
        Ok(state)
    }

    pub(crate) fn auth<'a>(&'a self, cid: Option<&'a str>) -> Auth<'a> {
        Auth {
            cfg: &self.cfg,
            store: &self.store,
            clock: self.clock,
            entropy: self.entropy,
            ledger: &self.ledger,
            cid,
        }
    }

    /// Monotonic seconds, for the rate windows.
    fn mono(&self) -> f64 {
        self.started.elapsed().as_secs_f64()
    }
}

/// An error response in the `{ok: false, error}` envelope.
#[derive(Debug)]
pub struct ApiError(pub StatusCode, pub String);

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        (self.0, axum::Json(json!({"ok": false, "error": self.1}))).into_response()
    }
}

pub(crate) fn err(status: StatusCode, msg: impl Into<String>) -> ApiError {
    ApiError(status, msg.into())
}

impl From<StoreError> for ApiError {
    fn from(e: StoreError) -> Self {
        match e {
            StoreError::Invalid(m) => err(StatusCode::BAD_REQUEST, m),
            StoreError::Store(m) => err(StatusCode::INTERNAL_SERVER_ERROR, m),
        }
    }
}

/// The request's correlation id (set by the outermost layer).
#[derive(Debug, Clone)]
struct Cid(String);

/// What a handler needs from the request head.
#[derive(Debug, Clone)]
pub(crate) struct Head {
    pub(crate) method: Method,
    pub(crate) headers: HeaderMap,
    pub(crate) peer: Option<String>,
    pub(crate) cid: String,
}

impl Head {
    pub(crate) fn of(req: &Request) -> Self {
        Self {
            method: req.method().clone(),
            headers: req.headers().clone(),
            peer: req
                .extensions()
                .get::<ConnectInfo<SocketAddr>>()
                .map(|c| c.0.ip().to_string()),
            cid: req
                .extensions()
                .get::<Cid>()
                .map_or_else(String::new, |c| c.0.clone()),
        }
    }

    pub(crate) fn header(&self, name: &str) -> Option<String> {
        self.headers
            .get(name)
            .and_then(|v| v.to_str().ok())
            .map(str::to_owned)
    }

    fn cookie(&self, name: &str) -> Option<String> {
        self.headers
            .get_all(header::COOKIE)
            .iter()
            .filter_map(|v| v.to_str().ok())
            .flat_map(|v| v.split(';'))
            .find_map(|kv| {
                let (k, v) = kv.split_once('=')?;
                (k.trim() == name).then(|| v.trim().trim_matches('"').to_owned())
            })
    }

    /// The direct peer is loopback (or unknown, as for an in-process client).
    fn loopback(&self) -> bool {
        self.peer
            .as_deref()
            .is_none_or(|p| matches!(p, "127.0.0.1" | "::1"))
    }

    /// The rate-limit key: the first forwarded hop behind a trusted proxy, else the peer.
    fn client_ip(&self, st: &AppState) -> String {
        if st.settings.trust_proxy
            && let Some(xff) = self.header("x-forwarded-for").filter(|x| !x.is_empty())
        {
            return xff.split(',').next().unwrap_or("").trim().to_owned();
        }
        self.peer.clone().unwrap_or_else(|| "-".to_owned())
    }

    /// The explicit header credential: `X-API-Key`, else the `Authorization` value without its `Bearer ` prefix.
    fn supplied(&self) -> String {
        self.header("x-api-key")
            .filter(|k| !k.is_empty())
            .unwrap_or_else(|| {
                let a = self.header("authorization").unwrap_or_default();
                a.strip_prefix("Bearer ").unwrap_or(&a).trim().to_owned()
            })
    }
}

fn same(a: &str, b: &str) -> bool {
    a.as_bytes().ct_eq(b.as_bytes()).into()
}

/// The caller's identity, in the Python's order, failing closed: the desktop app on loopback, the scoped public-GIS
/// key, a trusted-proxy Tailscale identity, an explicit header credential (session token or automation key,
/// CSRF-exempt), then the session cookie (CSRF-checked on a state-changing method).
pub(crate) fn require_auth(st: &AppState, h: &Head) -> Result<String, ApiError> {
    if st.cfg.desktop && h.loopback() {
        return Ok("desktop-local".to_owned());
    }
    if let Some(k) = h.header("x-stewie-anon-key")
        && !k.is_empty()
        && !st.cfg.gis_anon_key.is_empty()
        && same(&k, &st.cfg.gis_anon_key)
    {
        return Ok("gis-anon".to_owned());
    }
    let auth = st.auth(Some(&h.cid));
    if let Some(ts) = auth.tailscale_identity(
        &h.header("tailscale-user-login").unwrap_or_default(),
        h.peer.as_deref(),
    ) {
        return Ok(ts);
    }
    let supplied = h.supplied();
    if !supplied.is_empty() {
        if let Some(op) = auth.verify_token(&supplied, None) {
            return Ok(op);
        }
        if same(&supplied, &st.cfg.api_key) {
            return Ok("api-key".to_owned());
        }
        return Err(err(StatusCode::UNAUTHORIZED, "invalid or missing API key"));
    }
    if let Some(tok) = h.cookie(SESSION_COOKIE)
        && let Some(op) = auth.verify_token(&tok, None)
    {
        if !matches!(
            h.method,
            Method::GET | Method::HEAD | Method::OPTIONS | Method::TRACE
        ) {
            let sent = h.header("x-csrf-token").unwrap_or_default();
            let cookie = h.cookie(CSRF_COOKIE).unwrap_or_default();
            if sent.is_empty() || cookie.is_empty() || !same(&sent, &cookie) {
                return Err(err(StatusCode::FORBIDDEN, "CSRF token missing or invalid"));
            }
        }
        return Ok(op);
    }
    Err(err(StatusCode::UNAUTHORIZED, "invalid or missing API key"))
}

/// Parse a JSON body (empty means absent); a parse failure is the Python's `bad JSON` envelope.
pub(crate) fn parse_body(bytes: &Bytes) -> Result<Option<Value>, ApiError> {
    validate::parse(bytes).map_err(|m| err(StatusCode::BAD_REQUEST, m))
}

/// Validate a parsed body against a model, as the Python's 400 envelope on failure.
pub(crate) fn body_model(
    body: Option<&Value>,
    m: Model,
) -> Result<serde_json::Map<String, Value>, ApiError> {
    validate::model(body, m).map_err(|e| err(StatusCode::BAD_REQUEST, e))
}

/// The session and CSRF cookies of a sign-in (both `SameSite=strict`, `Secure` when TLS is terminated upstream).
fn session_cookies(st: &AppState, token: &str) -> [String; 2] {
    let secure = if st.cfg.tls_terminated {
        "; Secure"
    } else {
        ""
    };
    let csrf = {
        use base64::Engine as _;
        let mut b = [0_u8; 32];
        st.entropy.fill(&mut b);
        base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(b)
    };
    #[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)]
    let age = TOKEN_TTL_S as u64;
    [
        format!(
            "{SESSION_COOKIE}={token}; HttpOnly; Max-Age={age}; Path=/; SameSite=strict{secure}"
        ),
        format!("{CSRF_COOKIE}={csrf}; Max-Age={age}; Path=/; SameSite=strict{secure}"),
    ]
}

fn with_cookies(body: Value, cookies: &[String]) -> Response {
    let mut r = axum::Json(body).into_response();
    for c in cookies {
        if let Ok(v) = HeaderValue::from_str(c) {
            r.headers_mut().append(header::SET_COOKIE, v);
        }
    }
    r
}

fn token_response(
    st: &AppState,
    h: &Head,
    email: &str,
    must_set_password: bool,
) -> Result<Response, ApiError> {
    let auth = st.auth(Some(&h.cid));
    // the token id's bytes are drawn before the CSRF token's, as the Python does
    let token = auth.issue_token(email, None);
    let cookies = session_cookies(st, &token);
    let role = auth
        .role_of(email)
        .map_err(|e| err(StatusCode::INTERNAL_SERVER_ERROR, e))?;
    // whole seconds, an integer in the body as the Python's 12 * 3600
    #[allow(clippy::cast_possible_truncation)]
    let ttl_s = TOKEN_TTL_S as i64;
    Ok(with_cookies(
        json!({"ok": true, "operator": email, "token": token, "ttl_s": ttl_s, "role": role,
               "must_set_password": must_set_password}),
        &cookies,
    ))
}

pub(crate) fn log(st: &AppState, h: &Head, actor: &str, action: &str, target: &str) {
    st.ledger
        .log_event(actor, action, target, Some(&h.cid), &serde_json::Map::new());
}

/// Run a handler body off the async workers (the credential paths run PBKDF2).
pub(crate) async fn blocking(
    st: Arc<AppState>,
    f: impl FnOnce(&AppState) -> Result<Response, ApiError> + Send + 'static,
) -> Response {
    match tokio::task::spawn_blocking(move || f(&st)).await {
        Ok(Ok(r)) => r,
        Ok(Err(e)) => e.into_response(),
        Err(e) => err(StatusCode::INTERNAL_SERVER_ERROR, e.to_string()).into_response(),
    }
}

pub(crate) async fn split(req: Request, max: usize) -> (Head, Result<Bytes, ApiError>) {
    let head = Head::of(&req);
    let bytes = axum::body::to_bytes(req.into_body(), max.saturating_add(1))
        .await
        .map_err(|e| err(StatusCode::BAD_REQUEST, e.to_string()));
    (head, bytes)
}

async fn healthz(State(st): State<Arc<AppState>>) -> Response {
    let audit = st.ledger.audit_health();
    let revocation = st.ledger.revocation_health();
    // BP-04: identity configured by neither an allowlist nor a director list (in Rust this admits nobody)
    let on_defaults = st.cfg.allowed.is_empty() && st.cfg.directors.is_none();
    let identity_degraded = on_defaults && st.cfg.tls_terminated;
    let degraded = audit.degraded || revocation.degraded || identity_degraded;
    axum::Json(json!({
        "status": if degraded { "degraded" } else { "ok" }, "version": env!("CARGO_PKG_VERSION"),
        "uptime_s": st.started.elapsed().as_secs_f64(), "audit": audit.to_json(), "revocation": revocation.to_json(),
        "identity": {"on_builtin_defaults": on_defaults, "degraded": identity_degraded},
    }))
    .into_response()
}

async fn auth_config(State(st): State<Arc<AppState>>) -> Response {
    axum::Json(
        json!({"ok": true, "operator_login": st.settings.operator_login, "desktop": st.cfg.desktop,
                      "registration_open": st.settings.registration_open}),
    )
    .into_response()
}

async fn auth_login(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let (h, bytes) = split(req, st.settings.max_body).await;
    blocking(st, move |st| {
        let body = parse_body(&bytes?)?;
        let v = body_model(body.as_ref(), LOGIN)?;
        if !st.settings.operator_login {
            return Err(err(
                StatusCode::FORBIDDEN,
                "operator login is disabled (STEWIE_OPERATOR_LOGIN=0); use the API key",
            ));
        }
        let email = v["email"].as_str().unwrap_or("").trim().to_lowercase();
        let password = v["password"]
            .as_str()
            .filter(|p| !p.is_empty())
            .map(str::to_owned);
        let header_credential = h.header("x-api-key").is_some_and(|k| !k.is_empty())
            || h.header("authorization").is_some_and(|a| !a.is_empty());
        // only the password-less key/proxy bootstrap is exempt; the PBKDF2 path is always limited
        if password.is_some() || !header_credential {
            let now = st.mono();
            if !st.login_ip.allow(&h.client_ip(st), now, 1)
                || (!email.is_empty() && !st.login_acct.allow(&email, now, 1))
            {
                return Err(err(
                    StatusCode::TOO_MANY_REQUESTS,
                    "too many login attempts; slow down",
                ));
            }
        }
        if let Some(pw) = password {
            let ip = h.client_ip(st);
            let Some(op) = st.store.verify_credentials(&email, &pw, Some(&ip))? else {
                return Err(err(StatusCode::FORBIDDEN, "invalid credentials"));
            };
            log(st, &h, &op, "auth.login", "password");
            return token_response(st, &h, &op, false);
        }
        if !legacy_authed(st, &h, &email) {
            return Err(err(StatusCode::UNAUTHORIZED, "invalid or missing API key"));
        }
        let auth = st.auth(Some(&h.cid));
        if !auth
            .is_allowed(&email)
            .map_err(|e| err(StatusCode::INTERNAL_SERVER_ERROR, e))?
        {
            return Err(err(
                StatusCode::FORBIDDEN,
                format!("{} is not a whitelisted operator", py_repr(&email)),
            ));
        }
        if st.store.has_password(&email)? {
            return Err(err(
                StatusCode::FORBIDDEN,
                "this account has a password -- sign in with it",
            ));
        }
        log(st, &h, &email, "auth.login", "bootstrap");
        token_response(st, &h, &email, true)
    })
    .await
}

/// The password-less bootstrap, bound to `email`: a trusted-proxy identity equal to it, a session token whose
/// subject is it, or the raw automation key (which carries no subject).
fn legacy_authed(st: &AppState, h: &Head, email: &str) -> bool {
    let auth = st.auth(Some(&h.cid));
    let e = email.trim().to_lowercase();
    if auth
        .tailscale_identity(
            &h.header("tailscale-user-login").unwrap_or_default(),
            h.peer.as_deref(),
        )
        .as_deref()
        == Some(e.as_str())
    {
        return true;
    }
    let supplied = h.supplied();
    if !supplied.is_empty() && auth.verify_token(&supplied, None).as_deref() == Some(e.as_str()) {
        return true;
    }
    same(&supplied, &st.cfg.api_key)
}

async fn auth_logout(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let h = Head::of(&req);
    let auth = st.auth(Some(&h.cid));
    let mut actor = "anonymous".to_owned();
    if let Some(claims) = h
        .cookie(SESSION_COOKIE)
        .and_then(|t| auth.decode_claims(&t))
    {
        if let Some(op) = claims["op"].as_str().filter(|o| !o.is_empty()) {
            op.clone_into(&mut actor);
        }
        if let Some(jti) = claims["jti"].as_str().filter(|j| !j.is_empty()) {
            // an unreadable store already fails closed at verify; the cookies are cleared regardless
            let _ = auth.revoke_jti(jti);
        }
    }
    let expires = httpdate::fmt_http_date(
        std::time::UNIX_EPOCH + std::time::Duration::from_secs_f64(st.clock.now().max(0.0)),
    );
    let gone =
        |name: &str| format!("{name}=\"\"; expires={expires}; Max-Age=0; Path=/; SameSite=lax");
    log(&st, &h, &actor, "auth.logout", "session cleared");
    with_cookies(
        json!({"ok": true}),
        &[gone(SESSION_COOKIE), gone(CSRF_COOKIE)],
    )
}

async fn auth_register(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let (h, bytes) = split(req, st.settings.max_body).await;
    blocking(st, move |st| {
        let body = parse_body(&bytes?)?;
        let v = body_model(body.as_ref(), REGISTER)?;
        if !st.settings.registration_open {
            return Err(err(StatusCode::FORBIDDEN, "registration is closed"));
        }
        if !st.register_ip.allow(&h.client_ip(st), st.mono(), 1) {
            return Err(err(StatusCode::TOO_MANY_REQUESTS, "too many registration attempts; slow down"));
        }
        let email = v["email"].as_str().unwrap_or("").trim().to_lowercase();
        let rec = st.store.register(&email, v["password"].as_str().unwrap_or(""), "operator", "pending", None)?;
        log(st, &h, &email, "auth.register", "pending");
        Ok(axum::Json(json!({"ok": true, "status": rec["status"],
                              "message": "request received -- a director must approve this account before sign-in"}))
        .into_response())
    })
    .await
}

async fn auth_me(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let h = Head::of(&req);
    let run = || -> Result<Response, ApiError> {
        let identity = require_auth(&st, &h)?;
        let role = st
            .auth(Some(&h.cid))
            .role_of(&identity)
            .map_err(|e| err(StatusCode::INTERNAL_SERVER_ERROR, e))?;
        Ok(
            axum::Json(json!({"ok": true, "identity": identity, "role": role,
                              "has_password": st.store.has_password(&identity)?}))
            .into_response(),
        )
    };
    run().unwrap_or_else(IntoResponse::into_response)
}

async fn auth_password(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let (h, bytes) = split(req, st.settings.max_body).await;
    blocking(st, move |st| {
        // FastAPI's order: a malformed body first, then the auth dependency, then the fields
        let body = parse_body(&bytes?)?;
        let identity = require_auth(st, &h)?;
        let v = body_model(body.as_ref(), PASSWORD)?;
        if matches!(identity.as_str(), "api-key" | "dev-open") {
            return Err(err(
                StatusCode::BAD_REQUEST,
                "an automation identity has no password",
            ));
        }
        let new = v["new_password"].as_str().unwrap_or("");
        if st.store.get(&identity)?.is_none() {
            // a fallback-allowlist identity becomes a real active account, its role preserved
            let role = st
                .auth(Some(&h.cid))
                .role_of(&identity)
                .map_err(|e| err(StatusCode::INTERNAL_SERVER_ERROR, e))?;
            st.store
                .create_active(&identity, new, &role, Some(&identity))?;
        } else if st.store.has_password(&identity)? {
            if !st
                .store
                .verify_old_password(&identity, v["old_password"].as_str().unwrap_or(""))?
            {
                return Err(err(StatusCode::FORBIDDEN, "current password is incorrect"));
            }
            st.store.set_password(&identity, new)?;
        } else {
            st.store.set_password(&identity, new)?;
        }
        log(st, &h, &identity, "auth.password", "set");
        Ok(axum::Json(json!({"ok": true, "message": "password set"})).into_response())
    })
    .await
}

/// Starlette's catch-alls: an unmatched GET or POST is a 404 naming the path; any other method is a 405.
async fn no_route(req: Request) -> Response {
    if matches!(*req.method(), Method::GET | Method::HEAD | Method::POST) {
        err(
            StatusCode::NOT_FOUND,
            format!("no route {}", req.uri().path()),
        )
        .into_response()
    } else {
        err(StatusCode::METHOD_NOT_ALLOWED, "Method Not Allowed").into_response()
    }
}

/// The hardening headers, set where a handler has not.
async fn security_headers(req: Request, next: Next) -> Response {
    let mut r = next.run(req).await;
    let h = r.headers_mut();
    for (k, v) in [
        ("x-content-type-options", "nosniff"),
        ("referrer-policy", "strict-origin-when-cross-origin"),
        (
            "permissions-policy",
            "geolocation=(), microphone=(), camera=()",
        ),
    ] {
        h.entry(k).or_insert(HeaderValue::from_static(v));
    }
    r
}

/// The public-GET caching policy (Python `cache_control.classify`): dynamic world and planner reads are never
/// stored (set even on errors), static DEM-derived products may be edge-cached five minutes (set only on a 200
/// that does not already say). The `traffic` drape is the one dynamic kind.
fn cache_directive(path: &str, query: Option<&str>) -> Option<(&'static str, bool)> {
    const NO_STORE_PATHS: [&str; 11] = [
        "/world/site-markers",
        "/world/point",
        "/world/points",
        "/world/transect",
        "/world/layer-manifest",
        "/world/layer-catalog",
        "/world/layer-consumption",
        "/world/traffic-layer",
        "/world/terramechanics-layers",
        "/world/site-suitability",
        "/world/keepouts-from-hazard",
    ];
    const STATIC_EXACT: [&str; 4] = [
        "/dem/heightfield_full",
        "/dem/heightfield_full/meta",
        "/dem/graticule",
        "/layers/legend",
    ];
    const NO_STORE: (&str, bool) = ("no-store", true);
    const STATIC: (&str, bool) = ("public, max-age=300", false);
    let by_kind = |k: Option<&str>| {
        if k == Some("traffic") {
            NO_STORE
        } else {
            STATIC
        }
    };
    let param = |name: &str| {
        query?.split('&').find_map(|kv| {
            let (k, v) = kv.split_once('=').unwrap_or((kv, ""));
            k.eq_ignore_ascii_case(name).then_some(v)
        })
    };
    if NO_STORE_PATHS.contains(&path) {
        return Some(NO_STORE);
    }
    if let Some(rest) = path.strip_prefix("/layers/globe/") {
        if let Some(kind) = rest.strip_suffix(".png").filter(|k| !k.contains('/')) {
            return Some(by_kind(Some(kind)));
        }
        if rest.strip_suffix("/bbox").is_some_and(|k| !k.contains('/')) {
            return Some(STATIC);
        }
    }
    if path == "/dem/heightfield_full/layer.png" {
        return Some(by_kind(Some(
            param("kind").filter(|k| !k.is_empty()).unwrap_or("dem"),
        )));
    }
    if path == "/ogc/wms" {
        let layer = param("layers")
            .filter(|v| !v.is_empty())
            .map(|v| v.split(',').next().unwrap_or("").trim());
        return Some(by_kind(layer));
    }
    STATIC_EXACT.contains(&path).then_some(STATIC)
}

async fn cache_control(req: Request, next: Next) -> Response {
    let directive = cache_directive(req.uri().path(), req.uri().query());
    let mut r = next.run(req).await;
    if let Some((value, overwrite)) = directive {
        let v = HeaderValue::from_static(value);
        if overwrite {
            r.headers_mut().insert(header::CACHE_CONTROL, v);
        } else if r.status() == StatusCode::OK {
            r.headers_mut().entry(header::CACHE_CONTROL).or_insert(v);
        }
    }
    r
}

/// The outermost layer: the correlation id (an inbound `X-Correlation-Id` / `X-Request-Id`, else a fresh one),
/// and the body-size cap on POST/PUT/PATCH (declared, then actual). An over-cap request is answered here, before
/// any other layer, as the Python's.
async fn correlate(State(st): State<Arc<AppState>>, req: Request, next: Next) -> Response {
    let cid = {
        let inbound = |n: &str| {
            req.headers()
                .get(n)
                .and_then(|v| v.to_str().ok())
                .filter(|v| !v.is_empty())
                .map(str::to_owned)
        };
        inbound("x-correlation-id")
            .or_else(|| inbound("x-request-id"))
            .unwrap_or_else(|| new_correlation_id(st.entropy))
    };
    let max = st.settings.max_body;
    let too_large = || {
        err(
            StatusCode::PAYLOAD_TOO_LARGE,
            format!("request body too large (> {max} bytes)"),
        )
        .into_response()
    };
    let mut req = req;
    if matches!(*req.method(), Method::POST | Method::PUT | Method::PATCH) {
        let declared = req
            .headers()
            .get(header::CONTENT_LENGTH)
            .and_then(|v| v.to_str().ok())
            .and_then(|v| v.trim().parse::<usize>().ok())
            .unwrap_or(0);
        if declared > max {
            return too_large();
        }
        let (parts, body) = req.into_parts();
        let Ok(bytes) = axum::body::to_bytes(body, max.saturating_add(1)).await else {
            return too_large();
        };
        if bytes.len() > max {
            return too_large();
        }
        req = Request::from_parts(parts, Body::from(bytes));
    }
    req.extensions_mut().insert(Cid(cid.clone()));
    let mut r = next.run(req).await;
    if let Ok(v) = HeaderValue::from_str(&cid) {
        r.headers_mut().insert("x-correlation-id", v);
    }
    r
}

/// The app over one shared state.
pub fn router(state: Arc<AppState>) -> Router {
    Router::new()
        .route("/healthz", get(healthz))
        .route("/auth/config", get(auth_config))
        .route("/auth/login", post(auth_login))
        .route("/auth/logout", post(auth_logout))
        .route("/auth/register", post(auth_register))
        .route("/auth/me", get(auth_me))
        .route("/auth/password", post(auth_password))
        .merge(crate::admin::routes())
        .merge(crate::construction::routes())
        .merge(crate::twin::routes())
        .merge(crate::world_routes::routes())
        .fallback(no_route)
        .method_not_allowed_fallback(no_route)
        .layer(DefaultBodyLimit::disable())
        .layer(middleware::from_fn(security_headers))
        .layer(middleware::from_fn(cache_control))
        .layer(middleware::from_fn_with_state(state.clone(), correlate))
        .with_state(state)
}
