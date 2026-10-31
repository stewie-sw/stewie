//! The hash-chained world-transaction log (Python `stewie.twin.envelope.TransactionLog`, DT-01).
//!
//! Each record links the four world-state source identities (conserved authority, observed twin, plan,
//! belief) with a stamp (mission, site, body, time, provenance, uncertainty). `world_sha` hashes all of
//! them; `chain_hash` = sha256(previous chain hash + the record without its own chain hash). A durable log
//! appends and fsyncs **before** acknowledging, so memory is never ahead of disk. Replay re-derives every
//! hash and refuses any mismatch before applying the record.

use std::path::{Path, PathBuf};

use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};

use crate::{TwinError, journal, pyjson};

/// One linked world-state record. An empty `packet_sha` or `vehicle_sha` means "not linked" and is left
/// out of both hashes (so records written before those links existed still verify).
#[derive(Debug, Clone, PartialEq)]
pub struct WorldTransaction {
    pub seq: u64,
    pub authority_sha: String,
    pub twin_version: i64,
    pub twin_hash: String,
    pub plan_id: String,
    pub belief: Map<String, Value>,
    pub mission: String,
    pub site: String,
    pub body: String,
    pub mission_t_s: f64,
    pub provenance: String,
    pub uncertainty_m: f64,
    pub world_sha: String,
    pub prev_hash: String,
    pub chain_hash: String,
    pub packet_sha: String,
    pub vehicle_sha: String,
}

/// The identities and stamp a commit links.
#[derive(Debug, Clone, PartialEq)]
pub struct Snapshot {
    pub authority_sha: String,
    pub twin_version: i64,
    pub twin_hash: String,
    pub plan_id: String,
    pub belief: Map<String, Value>,
    pub mission: String,
    pub site: String,
    pub body: String,
    pub mission_t_s: f64,
    pub provenance: String,
    pub uncertainty_m: f64,
    pub packet_sha: String,
    pub vehicle_sha: String,
}

fn sha256_hex(parts: &[&[u8]]) -> String {
    let mut h = Sha256::new();
    for p in parts {
        h.update(p);
    }
    h.finalize().iter().fold(String::new(), |mut s, b| {
        use std::fmt::Write as _;
        let _ = write!(s, "{b:02x}");
        s
    })
}

fn world_sha(s: &Snapshot) -> Result<String, TwinError> {
    let mut p = json!({
        "authority_sha": s.authority_sha,
        "twin_version": s.twin_version,
        "twin_hash": s.twin_hash,
        "plan_id": s.plan_id,
        "belief": s.belief,
        "mission": s.mission,
        "site": s.site,
        "body": s.body,
        "mission_t_s": s.mission_t_s,
        "provenance": s.provenance,
        "uncertainty_m": s.uncertainty_m,
    });
    if !s.packet_sha.is_empty() {
        p["packet_sha"] = json!(s.packet_sha);
    }
    if !s.vehicle_sha.is_empty() {
        p["vehicle_sha"] = json!(s.vehicle_sha);
    }
    Ok(sha256_hex(&[pyjson::dumps(&p)?.as_bytes()]))
}

impl WorldTransaction {
    /// The full record as journalled (every field, chain hash included).
    #[must_use]
    pub fn record(&self) -> Value {
        json!({
            "seq": self.seq,
            "authority_sha": self.authority_sha,
            "twin_version": self.twin_version,
            "twin_hash": self.twin_hash,
            "plan_id": self.plan_id,
            "belief": self.belief,
            "mission": self.mission,
            "site": self.site,
            "body": self.body,
            "mission_t_s": self.mission_t_s,
            "provenance": self.provenance,
            "uncertainty_m": self.uncertainty_m,
            "world_sha": self.world_sha,
            "prev_hash": self.prev_hash,
            "chain_hash": self.chain_hash,
            "packet_sha": self.packet_sha,
            "vehicle_sha": self.vehicle_sha,
        })
    }

    /// What the chain hash commits to: the record without its chain hash or unlinked identities.
    fn linked_body(&self) -> Value {
        let mut b = self.record();
        let m = b.as_object_mut().expect("record is an object");
        m.remove("chain_hash");
        for k in ["packet_sha", "vehicle_sha"] {
            if m.get(k).and_then(Value::as_str).is_some_and(str::is_empty) {
                m.remove(k);
            }
        }
        b
    }

    fn snapshot(&self) -> Snapshot {
        Snapshot {
            authority_sha: self.authority_sha.clone(),
            twin_version: self.twin_version,
            twin_hash: self.twin_hash.clone(),
            plan_id: self.plan_id.clone(),
            belief: self.belief.clone(),
            mission: self.mission.clone(),
            site: self.site.clone(),
            body: self.body.clone(),
            mission_t_s: self.mission_t_s,
            provenance: self.provenance.clone(),
            uncertainty_m: self.uncertainty_m,
            packet_sha: self.packet_sha.clone(),
            vehicle_sha: self.vehicle_sha.clone(),
        }
    }
}

fn chain_hash(body: &Value, prev: &str) -> Result<String, TwinError> {
    Ok(sha256_hex(&[
        prev.as_bytes(),
        pyjson::dumps(body)?.as_bytes(),
    ]))
}

/// Append-only, hash-chained log; durable when it has a journal path.
#[derive(Debug, Default)]
pub struct TransactionLog {
    journal: Option<PathBuf>,
    transactions: Vec<WorldTransaction>,
}

