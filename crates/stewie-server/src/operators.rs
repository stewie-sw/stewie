//! The operator-account store (RW-55a1; Python `stewie.server.operators`): one JSON document at
//! `data_dir/operators.json` holding salted PBKDF2-HMAC-SHA256 credentials (never a plaintext), a role on the
//! ladder guest < trainee < operator < director, a status, per-IP failed-login lockouts and the one-time invites
//! (stored as the sha256 of the token only). The file format is the Python's, so the cutover reads the live store.
//!
//! Authority: the store governs only the emails it holds; any other email falls back to the allowlist in
//! [`crate::auth`]. A store that is corrupt, schema-invalid, unreadable, or missing after enrollment fails closed.

use std::path::PathBuf;
use std::sync::Mutex;

use regex::Regex;
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};
use subtle::ConstantTimeEq;

use crate::{Clock, Entropy};

const PBKDF2_ITERS: u32 = 200_000;
const SALT_BYTES: usize = 16;
pub const MIN_PASSWORD_LEN: usize = 10;
const MAX_FAILED: i64 = 5;
const LOCKOUT_S: f64 = 15.0 * 60.0;
/// The role ladder in ascending capability; the index is the rank.
pub const ROLES: [&str; 4] = ["guest", "trainee", "operator", "director"];
const STATUSES: [&str; 3] = ["active", "pending", "revoked"];
const MAX_EMAIL_LEN: usize = 254;
const MAX_LOCAL_LEN: usize = 64;
const INVITE_TOKEN_BYTES: usize = 32;
const MAX_INVITE_TTL_S: f64 = 90.0 * 86400.0;
const MAX_INVITE_USES: i64 = 1000;
const MAX_LOCK_IPS: usize = 64;

/// A role's capability rank; an unknown role ranks below guest so it never satisfies a gate.
#[must_use]
pub fn role_rank(role: Option<&str>) -> i32 {
    role.and_then(|r| ROLES.iter().position(|x| *x == r))
        .map_or(-1, |i| i32::try_from(i).unwrap_or(-1))
}

/// Why a store call failed: the caller's input (the Python's `ValueError`), or a store that cannot be trusted
/// (`AccountStoreError`, fail closed).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum StoreError {
    Invalid(String),
    Store(String),
}

impl std::fmt::Display for StoreError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Invalid(m) => write!(f, "ValueError: {m}"),
            Self::Store(m) => write!(f, "AccountStoreError: {m}"),
        }
    }
}

impl std::error::Error for StoreError {}

impl From<StoreError> for String {
    fn from(e: StoreError) -> Self {
        e.to_string()
    }
}

fn invalid<T>(m: impl Into<String>) -> Result<T, StoreError> {
    Err(StoreError::Invalid(m.into()))
}

/// The account store in one data directory, serialised by its lock.
pub struct Store<'a> {
    pub data_dir: PathBuf,
    pub clock: &'a dyn Clock,
    pub entropy: &'a dyn Entropy,
    lock: Mutex<()>,
}

impl std::fmt::Debug for Store<'_> {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Store")
            .field("data_dir", &self.data_dir)
            .finish_non_exhaustive()
    }
}

fn norm(email: &str) -> String {
    email.trim().to_lowercase()
}

fn hex(b: &[u8]) -> String {
    b.iter().fold(String::new(), |mut s, x| {
        use std::fmt::Write as _;
        let _ = write!(s, "{x:02x}");
        s
    })
}

fn pw_hash(password: &str, salt_hex: &str) -> Result<String, StoreError> {
    let salt = (0..salt_hex.len())
        .step_by(2)
        .map(|i| {
            salt_hex
                .get(i..i + 2)
                .and_then(|h| u8::from_str_radix(h, 16).ok())
        })
        .collect::<Option<Vec<u8>>>()
        .ok_or_else(|| StoreError::Store("a stored salt is not hex".to_owned()))?;
    let mut out = [0_u8; 32];
    pbkdf2::pbkdf2_hmac::<Sha256>(password.as_bytes(), &salt, PBKDF2_ITERS, &mut out);
    Ok(hex(&out))
}

