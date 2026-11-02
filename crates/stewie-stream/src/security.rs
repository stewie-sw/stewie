//! The guards of the public stream (Python `stewie.stream.security`): a constant-time token gate
//! (`VIZ2_STREAM_TOKEN`; off when unset, as on the tailnet), a live-session cap (`VIZ2_STREAM_MAX_SESSIONS`,
//! default 2) taken before any GPU process is spawned and released when its slot drops, and a per-client sliding
//! window on new connections (`VIZ2_STREAM_MAX_CONN_PER_MIN`, default 20, over 60 s). The environment is read per
//! request, so an override applies at once.
//!
//! The client is the socket peer, unless the peer is this host (cloudflared): then Cloudflare's `CF-Connecting-IP`,
//! else the last `X-Forwarded-For` hop. The Python keyed on the first hop, which a client can write itself, since
//! Cloudflare appends to a forwarded header it is sent (D-R184).

use std::collections::{HashMap, VecDeque};
use std::net::IpAddr;
use std::sync::{Arc, Mutex, PoisonError};
use std::time::Instant;

use subtle::ConstantTimeEq as _;

pub const ENV_TOKEN: &str = "VIZ2_STREAM_TOKEN";
pub const ENV_MAX_SESSIONS: &str = "VIZ2_STREAM_MAX_SESSIONS";
pub const ENV_MAX_CONN_PER_MIN: &str = "VIZ2_STREAM_MAX_CONN_PER_MIN";
pub const DEFAULT_MAX_SESSIONS: usize = 2;
pub const DEFAULT_MAX_CONN_PER_MIN: usize = 20;
pub const RATE_WINDOW_S: f64 = 60.0;

/// WebSocket close codes (the application range): a bad token, too many connections, every GPU slot busy.
pub const WS_CLOSE_UNAUTHORIZED: u16 = 4401;
pub const WS_CLOSE_RATE_LIMITED: u16 = 4429;
pub const WS_CLOSE_AT_CAPACITY: u16 = 4409;

/// The environment, as a lookup (the process environment in the binary, a map in tests).
pub type Env = Arc<dyn Fn(&str) -> Option<String> + Send + Sync>;

/// Paths outside both the token gate and the rate limit: the vendored ES module and the readiness probe.
#[must_use]
pub fn is_exempt(path: &str) -> bool {
    path == "/healthz" || path == "/vendor" || path.starts_with("/vendor/")
}

/// Whether `supplied` is the configured token, compared in constant time; open when none is configured.
#[must_use]
pub fn token_ok(env: &Env, supplied: Option<&str>) -> bool {
    match env(ENV_TOKEN).filter(|t| !t.is_empty()) {
        None => true,
        Some(want) => supplied
            .filter(|s| !s.is_empty())
            .is_some_and(|s| bool::from(s.as_bytes().ct_eq(want.as_bytes()))),
    }
}

/// A positive integer setting (Python `max(1, int(raw))`), else its default.
fn int_env(env: &Env, name: &str, default: usize) -> usize {
    env(name)
        .filter(|r| !r.is_empty())
        .and_then(|r| crate::py::int(&serde_json::Value::String(r)))
        .map_or(default, |n| usize::try_from(n.max(1)).unwrap_or(usize::MAX))
}

#[must_use]
pub fn max_sessions(env: &Env) -> usize {
    int_env(env, ENV_MAX_SESSIONS, DEFAULT_MAX_SESSIONS)
}

#[must_use]
pub fn max_conn_per_min(env: &Env) -> usize {
    int_env(env, ENV_MAX_CONN_PER_MIN, DEFAULT_MAX_CONN_PER_MIN)
}

/// The rate-limit key of a request: see the module note.
#[must_use]
pub fn client_key(peer: Option<IpAddr>, header: impl Fn(&str) -> Option<String>) -> String {
    match peer {
        Some(ip) if ip.is_loopback() => header("cf-connecting-ip")
            .map(|v| v.trim().to_owned())
            .filter(|v| !v.is_empty())
            .or_else(|| {
                header("x-forwarded-for")
                    .and_then(|x| x.rsplit(',').next().map(|h| h.trim().to_owned()))
                    .filter(|v| !v.is_empty())
            })
            .unwrap_or_else(|| ip.to_string()),
        Some(ip) => ip.to_string(),
        None => "-".to_owned(),
    }
}

