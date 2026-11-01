//! Operator identity (RW-55a1; Python `stewie.server.auth`): HMAC-SHA256 session tokens that interoperate with the
//! Python's (so live sessions survive the cutover), the durable revocation store, roles, and the trusted-proxy
//! Tailscale identity. Every unreadable store fails closed.
//!
//! Configuration is read once into [`AuthConfig`]. Two departures from the Python (D-R106): there is no dev-open
//! mode (no automation key, no server), and no operator email is compiled in (an unset allowlist admits nobody).

use std::collections::BTreeSet;
use std::net::IpAddr;
use std::path::PathBuf;

use base64::Engine as _;
use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use hmac::{Hmac, Mac};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};

use crate::operators::Store;
use crate::services::Ledger;
use crate::{Clock, Entropy};

/// Session lifetime [s].
pub const TOKEN_TTL_S: f64 = 12.0 * 3600.0;
const TOKEN_ISS: &str = "stewie-auth";
const DEFAULT_AUD: &str = "stewie-cockpit";

/// The auth settings, from the environment (`STEWIE_*`).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AuthConfig {
    /// The automation credential (`STEWIE_API_KEY`); required.
    pub api_key: String,
    /// The session-signing secret; when unset it is derived from the automation key.
    pub session_secret: Option<String>,
    /// The operator allowlist (lower-case); empty admits nobody.
    pub allowed: Vec<String>,
    /// The directors; unset means the whole allowlist.
    pub directors: Option<Vec<String>>,
    /// The scoped public-GIS guest key; empty means no anonymous principal.
    pub gis_anon_key: String,
    pub token_aud: String,
    pub trust_tailscale: bool,
    pub trusted_proxies: Vec<String>,
    /// TLS terminated upstream: a production deployment.
    pub tls_terminated: bool,
    /// The bundled single-user desktop app on loopback.
    pub desktop: bool,
    pub data_dir: PathBuf,
}

fn list(v: &str) -> Vec<String> {
    v.split(',')
        .map(|e| e.trim().to_lowercase())
        .filter(|e| !e.is_empty())
        .collect()
}

impl AuthConfig {
    /// Read the configuration and apply the startup guards: an automation key is required; production
    /// (`STEWIE_TLS_TERMINATED=1`) requires a standalone session secret; trusting the Tailscale header requires a
    /// trusted-proxy allowlist.
    ///
    /// # Errors
    /// The first guard that fails, in words an operator can act on.
    pub fn from_env(get: &dyn Fn(&str) -> Option<String>) -> Result<Self, String> {
        let var = |k: &str| get(k).unwrap_or_default();
        let api_key = var("STEWIE_API_KEY");
        if api_key.is_empty() {
            return Err(
                "STEWIE_API_KEY is not set: the server refuses to start without an automation key \
                        (there is no open mode)"
                    .to_owned(),
            );
        }
        let session_secret = Some(var("STEWIE_SESSION_SECRET")).filter(|s| !s.is_empty());
        let tls_terminated = var("STEWIE_TLS_TERMINATED") == "1";
        if tls_terminated && session_secret.is_none() {
            return Err("production (STEWIE_TLS_TERMINATED=1) requires a standalone STEWIE_SESSION_SECRET: without \
                        it the session-signing key is derived from STEWIE_API_KEY, so rotating the automation key \
                        would silently invalidate all live sessions (BP-03). Set STEWIE_SESSION_SECRET and restart."
                .to_owned());
        }
        let trust_tailscale = var("STEWIE_TRUST_TAILSCALE") == "1";
        let trusted_proxies: Vec<String> = var("STEWIE_TRUSTED_PROXIES")
            .split(',')
            .map(|p| p.trim().to_owned())
            .filter(|p| !p.is_empty())
            .collect();
        if trust_tailscale && trusted_proxies.is_empty() {
            return Err("STEWIE_TRUST_TAILSCALE=1 requires a non-empty STEWIE_TRUSTED_PROXIES allowlist (the proxy \
                        IP/CIDR whose Tailscale-User-Login header is trusted). Refusing to start fail-open (SEC-03)."
                .to_owned());
        }
        let data_dir = get("STEWIE_DATA_DIR").filter(|d| !d.is_empty()).ok_or(
            "STEWIE_DATA_DIR is not set: the account and revocation stores need a data directory",
        )?;
        let directors = Some(var("STEWIE_DIRECTORS"))
            .filter(|d| !d.trim().is_empty())
            .map(|d| list(&d));
        Ok(Self {
            api_key,
            session_secret,
            allowed: list(&var("STEWIE_ALLOWED_OPERATORS")),
            directors,
            gis_anon_key: var("STEWIE_GIS_ANON_KEY"),
            token_aud: Some(var("STEWIE_TOKEN_AUD"))
                .filter(|a| !a.is_empty())
                .unwrap_or_else(|| DEFAULT_AUD.to_owned()),
            trust_tailscale,
            trusted_proxies,
            tls_terminated,
            desktop: var("STEWIE_DESKTOP") == "1",
            data_dir: PathBuf::from(data_dir),
        })
    }