fn same(a: &str, b: &str) -> bool {
    a.as_bytes().ct_eq(b.as_bytes()).into()
}

/// The public record: everything but the hash and salt.
fn public(rec: &Value) -> Value {
    let mut m = rec.as_object().cloned().unwrap_or_default();
    m.remove("pw_hash");
    m.remove("pw_salt");
    Value::Object(m)
}

/// Normalise and strictly validate an operator email: bounded length, no HTML/control/shell metacharacter, and a
/// conservative dot-atom@domain grammar with an alphabetic TLD of two or more letters.
///
/// # Errors
/// The address is not acceptable (the Python's message).
pub fn validate_email(email: &str) -> Result<String, StoreError> {
    static RE: std::sync::LazyLock<Regex> = std::sync::LazyLock::new(|| {
        Regex::new(
            r"^[A-Za-z0-9_%+-]+(?:\.[A-Za-z0-9_%+-]+)*@(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$",
        )
        .expect("the email grammar compiles")
    });
    let e = norm(email);
    let repr = py_repr(email);
    if e.is_empty() || e.chars().count() > MAX_EMAIL_LEN {
        return invalid(format!("{repr} is not a valid email address (length)"));
    }
    if e.chars()
        .any(|c| "<>\"'&;/\\ `".contains(c) || (c as u32) < 0x20)
    {
        return invalid(format!(
            "{repr} is not a valid email address (forbidden character)"
        ));
    }
    if e.split('@').next().unwrap_or("").chars().count() > MAX_LOCAL_LEN {
        return invalid(format!(
            "{repr} is not a valid email address (local part too long)"
        ));
    }
    if !RE.is_match(&e) {
        return invalid(format!("{repr} is not a valid email address"));
    }
    Ok(e)
}

/// Python's `repr` of a printable string (the error messages quote the input with it).
#[must_use]
pub fn py_repr(s: &str) -> String {
    let q = if s.contains('\'') && !s.contains('"') {
        '"'
    } else {
        '\''
    };
    let mut out = String::from(q);
    for c in s.chars() {
        match c {
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if c == q => {
                out.push('\\');
                out.push(c);
            }
            c if (c as u32) < 0x20 || c as u32 == 0x7f => {
                use std::fmt::Write as _;
                let _ = write!(out, "\\x{:02x}", c as u32);
            }
            c => out.push(c),
        }
    }
    out.push(q);
    out
}

fn check_password(password: &str) -> Result<(), StoreError> {
    if password.chars().count() < MIN_PASSWORD_LEN {
        return invalid(format!(
            "password must be at least {MIN_PASSWORD_LEN} characters"
        ));
    }
    Ok(())
}

fn check_role(role: &str) -> Result<(), StoreError> {
    if ROLES.contains(&role) {
        Ok(())
    } else {
        invalid("role must be one of ('guest', 'trainee', 'operator', 'director')")
    }
}

/// Drop expired, non-counting per-IP lockouts and cap the map (the least-locked go first).
fn prune_locks(locks: &mut Map<String, Value>, now: f64) {
    let until = |v: &Value| v["until"].as_f64().unwrap_or(0.0);
    locks.retain(|_, v| !(until(v) <= now && v["n"].as_i64().unwrap_or(0) == 0));
    if locks.len() > MAX_LOCK_IPS {
        let mut by: Vec<(String, f64)> = locks.iter().map(|(k, v)| (k.clone(), until(v))).collect();
        by.sort_by(|a, b| a.1.total_cmp(&b.1));
        for (ip, _) in by.into_iter().take(locks.len() - MAX_LOCK_IPS) {
            locks.remove(&ip);
        }
    }
}

impl<'a> Store<'a> {
    #[must_use]
    pub fn new(data_dir: PathBuf, clock: &'a dyn Clock, entropy: &'a dyn Entropy) -> Self {
        Self {
            data_dir,
            clock,
            entropy,
            lock: Mutex::new(()),
        }
    }

    fn path(&self) -> PathBuf {
        self.data_dir.join("operators.json")
    }

    fn marker(&self) -> PathBuf {
        self.data_dir.join("operators.json.bootstrapped")
    }

