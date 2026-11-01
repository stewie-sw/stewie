//! The server's cross-cutting services (RW-55a2a; Python `stewie.server.services`): the append-only audit ledger
//! at `data_dir/events.jsonl` (locked, fsync'd, rotated past a size cap, secrets redacted), the fail-closed
//! critical path for accountable actions (AR-004), and the visible health of the ledger and of the session
//! revocation store. A failed plain event degrades health and returns; a failed critical event refuses the action.

use std::path::PathBuf;
use std::sync::Mutex;
use std::sync::atomic::{AtomicU64, Ordering};

use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};

use crate::{Clock, Entropy};

/// The live ledger rolls over past this many bytes unless configured otherwise.
pub const AUDIT_DEFAULT_MAX_BYTES: u64 = 16 * 1024 * 1024;

/// Field names whose values never reach the ledger.
const REDACT_KEYS: [&str; 15] = [
    "password",
    "passwd",
    "pass",
    "token",
    "api_key",
    "apikey",
    "key",
    "secret",
    "authorization",
    "auth",
    "csrf",
    "private_key",
    "privatekey",
    "cookie",
    "session",
];

/// The accountable actions (AR-004): an action starting with one of these is recorded before it takes effect,
/// or refused. The rover-command route emits `rc.<kind>`, so the actuation events are the kind names.
pub const CRITICAL_ACTION_PREFIXES: [&str; 13] = [
    "rc.goto",
    "rc.command",
    "rc.safe",
    "rc.estop",
    "rc.setsim",
    "rc.rearm",
    "rc.teleop_grant",
    "executive.release",
    "executive.advance",
    "operator.",
    "admin.",
    "release.",
    "twin.publish",
];

/// Is `action` accountable (recorded first or refused)?
#[must_use]
pub fn is_critical_action(action: &str) -> bool {
    CRITICAL_ACTION_PREFIXES
        .iter()
        .any(|p| action.starts_with(p))
}

/// Mask every value held under a secret-like key, recursively; everything else passes through.
#[must_use]
pub fn redact(v: &Value) -> Value {
    match v {
        Value::Object(m) => Value::Object(
            m.iter()
                .map(|(k, x)| {
                    let masked = REDACT_KEYS.contains(&k.to_lowercase().as_str());
                    (
                        k.clone(),
                        if masked {
                            json!("[redacted]")
                        } else {
                            redact(x)
                        },
                    )
                })
                .collect(),
        ),
        Value::Array(a) => Value::Array(a.iter().map(redact).collect()),
        other => other.clone(),
    }
}

/// A short, order-insensitive fingerprint of a payload: the first 16 hex digits of the sha256 of its sorted,
/// compact JSON (the Python's, byte for byte), so the ledger records what flowed without storing it.
#[must_use]
pub fn hash_payload(v: &Value) -> String {
    let canon = stewie_twin::pyjson::dumps_compact(v).unwrap_or_else(|_| v.to_string());
    Sha256::digest(canon.as_bytes())
        .iter()
        .take(8)
        .fold(String::new(), |mut s, b| {
            use std::fmt::Write as _;
            let _ = write!(s, "{b:02x}");
            s
        })
}

/// A degraded flag with its failure count and last error, as `/healthz` reports it.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Health {
    pub degraded: bool,
    pub failures: u64,
    pub last_error: Option<String>,
}

impl Health {
    fn fail(&mut self, err: &str) {
        self.degraded = true;
        self.failures += 1;
        self.last_error = Some(err.to_owned());
    }

    #[must_use]
    pub fn to_json(&self) -> Value {
        json!({"degraded": self.degraded, "failures": self.failures, "last_error": self.last_error})
    }
}

/// A critical action whose audit record could not be durably written: the action must not happen.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AuditWriteRefused(pub String);

impl std::fmt::Display for AuditWriteRefused {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for AuditWriteRefused {}

/// The audit ledger of one data directory, with the process's ledger and revocation health.
pub struct Ledger<'a> {
    pub data_dir: PathBuf,
    max_bytes: AtomicU64,
    clock: &'a dyn Clock,
    lock: Mutex<()>,
    audit: Mutex<Health>,
    revocation: Mutex<Health>,
}

impl std::fmt::Debug for Ledger<'_> {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Ledger")
            .field("data_dir", &self.data_dir)
            .finish_non_exhaustive()
    }
}

fn locked<T>(m: &Mutex<T>) -> std::sync::MutexGuard<'_, T> {
    m.lock().unwrap_or_else(std::sync::PoisonError::into_inner)
}

impl<'a> Ledger<'a> {
    #[must_use]
    pub fn new(data_dir: PathBuf, max_bytes: u64, clock: &'a dyn Clock) -> Self {
        Self {
            data_dir,
            max_bytes: AtomicU64::new(max_bytes),
            clock,
            lock: Mutex::new(()),
            audit: Mutex::new(Health::default()),
            revocation: Mutex::new(Health::default()),
        }
    }

    /// Change the rotation cap at run time (the Python re-reads `STEWIE_AUDIT_MAX_BYTES` on every append).
    pub fn set_max_bytes(&self, n: u64) {
        self.max_bytes.store(n, Ordering::Relaxed);
    }

    /// The live ledger's path.
    #[must_use]
    pub fn path(&self) -> PathBuf {
        self.data_dir.join("events.jsonl")
    }

    #[must_use]
    pub fn audit_health(&self) -> Health {
        locked(&self.audit).clone()
    }

    #[must_use]
    pub fn revocation_health(&self) -> Health {
        locked(&self.revocation).clone()
    }