impl TransactionLog {
    /// A volatile log (no journal).
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Cold-restore from the journal alone: every record replays through the commit path with its hashes
    /// re-derived and checked first; a torn tail is dropped and repaired; future commits journal again.
    ///
    /// # Errors
    /// I/O failure, interior corruption, or any record whose hashes or links do not re-derive.
    pub fn from_journal(path: &Path) -> Result<Self, TwinError> {
        let mut log = Self::new();
        journal::replay(path, "world journal", |rec| {
            let s = |k: &str| {
                rec.get(k)
                    .and_then(Value::as_str)
                    .map(str::to_owned)
                    .ok_or_else(|| TwinError::Invalid(format!("record lacks {k}")))
            };
            let num = |k: &str, default: Option<f64>| {
                rec.get(k)
                    .and_then(Value::as_f64)
                    .or(default)
                    .ok_or_else(|| TwinError::Invalid(format!("record lacks {k}")))
            };
            let opt = |k: &str| rec.get(k).and_then(Value::as_str).unwrap_or("").to_owned();
            let snap = Snapshot {
                authority_sha: s("authority_sha")?,
                twin_version: rec
                    .get("twin_version")
                    .and_then(Value::as_i64)
                    .ok_or_else(|| TwinError::Invalid("record lacks twin_version".into()))?,
                twin_hash: s("twin_hash")?,
                plan_id: s("plan_id")?,
                belief: rec
                    .get("belief")
                    .and_then(Value::as_object)
                    .cloned()
                    .ok_or_else(|| TwinError::Invalid("record lacks belief".into()))?,
                mission: s("mission")?,
                site: s("site")?,
                body: s("body")?,
                mission_t_s: num("mission_t_s", None)?,
                provenance: s("provenance")?,
                uncertainty_m: num("uncertainty_m", Some(0.0))?,
                packet_sha: opt("packet_sha"),
                vehicle_sha: opt("vehicle_sha"),
            };
            let txn = log.append(snap, Some(&s("chain_hash")?))?;
            let same = rec.get("seq").and_then(Value::as_u64) == Some(txn.seq)
                && rec.get("prev_hash").and_then(Value::as_str) == Some(txn.prev_hash.as_str())
                && rec.get("world_sha").and_then(Value::as_str) == Some(txn.world_sha.as_str());
            if same {
                Ok(())
            } else {
                Err(TwinError::Tampered(format!("seq {}", txn.seq)))
            }
        })?;
        log.journal = Some(path.to_path_buf());
        Ok(log)
    }

    /// Link, hash-chain, durably journal (if journalling) and append a snapshot.
    ///
    /// # Errors
    /// Empty provenance, a non-finite stamp, or an I/O failure (then nothing is appended in memory).
    pub fn commit(&mut self, snap: Snapshot) -> Result<&WorldTransaction, TwinError> {
        if snap.provenance.trim().is_empty() {
            return Err(TwinError::Invalid(
                "every world transaction requires non-empty provenance".into(),
            ));
        }
        self.append(snap, None)
    }

    fn append(
        &mut self,
        snap: Snapshot,
        expected_chain: Option<&str>,
    ) -> Result<&WorldTransaction, TwinError> {
        let prev = self
            .transactions
            .last()
            .map_or_else(|| "genesis".to_owned(), |t| t.chain_hash.clone());
        let w = world_sha(&snap)?;
        let mut txn = WorldTransaction {
            seq: self.transactions.len() as u64,
            authority_sha: snap.authority_sha,
            twin_version: snap.twin_version,
            twin_hash: snap.twin_hash,
            plan_id: snap.plan_id,
            belief: snap.belief,
            mission: snap.mission,
            site: snap.site,
            body: snap.body,
            mission_t_s: snap.mission_t_s,
            provenance: snap.provenance,
            uncertainty_m: snap.uncertainty_m,
            world_sha: w,
            prev_hash: prev.clone(),
            chain_hash: String::new(),
            packet_sha: snap.packet_sha,
            vehicle_sha: snap.vehicle_sha,
        };
        txn.chain_hash = chain_hash(&txn.linked_body(), &prev)?;
        if expected_chain.is_some_and(|e| e != txn.chain_hash) {
            return Err(TwinError::Tampered(format!(
                "chain hash at seq {}",
                txn.seq
            )));
        }
        if let Some(p) = &self.journal {
            journal::append(p, &txn.record())?; // durable before acknowledged
        }
        self.transactions.push(txn);
        Ok(self.transactions.last().expect("just pushed"))
    }

    /// The most recent consistent linked record.
    #[must_use]
    pub fn latest(&self) -> Option<&WorldTransaction> {
        self.transactions.last()
    }

    #[must_use]
    pub fn transactions(&self) -> &[WorldTransaction] {
        &self.transactions
    }

    /// Re-derive every world sha, link and chain hash.
    #[must_use]
    pub fn verify_chain(&self) -> bool {
        let mut prev = "genesis".to_owned();
        for t in &self.transactions {
            let ok = world_sha(&t.snapshot()).is_ok_and(|w| w == t.world_sha)
                && t.prev_hash == prev
                && chain_hash(&t.linked_body(), &prev).is_ok_and(|c| c == t.chain_hash);
            if !ok {
                return false;
            }
            prev.clone_from(&t.chain_hash);
        }
        true
    }
}
