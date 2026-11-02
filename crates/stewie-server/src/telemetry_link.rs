//! The mission-link constraint model (RW-55b26a; Python `stewie.bridge.telemetry`): what an operator-trainee
//! receives is only what survives a token-bucket downlink rate, a per-sol byte budget (what does not fit is
//! stranded, counted and named), seeded packet drop (numpy's generator, draw for draw), and the downlink
//! latency. Profiles are the packaged JSON budgets (`ideal`, `mission_default`, `comm_dropout`).

use serde_json::{Map, Value, json};
use stewie_twin::pcg64::Pcg64;

/// The packaged link budgets, by name.
const PROFILES: [(&str, &str); 3] = [
    (
        "ideal",
        include_str!("../../../stewie/bridge/profiles/ideal.json"),
    ),
    (
        "mission_default",
        include_str!("../../../stewie/bridge/profiles/mission_default.json"),
    ),
    (
        "comm_dropout",
        include_str!("../../../stewie/bridge/profiles/comm_dropout.json"),
    ),
];

const ALLOWED: [&str; 8] = [
    "downlink_kbps",
    "uplink_latency_ms",
    "downlink_latency_ms",
    "drop_prob",
    "camera_fps",
    "camera_max_bytes",
    "budget_bytes_per_sol",
    "provenance",
];

/// One mission link budget; an absent rate or budget is unconstrained.
#[derive(Debug, Clone, PartialEq)]
pub struct LinkProfile {
    pub downlink_kbps: Option<f64>,
    pub downlink_latency_ms: f64,
    pub budget_bytes_per_sol: Option<i64>,
    pub drop_prob: f64,
}

/// A packaged profile by name (Python `load_profile(profiles/<name>.json)`).
///
/// # Errors
/// No packaged profile of that name (the Python reads any file path; this server serves the packaged ones,
/// D-R173), a key the schema does not know, or a value out of its domain.
pub fn load_profile(name: &str) -> Result<LinkProfile, String> {
    let text = PROFILES
        .iter()
        .find(|(n, _)| *n == name)
        .map(|(_, t)| *t)
        .ok_or_else(|| {
            format!("unknown link profile {name:?} (known: ideal, mission_default, comm_dropout)")
        })?;
    let doc: Map<String, Value> = serde_json::from_str(text).map_err(|e| e.to_string())?;
    let mut unknown: Vec<&String> = doc
        .keys()
        .filter(|k| !ALLOWED.contains(&k.as_str()))
        .collect();
    unknown.sort();
    if !unknown.is_empty() {
        return Err(format!(
            "unknown link-profile keys {unknown:?} in {name}.json"
        ));
    }
    let f = |k: &str| doc.get(k).and_then(Value::as_f64);
    let p = LinkProfile {
        downlink_kbps: f("downlink_kbps"),
        downlink_latency_ms: f("downlink_latency_ms").unwrap_or(0.0),
        budget_bytes_per_sol: doc.get("budget_bytes_per_sol").and_then(Value::as_i64),
        drop_prob: f("drop_prob").unwrap_or(0.0),
    };
    if p.downlink_kbps.is_some_and(|k| k <= 0.0) {
        return Err("downlink_kbps must be > 0 or None".to_owned());
    }
    if !(0.0..1.0).contains(&p.drop_prob) {
        return Err("drop_prob must be in [0, 1)".to_owned());
    }
    Ok(p)
}

/// The per-session link simulator (Python `TelemetryLink`).
#[derive(Debug, Clone)]
pub struct TelemetryLink {
    pub profile: LinkProfile,
    rng: Pcg64,
    tokens: f64,
    last_t: Option<f64>,
    sol_spent: i64,
    pub sent: u64,
    pub dropped: u64,
    pub rate_limited: u64,
    pub bytes_delivered: u64,
    pub stranded: Vec<(String, i64, f64)>,
}

impl TelemetryLink {
    /// A link on `profile` drawing its drops from `default_rng(seed)`; its bucket starts with one second of rate.
    #[must_use]
    pub fn new(profile: LinkProfile, seed: u128) -> Self {
        let tokens = profile.downlink_kbps.map_or(0.0, |k| k * 125.0);
        Self {
            profile,
            rng: Pcg64::new(seed),
            tokens,
            last_t: None,
            sol_spent: 0,
            sent: 0,
            dropped: 0,
            rate_limited: 0,
            bytes_delivered: 0,
            stranded: Vec::new(),
        }
    }

    fn refill(&mut self, t_s: f64) {
        let Some(kbps) = self.profile.downlink_kbps else {
            return;
        };
        let cap = kbps * 125.0;
        if let Some(last) = self.last_t
            && t_s > last
        {
            self.tokens = cap.min(self.tokens + (t_s - last) * cap);
        }
        self.last_t = Some(self.last_t.map_or(t_s, |l| l.max(t_s)));
    }

    /// Downlink one packet: rate, then drop; true when delivered.
    #[allow(clippy::cast_precision_loss)] // a packet size
    pub fn try_send(&mut self, payload_bytes: i64, t_s: f64) -> bool {
        self.refill(t_s);
        if self.profile.downlink_kbps.is_some() && payload_bytes as f64 > self.tokens {
            self.rate_limited += 1;
            return false;
        }
        if self.profile.drop_prob > 0.0 && self.rng.random() < self.profile.drop_prob {
            self.dropped += 1;
            return false;
        }
        if self.profile.downlink_kbps.is_some() {
            self.tokens -= payload_bytes as f64;
        }
        self.sent += 1;
        self.bytes_delivered += u64::try_from(payload_bytes).unwrap_or(0);
        true
    }

    /// When a packet sent at `t_s` becomes operator-visible (`t_s` plus the downlink latency), or `None` when it
    /// is over the sol budget (stranded), rate-limited or dropped.
    pub fn deliver_at(&mut self, payload_bytes: i64, t_s: f64, name: &str) -> Option<f64> {
        if let Some(budget) = self.profile.budget_bytes_per_sol {
            let remaining = (budget - self.sol_spent).max(0);
            if payload_bytes > remaining {
                self.stranded.push((name.to_owned(), payload_bytes, t_s));
                return None;
            }
        }
        if !self.try_send(payload_bytes, t_s) {
            return None;
        }
        self.sol_spent += payload_bytes;
        Some(t_s + self.profile.downlink_latency_ms / 1000.0)
    }

    /// The counters, in the Python's key order.
    #[must_use]
    pub fn stats(&self) -> Value {
        json!({"sent": self.sent, "dropped": self.dropped, "rate_limited": self.rate_limited,
               "bytes_delivered": self.bytes_delivered, "stranded": self.stranded.len()})
    }

    /// Python `repr(dict(stats))`, in insertion order (the summary prints it).
    #[must_use]
    pub fn stats_repr(&self) -> String {
        format!(
            "{{'sent': {}, 'dropped': {}, 'rate_limited': {}, 'bytes_delivered': {}, 'stranded': {}}}",
            self.sent,
            self.dropped,
            self.rate_limited,
            self.bytes_delivered,
            self.stranded.len()
        )
    }
}
