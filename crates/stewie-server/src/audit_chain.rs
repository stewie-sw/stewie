//! The EG-07 executive audit chain, read side (RW-55b19; Python `stewie.contracts.audit.AuditLog` over
//! `server.audit_log.journal_path`): the hash-chained who/what/when/where/mode/reason/before/after/evidence records of
//! every authority action, reloaded from `data_dir/audit/executive_chain.jsonl` under its sidecar lock, checked
//! against the `.head.json` anchor (a regressed or truncated journal is detected), and verified link by link. An
//! empty chain attests nothing (`None`), never "verified".

use std::fs::File;
use std::io::Write as _;
use std::path::{Path, PathBuf};

use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};

const GENESIS_HASH: &str = "0000000000000000000000000000000000000000000000000000000000000000";
const FIELDS: [&str; 9] = [
    "actor",
    "action",
    "timestamp",
    "location",
    "mode",
    "reason",
    "before_state",
    "after_state",
    "evidence",
];
const ANCHOR_SCHEMA: &str = "stewie.audit-head/v1";

/// The executive chain's journal under `data_dir`.
#[must_use]
pub fn journal_path(data_dir: &Path) -> PathBuf {
    data_dir.join("audit").join("executive_chain.jsonl")
}

/// A loaded chain: its records (each the Python's `asdict(AuditRecord)`) and why it could not be trusted, if so.
#[derive(Debug, Clone, Default)]
pub struct Chain {
    pub records: Vec<Map<String, Value>>,
    pub load_error: Option<String>,
}

fn text(r: &Map<String, Value>, k: &str) -> String {
    r.get(k).and_then(Value::as_str).unwrap_or("").to_owned()
}

/// The record hash: SHA-256 over the sorted JSON of the predecessor's hash and the nine fields.
fn digest(r: &Map<String, Value>, prev: &str) -> String {
    let mut m = Map::new();
    m.insert("prev_hash".into(), json!(prev));
    for k in FIELDS {
        m.insert(k.into(), r.get(k).cloned().unwrap_or(Value::Null));
    }
    let text = stewie_twin::pyjson::dumps(&Value::Object(m)).unwrap_or_default();
    Sha256::digest(text.as_bytes())
        .iter()
        .fold(String::new(), |mut s, b| {
            use std::fmt::Write as _;
            let _ = write!(s, "{b:02x}");
            s
        })
}

/// Python `verify_chain`: every record links to its predecessor and its stored hash is its fields' digest.
#[must_use]
pub fn verify_chain(records: &[Map<String, Value>]) -> bool {
    let mut prev = GENESIS_HASH.to_owned();
    for r in records {
        if text(r, "prev_hash") != prev || digest(r, &prev) != text(r, "record_hash") {
            return false;
        }
        prev = text(r, "record_hash");
    }
    true
}

/// The anchor `(count, head hash)`, or why it is unreadable.
fn read_anchor(path: &Path) -> Result<Option<(usize, String)>, String> {
    let Ok(t) = std::fs::read_to_string(path) else {
        return Ok(None);
    };
    let a: Value =
        serde_json::from_str(&t).map_err(|e| format!("ValueError({:?})", e.to_string()))?;
    if a.get("schema").and_then(Value::as_str) != Some(ANCHOR_SCHEMA) {
        return Err("ValueError('invalid audit-head schema')".to_owned());
    }
    let (Some(count), Some(head)) = (a["count"].as_u64(), a["record_hash"].as_str()) else {
        return Err("ValueError('invalid audit-head fields')".to_owned());
    };
    if head.len() != 64 {
        return Err("ValueError('invalid audit-head record_hash')".to_owned());
    }
    #[allow(clippy::cast_possible_truncation)] // a record count
    Ok(Some((count as usize, head.to_owned())))
}