    /// One record: ts (ms precision), actor, action, target, the critical flag, the correlation id, then the
    /// redacted fields (a field named like a record key overrides it).
    fn record(
        &self,
        actor: &str,
        action: &str,
        target: &str,
        critical: bool,
        cid: Option<&str>,
        fields: &Map<String, Value>,
    ) -> String {
        let mut rec = Map::new();
        rec.insert(
            "ts".into(),
            json!((self.clock.now() * 1000.0).round() / 1000.0),
        );
        rec.insert("actor".into(), json!(actor));
        rec.insert("action".into(), json!(action));
        rec.insert("target".into(), json!(target));
        if critical {
            rec.insert("critical".into(), json!(true));
        }
        if let Some(c) = cid {
            rec.insert("correlation_id".into(), json!(c));
        }
        if let Value::Object(f) = redact(&Value::Object(fields.clone())) {
            rec.extend(f);
        }
        format!("{}\n", Value::Object(rec))
    }

    /// Rotate past the cap, append, flush and fsync, under the ledger lock.
    fn append(&self, line: &str) -> std::io::Result<()> {
        use std::io::Write as _;
        let _g = locked(&self.lock);
        let path = self.path();
        std::fs::create_dir_all(&self.data_dir)?;
        if path.exists()
            && std::fs::metadata(&path)?.len() >= self.max_bytes.load(Ordering::Relaxed)
        {
            // the rolled file is named by the millisecond, as the Python's int(time.time() * 1000)
            #[allow(clippy::cast_possible_truncation)]
            let ms = (self.clock.now() * 1000.0) as i64;
            std::fs::rename(&path, PathBuf::from(format!("{}.{ms}", path.display())))?;
        }
        let mut f = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&path)?;
        f.write_all(line.as_bytes())?;
        f.flush()?;
        f.sync_all()
    }

    fn audit_failed(&self, e: &std::io::Error) {
        locked(&self.audit).fail(&e.to_string());
        eprintln!(
            "S-10 ALERT: audit ledger write FAILED (security events are not being recorded): {e}"
        );
    }

    /// Record an event. A write failure degrades the ledger's health visibly and never fails the caller.
    pub fn log_event(
        &self,
        actor: &str,
        action: &str,
        target: &str,
        cid: Option<&str>,
        fields: &Map<String, Value>,
    ) {
        let line = self.record(actor, action, target, false, cid, fields);
        if let Err(e) = self.append(&line) {
            self.audit_failed(&e);
        }
    }

    /// Record an accountable action before it takes effect.
    ///
    /// # Errors
    /// The record could not be durably written: the caller must not perform the action.
    pub fn critical_event(
        &self,
        actor: &str,
        action: &str,
        target: &str,
        cid: Option<&str>,
        fields: &Map<String, Value>,
    ) -> Result<(), AuditWriteRefused> {
        let line = self.record(actor, action, target, true, cid, fields);
        self.append(&line).map_err(|e| {
            self.audit_failed(&e);
            AuditWriteRefused(format!(
                "critical action {action:?} refused: its audit record could not be durably written ({e})"
            ))
        })
    }

    /// The revocation store could not be read, so tokens are being denied: degrade, alert and audit it.
    pub fn record_revocation_failure(&self, err: &str) {
        locked(&self.revocation).fail(err);
        eprintln!(
            "SEC-02 ALERT: session revocation store UNREADABLE -- denying tokens (fail closed): {err}"
        );
        self.log_event("system", "revocation.read_failed", err, None, &Map::new());
    }
}

/// A fresh, unguessable correlation id for one request (16 hex digits).
#[must_use]
pub fn new_correlation_id(entropy: &dyn Entropy) -> String {
    let mut b = [0_u8; 8];
    entropy.fill(&mut b);
    b.iter().fold(String::new(), |mut s, x| {
        use std::fmt::Write as _;
        let _ = write!(s, "{x:02x}");
        s
    })
}

/// A fixed-window counter keyed by an arbitrary string (IP, account, identity): `max_hits` units per `window_s`;
/// a request costing more than what is left is refused (HTTP 429) and spends nothing. Process-local, as the
/// deployment runs one server process.
#[derive(Debug)]
pub struct RateLimiter {
    pub max_hits: i64,
    pub window_s: f64,
    buckets: Mutex<std::collections::HashMap<String, (f64, i64)>>,
}

impl RateLimiter {
    #[must_use]
    pub fn new(max_hits: i64, window_s: f64) -> Self {
        Self {
            max_hits,
            window_s,
            buckets: Mutex::new(std::collections::HashMap::new()),
        }
    }

    /// Spend `cost` units (at least one) for `key` at monotonic time `now`; false when the window's cap would be
    /// exceeded.
    pub fn allow(&self, key: &str, now: f64, cost: i64) -> bool {
        let c = cost.max(1);
        let mut b = locked(&self.buckets);
        let (mut start, mut count) = b.get(key).copied().unwrap_or((now, 0));
        if now - start >= self.window_s {
            (start, count) = (now, 0);
        }
        if count + c > self.max_hits {
            b.insert(key.to_owned(), (start, count));
            return false;
        }
        b.insert(key.to_owned(), (start, count + c));
        // bounded memory under churned keys
        if b.len() > 4096 {
            let w = self.window_s;
            b.retain(|_, (s, _)| now - *s < w);
        }
        true
    }

    /// Forget one key, or every key.
    pub fn reset(&self, key: Option<&str>) {
        let mut b = locked(&self.buckets);
        match key {
            Some(k) => {
                b.remove(k);
            }
            None => b.clear(),
        }
    }
}