    /// The bytes that sign session tokens: the standalone secret, else a domain-separated derivation of the
    /// automation key (never the key's own bytes).
    #[must_use]
    pub fn signing_secret(&self) -> Vec<u8> {
        if let Some(s) = &self.session_secret {
            return s.as_bytes().to_vec();
        }
        let mut h = Sha256::new();
        h.update(b"stewie.session.v1\x00");
        h.update(self.api_key.as_bytes());
        h.finalize().to_vec()
    }
}

/// The session layer over one configuration, account store, clock and entropy source.
pub struct Auth<'a> {
    pub cfg: &'a AuthConfig,
    pub store: &'a Store<'a>,
    pub clock: &'a dyn Clock,
    pub entropy: &'a dyn Entropy,
    /// Where an unreadable revocation store is reported (health, alert, audit line).
    pub ledger: &'a Ledger<'a>,
}

impl std::fmt::Debug for Auth<'_> {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Auth")
            .field("aud", &self.cfg.token_aud)
            .finish_non_exhaustive()
    }
}

fn sign(secret: &[u8], payload: &[u8]) -> Vec<u8> {
    let mut m = Hmac::<Sha256>::new_from_slice(secret).expect("HMAC takes any key length");
    m.update(payload);
    m.finalize().into_bytes().to_vec()
}

/// A token id: 16 random bytes as a version-4 UUID, in hex (the Python's `uuid4().hex`).
fn uuid4_hex(entropy: &dyn Entropy) -> String {
    let mut b = [0_u8; 16];
    entropy.fill(&mut b);
    b[6] = (b[6] & 0x0f) | 0x40;
    b[8] = (b[8] & 0x3f) | 0x80;
    b.iter().fold(String::new(), |mut s, x| {
        use std::fmt::Write as _;
        let _ = write!(s, "{x:02x}");
        s
    })
}