/// The in-memory sliding-window counter, keyed by client.
#[derive(Debug, Default)]
pub struct Limiter {
    hits: Mutex<HashMap<String, VecDeque<Instant>>>,
}

impl Limiter {
    /// Record a hit at `now`; `false` once `limit` hits already fall within the trailing window.
    pub fn allow(&self, key: &str, limit: usize, now: Instant) -> bool {
        let window = std::time::Duration::from_secs_f64(RATE_WINDOW_S);
        let mut hits = self.hits.lock().unwrap_or_else(PoisonError::into_inner);
        let dq = hits.entry(key.to_owned()).or_default();
        while dq.front().is_some_and(|t| now.duration_since(*t) >= window) {
            dq.pop_front();
        }
        if dq.len() >= limit.max(1) {
            return false;
        }
        dq.push_back(now);
        // churned keys cannot grow the map without bound
        if hits.len() > 4096 {
            hits.retain(|_, dq| dq.back().is_some_and(|t| now.duration_since(*t) < window));
        }
        true
    }
}

/// The live GPU-session counter.
#[derive(Debug, Default)]
pub struct Sessions {
    n: Mutex<usize>,
}

/// A reserved session slot, released when dropped (every teardown path, a panic included).
#[derive(Debug)]
pub struct Slot<'a>(&'a Sessions);

impl Drop for Slot<'_> {
    fn drop(&mut self) {
        let mut n = self.0.n.lock().unwrap_or_else(PoisonError::into_inner);
        *n = n.saturating_sub(1);
    }
}

impl Sessions {
    /// A slot if fewer than `cap` are live.
    pub fn acquire(&self, cap: usize) -> Option<Slot<'_>> {
        let mut n = self.n.lock().unwrap_or_else(PoisonError::into_inner);
        (*n < cap.max(1)).then(|| {
            *n += 1;
            Slot(self)
        })
    }

    #[must_use]
    pub fn count(&self) -> usize {
        *self.n.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn env(pairs: &[(&'static str, &'static str)]) -> Env {
        let m: HashMap<&str, &str> = pairs.iter().copied().collect();
        Arc::new(move |k| m.get(k).map(|v| (*v).to_owned()))
    }

    #[test]
    fn the_token_gate_is_constant_time_and_off_when_unset() {
        assert!(token_ok(&env(&[]), None));
        let e = env(&[(ENV_TOKEN, "s3cret-token")]);
        assert!(token_ok(&e, Some("s3cret-token")));
        assert!(!token_ok(&e, Some("s3cret-tokeN")));
        assert!(!token_ok(&e, Some("")));
        assert!(!token_ok(&e, None));
    }

    #[test]
    fn the_client_is_the_peer_unless_cloudflared_forwards_it() {
        let lo: Option<IpAddr> = Some([127, 0, 0, 1].into());
        let far: Option<IpAddr> = Some([100, 64, 0, 9].into());
        // SYNTHETIC addresses (labelled): a client that writes its own X-Forwarded-For cannot pick its key
        let xff = |h: &str| (h == "x-forwarded-for").then(|| "1.2.3.4, 203.0.113.7".to_owned());
        assert_eq!(client_key(lo, xff), "203.0.113.7");
        assert_eq!(
            client_key(lo, |h| (h == "cf-connecting-ip")
                .then(|| "198.51.100.2".to_owned())),
            "198.51.100.2"
        );
        assert_eq!(client_key(far, xff), "100.64.0.9");
        assert_eq!(client_key(lo, |_| None), "127.0.0.1");
    }

    #[test]
    fn the_window_refuses_past_the_limit_and_slides() {
        let l = Limiter::default();
        let t0 = Instant::now();
        assert!((0..3).all(|_| l.allow("a", 3, t0)));
        assert!(!l.allow("a", 3, t0));
        assert!(l.allow("b", 3, t0), "keys are independent");
        assert!(
            l.allow("a", 3, t0 + std::time::Duration::from_mins(1)),
            "a hit a full window old has expired"
        );
    }

    #[test]
    fn a_slot_is_released_when_dropped() {
        let s = Sessions::default();
        let a = s.acquire(2).unwrap();
        let _b = s.acquire(2).unwrap();
        assert!(s.acquire(2).is_none(), "at capacity");
        drop(a);
        assert_eq!(s.count(), 1);
        assert!(s.acquire(2).is_some());
    }
}