    fn guard(&self) -> std::sync::MutexGuard<'_, ()> {
        self.lock
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }

    /// Move a corrupt store aside so no later save overwrites it and its bytes survive for recovery.
    fn quarantine(&self, reason: &str) -> StoreError {
        let p = self.path();
        // integer seconds, as the Python's int(time.time())
        #[allow(clippy::cast_possible_truncation)]
        let dst = PathBuf::from(format!(
            "{}.corrupt.{}",
            p.display(),
            self.clock.now() as i64
        ));
        let moved = std::fs::rename(&p, &dst).map_or_else(
            |e| format!("could NOT be quarantined: {e}"),
            |()| format!("quarantined to {}", dst.display()),
        );
        StoreError::Store(format!(
            "account store {} is corrupt ({reason}); {moved}",
            p.display()
        ))
    }

    /// The store document. No file and no enrollment marker is a clean first run (empty); a missing file after
    /// enrollment, an unreadable file, or one that is not `{"operators": {...}}` fails closed (and a corrupt
    /// readable file is quarantined).
    fn load(&self) -> Result<Value, StoreError> {
        let p = self.path();
        if !p.exists() {
            if self.marker().exists() {
                return Err(StoreError::Store(format!(
                    "account store {} is missing but enrollment was completed (marker present); refusing to \
                     fall back to the env/default allowlist -- restore the store",
                    p.display()
                )));
            }
            return Ok(json!({"version": 1, "operators": {}}));
        }
        let raw = std::fs::read_to_string(&p).map_err(|e| {
            StoreError::Store(format!("account store {} is unreadable: {e}", p.display()))
        })?;
        let d: Value = serde_json::from_str(&raw)
            .map_err(|e| self.quarantine(&format!("invalid JSON: {e}")))?;
        if !d["operators"].is_object() {
            return Err(self.quarantine("schema mismatch (no 'operators' mapping)"));
        }
        Ok(d)
    }

    fn save(&self, data: &Value) -> Result<(), StoreError> {
        let body = serde_json::to_vec_pretty(data).map_err(|e| StoreError::Store(e.to_string()))?;
        crate::atomic_write(&self.path(), &body).map_err(StoreError::Store)?;
        // enrollment happened: a later-missing store is a fault from now on
        let at = json!({"bootstrapped_at": self.clock.now()});
        crate::atomic_write(&self.marker(), at.to_string().as_bytes()).map_err(StoreError::Store)
    }

    fn record(&self, email: &str) -> Result<Option<Value>, StoreError> {
        let _g = self.guard();
        Ok(self.load()?["operators"].get(norm(email)).cloned())
    }

    /// The public record of an account.
    ///
    /// # Errors
    /// An untrustworthy store.
    pub fn get(&self, email: &str) -> Result<Option<Value>, StoreError> {
        Ok(self.record(email)?.as_ref().map(public))
    }

    /// # Errors
    /// An untrustworthy store.
    pub fn exists(&self, email: &str) -> Result<bool, StoreError> {
        Ok(self.record(email)?.is_some())
    }

    /// Does the account have a password set?
    ///
    /// # Errors
    /// An untrustworthy store.
    pub fn has_password(&self, email: &str) -> Result<bool, StoreError> {
        Ok(self
            .record(email)?
            .is_some_and(|r| r["pw_hash"].as_str().is_some_and(|h| !h.is_empty())))
    }

    /// Does the store hold an active record for the email?
    ///
    /// # Errors
    /// An untrustworthy store.
    pub fn is_active(&self, email: &str) -> Result<bool, StoreError> {
        Ok(self.record(email)?.is_some_and(|r| r["status"] == "active"))
    }

    /// The role of an active account (operator when unrecorded), else None.
    ///
    /// # Errors
    /// An untrustworthy store.
    pub fn store_role(&self, email: &str) -> Result<Option<String>, StoreError> {
        Ok(self
            .record(email)?
            .filter(|r| r["status"] == "active")
            .map(|r| r["role"].as_str().unwrap_or("operator").to_owned()))
    }

    /// Every account's public record, by email.
    ///
    /// # Errors
    /// An untrustworthy store.
    pub fn list_all(&self) -> Result<Vec<Value>, StoreError> {
        let _g = self.guard();
        let d = self.load()?;
        let mut out: Vec<Value> = d["operators"]
            .as_object()
            .into_iter()
            .flat_map(|m| m.values().map(public))
            .collect();
        out.sort_by(|a, b| a["email"].as_str().cmp(&b["email"].as_str()));
        Ok(out)
    }

    fn salt(&self) -> String {
        let mut b = [0_u8; SALT_BYTES];
        self.entropy.fill(&mut b);
        hex(&b)
    }

    /// Validate and add an account to `data` (the caller holds the lock and saves).
    #[allow(clippy::too_many_arguments)]
    fn insert_account(
        &self,
        data: &mut Value,
        email: &str,
        password: &str,
        role: &str,
        status: &str,
        by: Option<&str>,
    ) -> Result<String, StoreError> {
        let e = validate_email(email)?;
        check_password(password)?;
        check_role(role)?;
        if !STATUSES.contains(&status) {
            return invalid("status must be one of ('active', 'pending', 'revoked')");
        }
        // the salt is drawn before the duplicate check, as the Python does (the oracle's byte order)
        let salt = self.salt();
        let now = self.clock.now();
        if data["operators"].get(&e).is_some() {
            return invalid(format!("an account for {} already exists", py_repr(&e)));
        }
        let active = status == "active";
        data["operators"][&e] = json!({
            "email": e, "role": role, "status": status, "pw_salt": salt, "pw_hash": pw_hash(password, &salt)?,
            "created_at": now, "approved_at": if active { json!(now) } else { Value::Null },
            "approved_by": if active { json!(by) } else { Value::Null },
            "failed": 0, "locked_until": 0.0, "last_login": null,
        });
        Ok(e)
    }

    /// Create an account (pending by default).
    ///
    /// # Errors
    /// A bad email, a short password, a bad role or status, an existing account, or an untrustworthy store.
    pub fn register(
        &self,
        email: &str,
        password: &str,
        role: &str,
        status: &str,
        by: Option<&str>,
    ) -> Result<Value, StoreError> {
        let _g = self.guard();
        let mut data = self.load()?;
        let e = self.insert_account(&mut data, email, password, role, status, by)?;
        self.save(&data)?;
        Ok(public(&data["operators"][&e]))
    }

    /// An immediately active account (director-created, or bootstrap).
    ///
    /// # Errors
    /// As [`Store::register`].
    pub fn create_active(
        &self,
        email: &str,
        password: &str,
        role: &str,
        by: Option<&str>,
    ) -> Result<Value, StoreError> {
        self.register(email, password, role, "active", by)
    }

    /// Seed the founding director from `STEWIE_BOOTSTRAP_DIRECTOR` / `STEWIE_BOOTSTRAP_PASSWORD` when that
    /// account does not exist and no active director does; the seeded email, else None.
    ///
    /// # Errors
    /// An untrustworthy store.
    pub fn bootstrap_director(
        &self,
        email: &str,
        password: &str,
    ) -> Result<Option<String>, StoreError> {
        let email = norm(email);
        if email.is_empty() || password.is_empty() || self.exists(&email)? {
            return Ok(None);
        }
        if self
            .list_all()?
            .iter()
            .any(|r| r["status"] == "active" && r["role"] == "director")
        {
            return Ok(None);
        }
        match self.create_active(&email, password, "director", Some("bootstrap-env")) {
            Ok(_) => Ok(Some(email)),
            Err(StoreError::Invalid(_)) => Ok(None),
            Err(e) => Err(e),
        }
    }

    /// Mint a one-time invite; the raw token is returned once and only its sha256 is stored. The TTL is clamped
    /// to [1 s, 90 days] and the uses to [1, 1000].
    ///
    /// # Errors
    /// A bad role, or an untrustworthy store.
    pub fn create_invite(
        &self,
        by: &str,
        role: &str,
        ttl_s: f64,
        max_uses: i64,
    ) -> Result<String, StoreError> {
        check_role(role)?;
        let ttl = ttl_s.clamp(1.0, MAX_INVITE_TTL_S);
        let uses = max_uses.clamp(1, MAX_INVITE_USES);
        let mut b = [0_u8; INVITE_TOKEN_BYTES];
        self.entropy.fill(&mut b);
        let token = {
            use base64::Engine as _;
            base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(b)
        };
        let now = self.clock.now();
        let _g = self.guard();
        let mut data = self.load()?;
        if !data["invites"].is_object() {
            data["invites"] = json!({});
        }
        data["invites"][hex(&Sha256::digest(token.as_bytes()))] = json!({"role": role, "by": by, "created_at": now, "expires_at": now + ttl, "max_uses": uses, "uses": 0});
        self.save(&data)?;
        Ok(token)
    }

    /// Redeem an invite: an active account at the invite's role, then the invite is burned. A bad email or weak
    /// password leaves the invite unburned.
    ///
    /// # Errors
    /// An unknown, expired or spent invite, a bad email or password, or an untrustworthy store.
    pub fn redeem_invite(
        &self,
        token: &str,
        email: &str,
        password: &str,
    ) -> Result<Value, StoreError> {
        let th = hex(&Sha256::digest(token.as_bytes()));
        let now = self.clock.now();
        // one lock over check, account and burn, so two redeems cannot both spend the last use
        let _g = self.guard();
        let mut data = self.load()?;
        let Some(inv) = data["invites"].get(&th).cloned() else {
            return invalid("invalid invite");
        };
        if now >= inv["expires_at"].as_f64().unwrap_or(0.0) {
            return invalid("invite expired");
        }
        let max = inv["max_uses"].as_i64().unwrap_or(0);
        let used = inv["uses"].as_i64().unwrap_or(0);
        if used >= max {
            return invalid("invite already used");
        }
        let by = format!("invite:{}", inv["by"].as_str().unwrap_or("?"));
        let role = inv["role"].as_str().unwrap_or("operator");
        let e = self.insert_account(&mut data, email, password, role, "active", Some(&by))?;
        if used + 1 >= max {
            if let Some(m) = data["invites"].as_object_mut() {
                m.remove(&th);
            }
        } else {
            data["invites"][&th]["uses"] = json!(used + 1);
        }
        self.save(&data)?;
        Ok(public(&data["operators"][&e]))
    }

    /// The normalised email iff the account is active, has a password, the password matches, and this client IP
    /// is not locked out for it. Five failures from one IP lock that IP (only) for fifteen minutes; a success
    /// clears that IP's count. No IP shares one bucket.
    ///
    /// # Errors
    /// An untrustworthy store.
    pub fn verify_credentials(
        &self,
        email: &str,
        password: &str,
        client_ip: Option<&str>,
    ) -> Result<Option<String>, StoreError> {
        let e = norm(email);
        let now = self.clock.now();
        let ipk = client_ip
            .filter(|i| !i.is_empty())
            .unwrap_or("_")
            .to_owned();
        let _g = self.guard();
        let mut data = self.load()?;
        let Some(rec) = data["operators"].get_mut(&e) else {
            return Ok(None);
        };
        let Some(hash) = rec["pw_hash"]
            .as_str()
            .filter(|h| !h.is_empty())
            .map(str::to_owned)
        else {
            return Ok(None);
        };
        if rec["status"] != "active" {
            return Ok(None);
        }
        if !rec["fail_by_ip"].is_object() {
            rec["fail_by_ip"] = json!({});
        }
        let salt = rec["pw_salt"].as_str().unwrap_or("").to_owned();
        let Some(locks) = rec["fail_by_ip"].as_object_mut() else {
            return Err(StoreError::Store(format!(
                "{e}: fail_by_ip is not a mapping"
            )));
        };
        prune_locks(locks, now);
        if locks
            .get(&ipk)
            .and_then(|v| v["until"].as_f64())
            .unwrap_or(0.0)
            > now
        {
            return Ok(None);
        }
        if same(&pw_hash(password, &salt)?, &hash) {
            locks.remove(&ipk);
            rec["last_login"] = json!(now);
            self.save(&data)?;
            return Ok(Some(e));
        }
        let ent = locks
            .entry(ipk)
            .or_insert_with(|| json!({"n": 0, "until": 0.0}));
        let n = ent["n"].as_i64().unwrap_or(0) + 1;
        if n >= MAX_FAILED {
            ent["until"] = json!(now + LOCKOUT_S);
            ent["n"] = json!(0);
        } else {
            ent["n"] = json!(n);
        }
        self.save(&data)?;
        Ok(None)
    }

    /// Is this (account, client IP) locked out?
    ///
    /// # Errors
    /// An untrustworthy store.
    pub fn is_locked(&self, email: &str, client_ip: Option<&str>) -> Result<bool, StoreError> {
        let ipk = client_ip.filter(|i| !i.is_empty()).unwrap_or("_");
        Ok(self.record(email)?.is_some_and(|r| {
            r["fail_by_ip"][ipk]["until"].as_f64().unwrap_or(0.0) > self.clock.now()
        }))
    }

    fn mutate(&self, email: &str, f: impl FnOnce(&mut Value)) -> Result<Value, StoreError> {
        let e = norm(email);
        {
            let _g = self.guard();
            let mut data = self.load()?;
            let Some(rec) = data["operators"].get_mut(&e) else {
                return invalid(format!("no account for {}", py_repr(&e)));
            };
            f(rec);
            self.save(&data)?;
        }
        self.get(&e).map(Option::unwrap_or_default)
    }

    /// Activate an account at `role`, clearing every lockout.
    ///
    /// # Errors
    /// A bad role, an unknown account, or an untrustworthy store.
    pub fn approve(&self, email: &str, by: &str, role: &str) -> Result<Value, StoreError> {
        check_role(role)?;
        let now = self.clock.now();
        self.mutate(email, |r| {
            r["status"] = json!("active");
            r["role"] = json!(role);
            r["approved_at"] = json!(now);
            r["approved_by"] = json!(by);
            r["failed"] = json!(0);
            r["locked_until"] = json!(0.0);
            r["fail_by_ip"] = json!({});
        })
    }

    /// # Errors
    /// An unknown account, or an untrustworthy store.
    pub fn revoke(&self, email: &str, by: &str) -> Result<Value, StoreError> {
        self.mutate(email, |r| {
            r["status"] = json!("revoked");
            r["approved_by"] = json!(by);
        })
    }

    /// # Errors
    /// A bad role, an unknown account, or an untrustworthy store.
    pub fn set_role(&self, email: &str, role: &str, by: &str) -> Result<Value, StoreError> {
        check_role(role)?;
        self.mutate(email, |r| {
            r["role"] = json!(role);
            r["approved_by"] = json!(by);
        })
    }

    /// A new salt and hash, clearing every lockout (the caller authorises the change).
    ///
    /// # Errors
    /// A short password, an unknown account, or an untrustworthy store.
    pub fn set_password(&self, email: &str, password: &str) -> Result<Value, StoreError> {
        check_password(password)?;
        let salt = self.salt();
        let h = pw_hash(password, &salt)?;
        self.mutate(email, |r| {
            r["pw_salt"] = json!(salt);
            r["pw_hash"] = json!(h);
            r["failed"] = json!(0);
            r["locked_until"] = json!(0.0);
            r["fail_by_ip"] = json!({});
        })
    }

    /// Does the password match the stored hash (no lockout side effect)?
    ///
    /// # Errors
    /// An untrustworthy store.
    pub fn verify_old_password(&self, email: &str, password: &str) -> Result<bool, StoreError> {
        let Some(rec) = self.record(email)? else {
            return Ok(false);
        };
        let (Some(h), Some(s)) = (
            rec["pw_hash"].as_str().filter(|h| !h.is_empty()),
            rec["pw_salt"].as_str(),
        ) else {
            return Ok(false);
        };
        Ok(same(&pw_hash(password, s)?, h))
    }

    /// # Errors
    /// An untrustworthy store.
    pub fn delete(&self, email: &str) -> Result<bool, StoreError> {
        let e = norm(email);
        let _g = self.guard();
        let mut data = self.load()?;
        let removed = data["operators"]
            .as_object_mut()
            .is_some_and(|m| m.remove(&e).is_some());
        if removed {
            self.save(&data)?;
        }
        Ok(removed)
    }
}