impl Auth<'_> {
    /// Is the email on the allowlist? The account store governs the emails it holds (active is allowed).
    ///
    /// # Errors
    /// An unreadable account store (fail closed).
    pub fn is_allowed(&self, email: &str) -> Result<bool, String> {
        let e = email.trim().to_lowercase();
        if self.store.exists(&e)? {
            return Ok(self.store.is_active(&e)?);
        }
        Ok(self.cfg.allowed.contains(&e))
    }

    /// Mint a session token for `email`: JSON claims (op, exp, iat, iss, aud, jti), compact, signed with the
    /// session secret; both parts unpadded URL-safe base64.
    #[must_use]
    pub fn issue_token(&self, email: &str, ttl_s: Option<f64>) -> String {
        let t = self.clock.now();
        let claims = json!({"op": email.trim().to_lowercase(), "exp": t + ttl_s.unwrap_or(TOKEN_TTL_S), "iat": t,
                            "iss": TOKEN_ISS, "aud": self.cfg.token_aud, "jti": uuid4_hex(self.entropy)});
        // the Python's json.dumps(separators=(",", ":")) in insertion order
        let payload = compact_in_order(&claims, &["op", "exp", "iat", "iss", "aud", "jti"]);
        let sig = sign(&self.cfg.signing_secret(), payload.as_bytes());
        format!(
            "{}.{}",
            URL_SAFE_NO_PAD.encode(&payload),
            URL_SAFE_NO_PAD.encode(sig)
        )
    }

    /// The claims iff the signature verifies (no expiry, audience, revocation or allowlist check).
    #[must_use]
    pub fn decode_claims(&self, token: &str) -> Option<Value> {
        let (p, s) = token.split_once('.')?;
        let unpad = |x: &str| x.trim_end_matches('=').to_owned();
        let payload = URL_SAFE_NO_PAD.decode(unpad(p)).ok()?;
        let sig = URL_SAFE_NO_PAD.decode(unpad(s)).ok()?;
        let mut m = Hmac::<Sha256>::new_from_slice(&self.cfg.signing_secret()).ok()?;
        m.update(&payload);
        m.verify_slice(&sig).ok()?;
        serde_json::from_slice(&payload).ok()
    }

    /// The operator iff the token is signed, unexpired at `now` (the clock when None), issued by us for our
    /// audience, not revoked, and the operator is allowed.
    #[must_use]
    pub fn verify_token(&self, token: &str, now: Option<f64>) -> Option<String> {
        let d = self.decode_claims(token)?;
        let now = now.unwrap_or_else(|| self.clock.now());
        if now > d["exp"].as_f64()? {
            return None;
        }
        if d["iss"] != TOKEN_ISS || d["aud"] != self.cfg.token_aud.as_str() {
            return None;
        }
        if let Some(jti) = d["jti"].as_str().filter(|j| !j.is_empty())
            && self.is_revoked(jti)
        {
            return None;
        }
        let op = d["op"].as_str()?;
        matches!(self.is_allowed(op), Ok(true)).then(|| op.to_owned())
    }

    fn revoked_path(&self) -> PathBuf {
        self.cfg.data_dir.join("revoked_jti.json")
    }

    /// The revoked token ids. No file is the normal empty state; a file that is not a JSON list of strings fails.
    ///
    /// # Errors
    /// An unreadable or malformed store.
    pub fn revoked_set(&self) -> Result<BTreeSet<String>, String> {
        let p = self.revoked_path();
        if !p.exists() {
            return Ok(BTreeSet::new());
        }
        let text =
            std::fs::read_to_string(&p).map_err(|e| format!("revocation store unreadable: {e}"))?;
        let v: Value =
            serde_json::from_str(&text).map_err(|e| format!("revocation store corrupt: {e}"))?;
        v.as_array()
            .ok_or("revocation store is not a JSON list")?
            .iter()
            .map(|x| {
                x.as_str()
                    .map(str::to_owned)
                    .ok_or_else(|| "revocation store holds a non-string".to_owned())
            })
            .collect()
    }

    /// Is `jti` revoked? An unreadable store answers yes (fail closed), and the failure is made visible:
    /// degraded revocation health, an alert, and an audit line.
    #[must_use]
    pub fn is_revoked(&self, jti: &str) -> bool {
        match self.revoked_set() {
            Ok(s) => s.contains(jti),
            Err(e) => {
                self.ledger.record_revocation_failure(&e);
                true
            }
        }
    }

    /// Revoke one session durably, refusing to overwrite an unreadable store.
    ///
    /// # Errors
    /// An unreadable store, or a failed write.
    pub fn revoke_jti(&self, jti: &str) -> Result<(), String> {
        let mut set = self.revoked_set()?;
        set.insert(jti.to_owned());
        let body = serde_json::to_string(&set.into_iter().collect::<Vec<_>>())
            .map_err(|e| e.to_string())?;
        crate::atomic_write(&self.revoked_path(), body.as_bytes())
    }

    /// The role: `director` for automation and the desktop app, `guest` for the public-GIS key, the account
    /// store's role for an active account, else director when named a director (the allowlist when no director
    /// list is set), operator otherwise.
    ///
    /// # Errors
    /// An unreadable account store.
    pub fn role_of(&self, identity: &str) -> Result<String, String> {
        if matches!(identity, "api-key" | "desktop-local") {
            return Ok("director".to_owned());
        }
        if identity == "gis-anon" {
            return Ok("guest".to_owned());
        }
        if let Some(r) = self.store.store_role(identity)? {
            return Ok(r);
        }
        let id = identity.trim().to_lowercase();
        let directors = self.cfg.directors.as_ref().unwrap_or(&self.cfg.allowed);
        Ok(if directors.contains(&id) {
            "director"
        } else {
            "operator"
        }
        .to_owned())
    }

    /// The allowed Tailscale identity, only when trusted and asserted by a trusted proxy peer.
    #[must_use]
    pub fn tailscale_identity(&self, login: &str, peer: Option<&str>) -> Option<String> {
        if !self.cfg.trust_tailscale || !peer_trusted(peer, &self.cfg.trusted_proxies) {
            return None;
        }
        let l = login.trim();
        (!l.is_empty() && matches!(self.is_allowed(l), Ok(true))).then(|| l.to_lowercase())
    }
}

/// Is `peer` in the trusted-proxy list: an exact entry (an IP or a non-IP peer label), or inside a CIDR entry?
#[must_use]
pub fn peer_trusted(peer: Option<&str>, proxies: &[String]) -> bool {
    let Some(peer) = peer else { return false };
    if proxies.iter().any(|p| p == peer) {
        return true;
    }
    let Ok(ip) = peer.parse::<IpAddr>() else {
        return false;
    };
    proxies
        .iter()
        .filter_map(|p| p.split_once('/'))
        .any(
            |(net, len)| match (net.parse::<IpAddr>(), len.parse::<u32>()) {
                (Ok(IpAddr::V4(n)), Ok(l)) if l <= 32 => match ip {
                    IpAddr::V4(a) => {
                        let mask = if l == 0 { 0 } else { u32::MAX << (32 - l) };
                        (u32::from(a) & mask) == (u32::from(n) & mask)
                    }
                    IpAddr::V6(_) => false,
                },
                (Ok(IpAddr::V6(n)), Ok(l)) if l <= 128 => match ip {
                    IpAddr::V6(a) => {
                        let mask = if l == 0 { 0 } else { u128::MAX << (128 - l) };
                        (u128::from(a) & mask) == (u128::from(n) & mask)
                    }
                    IpAddr::V4(_) => false,
                },
                _ => false,
            },
        )
}

/// Compact JSON of an object's `keys` in that order (the Python's insertion order), values as Python writes them.
fn compact_in_order(v: &Value, keys: &[&str]) -> String {
    let parts: Vec<String> = keys
        .iter()
        .map(|k| {
            let val = stewie_twin::pyjson::dumps(&v[*k]).unwrap_or_default();
            format!("{}:{val}", serde_json::to_string(k).unwrap_or_default())
        })
        .collect();
    format!("{{{}}}", parts.join(","))
}