/// Load the chain under the journal's sidecar lock, then (as the Python's `_ensure_anchor`) advance the anchor to a
/// valid chain's head when it lags. A malformed line stops the load and marks the chain unreadable.
#[must_use]
pub fn load(data_dir: &Path) -> Chain {
    let path = journal_path(data_dir);
    let anchor_path = PathBuf::from(format!("{}.head.json", path.display()));
    if !path.exists() && !anchor_path.exists() {
        return Chain::default();
    }
    let lock_path = PathBuf::from(format!("{}.lock", path.display()));
    let _ = std::fs::create_dir_all(path.parent().unwrap_or(data_dir));
    let lock = File::options()
        .create(true)
        .truncate(false)
        .write(true)
        .open(&lock_path);
    if let Ok(f) = &lock {
        let _ = f.lock();
    }
    let mut chain = Chain::default();
    let anchor = match read_anchor(&anchor_path) {
        Ok(a) => a,
        Err(e) => {
            chain.load_error = Some(format!("unreadable audit journal: {e}"));
            return chain;
        }
    };
    if let Ok(t) = std::fs::read_to_string(&path) {
        for ln in t.lines().map(str::trim).filter(|l| !l.is_empty()) {
            // the Python builds an `AuditRecord(**line)`: exactly the nine fields and the two links
            let shaped = |r: &Map<String, Value>| {
                r.len() == FIELDS.len() + 2
                    && FIELDS
                        .iter()
                        .chain(&["prev_hash", "record_hash"])
                        .all(|k| r.contains_key(*k))
            };
            match serde_json::from_str::<Map<String, Value>>(ln) {
                Ok(r) if shaped(&r) => chain.records.push(r),
                Ok(_) => {
                    chain.load_error = Some("unreadable audit journal: TypeError".to_owned());
                    return chain;
                }
                Err(e) => {
                    chain.load_error = Some(format!(
                        "unreadable audit journal: JSONDecodeError({:?})",
                        e.to_string()
                    ));
                    return chain;
                }
            }
        }
    }
    if let Some((count, head)) = &anchor {
        let n = chain.records.len();
        chain.load_error = if *count > n {
            Some(format!(
                "audit journal regressed from anchored count {count} to {n}"
            ))
        } else if *count == 0 {
            (head != GENESIS_HASH).then(|| "empty audit anchor has a non-genesis head".to_owned())
        } else if text(&chain.records[count - 1], "record_hash") != *head {
            Some("audit journal does not contain its anchored head".to_owned())
        } else {
            None
        };
    }
    let anchored = anchor.as_ref().map_or(0, |a| a.0);
    if chain.load_error.is_none()
        && verify_chain(&chain.records)
        && !chain.records.is_empty()
        && anchored < chain.records.len()
    {
        let head = text(&chain.records[chain.records.len() - 1], "record_hash");
        let body =
            json!({"count": chain.records.len(), "record_hash": head, "schema": ANCHOR_SCHEMA});
        let tmp = anchor_path.with_extension("json.part");
        let wrote = File::create(&tmp).and_then(|mut f| {
            f.write_all(
                format!(
                    "{}\n",
                    stewie_twin::pyjson::dumps(&body).unwrap_or_default()
                )
                .as_bytes(),
            )?;
            f.sync_all()
        });
        if wrote.is_ok() {
            let _ = std::fs::rename(&tmp, &anchor_path);
        }
    }
    if let Ok(f) = &lock {
        let _ = f.unlock();
    }
    chain
}

impl Chain {
    /// The operator-facing flag (Python `integrity`): `None` when nothing is recorded, `false` when unreadable or
    /// tampered, `true` for a non-empty chain that verifies.
    #[must_use]
    pub fn integrity(&self) -> Option<bool> {
        if self.load_error.is_some() {
            return Some(false);
        }
        if self.records.is_empty() {
            return None;
        }
        Some(verify_chain(&self.records))
    }
}

#[cfg(test)]
mod tests {
    use serde_json::{Map, Value, json};

    use super::{GENESIS_HASH, digest, verify_chain};

    fn rec(prev: &str, action: &str) -> Map<String, Value> {
        // SYNTHETIC record fields (labelled)
        let mut r: Map<String, Value> = [
            "actor",
            "timestamp",
            "location",
            "mode",
            "reason",
            "before_state",
            "after_state",
            "evidence",
        ]
        .iter()
        .map(|k| ((*k).to_owned(), json!(format!("synthetic {k}"))))
        .collect();
        r.insert("action".into(), json!(action));
        r.insert("prev_hash".into(), json!(prev));
        let h = digest(&r, prev);
        r.insert("record_hash".into(), json!(h));
        r
    }

    #[test]
    fn a_mutated_field_or_a_broken_link_fails_the_chain() {
        let a = rec(GENESIS_HASH, "release");
        let b = rec(a["record_hash"].as_str().unwrap(), "sim_run");
        assert!(verify_chain(&[a.clone(), b.clone()]));
        let mut tampered = b.clone();
        tampered.insert("reason".into(), json!("rewritten"));
        assert!(!verify_chain(&[a.clone(), tampered]));
        assert!(!verify_chain(&[b, a]));
    }

    #[test]
    fn the_journal_on_disk_is_anchored_and_a_truncation_is_detected() {
        let dir = std::env::temp_dir().join(format!("stewie-audit-chain-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        // nothing recorded attests nothing
        assert_eq!(super::load(&dir).integrity(), None);
        let a = rec(GENESIS_HASH, "release");
        let b = rec(a["record_hash"].as_str().unwrap(), "sim_run");
        let line = |r: &Map<String, Value>| {
            format!(
                "{}\n",
                stewie_twin::pyjson::dumps(&Value::Object(r.clone())).unwrap()
            )
        };
        let path = super::journal_path(&dir);
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(&path, line(&a) + &line(&b)).unwrap();
        // a valid journal verifies, and its first read writes the anchor at its head
        assert_eq!(super::load(&dir).integrity(), Some(true));
        let anchor: Value = serde_json::from_str(
            &std::fs::read_to_string(format!("{}.head.json", path.display())).unwrap(),
        )
        .unwrap();
        assert_eq!(
            (anchor["count"].clone(), anchor["record_hash"].clone()),
            (json!(2), b["record_hash"].clone())
        );
        // dropping the tail regresses the journal below its anchor
        std::fs::write(&path, line(&a)).unwrap();
        assert_eq!(super::load(&dir).integrity(), Some(false));
        // a torn line is unreadable, never silently dropped
        std::fs::write(&path, line(&a) + &line(&b) + "{\"actor\": ").unwrap();
        assert_eq!(super::load(&dir).integrity(), Some(false));
        let _ = std::fs::remove_dir_all(&dir);
    }
}
