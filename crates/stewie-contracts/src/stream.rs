//! The versioned command/telemetry stream with its SF-01 safe-stop (Python `stewie.bridge.stream.StreamSession`):
//! each frame carries the protocol version, a sequence number and its send time; the un-acked window back-pressures
//! the sender; a cumulative ack clears it; and a frame left un-acked past the deadline trips a terminal safe-stop.

use std::collections::BTreeMap;

use serde_json::{Value, json};

/// The stream protocol version.
pub const PROTOCOL_VERSION: &str = "1.0";

/// One stream (a fresh one per session: a trip is never reset).
#[derive(Debug, Clone, PartialEq)]
pub struct StreamSession {
    pub window: usize,
    pub ack_deadline_s: f64,
    /// The next sequence number.
    pub seq: i64,
    /// The highest cumulatively acked sequence number.
    pub last_ack: i64,
    /// Frames back-pressure refused.
    pub refused: u64,
    pub tripped: bool,
    sent_t: BTreeMap<i64, f64>,
}

impl StreamSession {
    /// A stream over an un-acked `window` with an ack deadline [s].
    ///
    /// # Errors
    /// A zero window or a non-positive deadline.
    pub fn new(window: usize, ack_deadline_s: f64) -> Result<Self, String> {
        if window < 1 {
            return Err(format!("window must be >= 1 (got {window})"));
        }
        if ack_deadline_s.is_nan() || ack_deadline_s <= 0.0 {
            return Err(format!("ack_deadline_s must be > 0 (got {ack_deadline_s})"));
        }
        Ok(Self {
            window,
            ack_deadline_s,
            seq: 0,
            last_ack: -1,
            refused: 0,
            tripped: false,
            sent_t: BTreeMap::new(),
        })
    }

    /// The framed payload, or `None` when tripped or when the full window refuses it (the caller waits for acks).
    pub fn send(&mut self, payload: Value, now: f64) -> Option<Value> {
        if self.tripped {
            return None;
        }
        if self.sent_t.len() >= self.window {
            self.refused += 1;
            return None;
        }
        let mut f = json!({"v": PROTOCOL_VERSION, "seq": self.seq, "t": now});
        f["payload"] = payload;
        self.sent_t.insert(self.seq, now);
        self.seq += 1;
        Some(f)
    }

    /// The consumer's cumulative ack through `seq` (the link heartbeat).
    pub fn ack(&mut self, seq: i64) {
        if seq <= self.last_ack {
            return;
        }
        self.sent_t.retain(|s, _| *s > seq);
        self.last_ack = seq;
    }

    /// Trip the safe-stop when the oldest un-acked frame is older than the deadline; `true` once tripped (and
    /// thereafter). The caller acts on the first `true` exactly once.
    pub fn tick(&mut self, now: f64) -> bool {
        if self.tripped {
            return true;
        }
        if let Some(oldest) = self.sent_t.values().copied().reduce(f64::min)
            && now - oldest > self.ack_deadline_s
        {
            self.tripped = true;
        }
        self.tripped
    }

    /// Frames sent and not yet acked.
    #[must_use]
    pub fn outstanding(&self) -> usize {
        self.sent_t.len()
    }

    #[must_use]
    pub fn status(&self) -> Value {
        json!({"version": PROTOCOL_VERSION, "seq": self.seq, "last_ack": self.last_ack,
               "outstanding": self.outstanding(), "window": self.window, "refused": self.refused,
               "tripped": self.tripped})
    }
}
