//! The world-transaction log against the Python twin: the REAL 2026-10-14 audit journal (sha256-pinned)
//! survives a torn tail, two restarts and appends with nothing acknowledged lost; interior corruption and
//! tampered hashes are refused without touching the file; a Python-written journal (SYNTHETIC inputs,
//! labelled) replays and verifies, and committing the same inputs writes byte-identical lines.

use std::fs;
use std::path::{Path, PathBuf};

use serde_json::Value;
use stewie_twin::world_log::{Snapshot, TransactionLog, WorldTransaction};
use stewie_twin::{TwinError, pyjson};

fn audit() -> Vec<u8> {
    let raw = fs::read(
        Path::new(env!("CARGO_MANIFEST_DIR")).join("fixtures/audit_world_2026-10-14.journal"),
    )
    .unwrap();
    let digest = sha256(&raw);
    assert_eq!(
        digest, "1e39943a7eecdaa533f429c6c9f6565aec1c36ac7ad4be1ed6dbb49906829a5d",
        "pinned real journal"
    );
    raw
}

fn sha256(b: &[u8]) -> String {
    use sha2::Digest;
    sha2::Sha256::digest(b)
        .iter()
        .fold(String::new(), |mut s, x| {
            use std::fmt::Write as _;
            let _ = write!(s, "{x:02x}");
            s
        })
}

fn scratch(tag: &str) -> PathBuf {
    let d = std::env::temp_dir().join(format!("stewie-twin-{tag}-{}", std::process::id()));
    let _ = fs::remove_dir_all(&d);
    fs::create_dir_all(&d).unwrap();
    d
}

fn recovery_files(dir: &Path) -> Vec<PathBuf> {
    let mut v: Vec<PathBuf> = fs::read_dir(dir)
        .unwrap()
        .flatten()
        .map(|e| e.path())
        .filter(|p| {
            p.file_name()
                .unwrap()
                .to_string_lossy()
                .starts_with("world.journal.recovery-")
        })
        .collect();
    v.sort();
    v
}

fn snapshot_of(rec: &Value) -> Snapshot {
    let s = |k: &str| rec[k].as_str().unwrap().to_owned();
    Snapshot {
        authority_sha: s("authority_sha"),
        twin_version: rec["twin_version"].as_i64().unwrap(),
        twin_hash: s("twin_hash"),
        plan_id: s("plan_id"),
        belief: rec["belief"].as_object().unwrap().clone(),
        mission: s("mission"),
        site: s("site"),
        body: s("body"),
        mission_t_s: rec["mission_t_s"].as_f64().unwrap(),
        provenance: s("provenance"),
        uncertainty_m: rec["uncertainty_m"].as_f64().unwrap(),
        packet_sha: s("packet_sha"),
        vehicle_sha: s("vehicle_sha"),
    }
}

#[test]
fn the_real_journal_keeps_every_acknowledged_append_across_two_restarts() {
    let audit = audit();
    for ending in ["intact", "torn", "torn-blank-tail", "missing-newline"] {
        let dir = scratch(ending);
        let journal = dir.join("world.journal");
        let mut original = audit.clone();
        if ending.starts_with("torn") {
            original.extend_from_slice(&audit[..audit.len() / 2]);
            if ending == "torn-blank-tail" {
                original.extend_from_slice(b"\n \n");
            }
        } else if ending == "missing-newline" {
            original.pop();
        }
        fs::write(&journal, &original).unwrap();
        let mut log = TransactionLog::from_journal(&journal).unwrap();
        let first: Value = serde_json::from_slice(&audit).unwrap();
        let mut expected = vec![first.clone()];
        assert_eq!(
            log.transactions()
                .iter()
                .map(WorldTransaction::record)
                .collect::<Vec<_>>(),
            expected,
            "{ending}"
        );
        assert!(log.verify_chain());
        assert_eq!(
            fs::read(&journal).unwrap(),
            audit,
            "{ending}: tail repaired to the real record"
        );
        let backups = recovery_files(&dir);
        assert_eq!(backups.len(), usize::from(ending != "intact"), "{ending}");
        if let Some(b) = backups.first() {
            assert_eq!(
                fs::read(b).unwrap(),
                original,
                "recovery copy keeps the original bytes"
            );
        }
        for _ in 0..2 {
            let acked = log.commit(snapshot_of(&first)).unwrap().record();
            expected.push(acked);
            let before = fs::read(&journal).unwrap();
            log = TransactionLog::from_journal(&journal).unwrap();
            assert_eq!(
                log.transactions()
                    .iter()
                    .map(WorldTransaction::record)
                    .collect::<Vec<_>>(),
                expected,
                "{ending}"
            );
            assert!(log.verify_chain());
            assert_eq!(
                fs::read(&journal).unwrap(),
                before,
                "a clean restart does not rewrite"
            );
            assert!(before.starts_with(&audit));
        }
        assert_eq!(recovery_files(&dir), backups);
        fs::remove_dir_all(&dir).unwrap();
    }
}

#[test]
fn interior_corruption_is_refused_and_the_file_is_untouched() {
    let audit = audit();
    let dir = scratch("interior");
    let journal = dir.join("world.journal");
    let mut original = audit.clone();
    original.extend_from_slice(&audit[..audit.len() / 2]);
    original.push(b'\n');
    original.extend_from_slice(&audit);
    fs::write(&journal, &original).unwrap();
    assert!(matches!(
        TransactionLog::from_journal(&journal),
        Err(TwinError::InteriorCorruption { .. })
    ));
    assert_eq!(fs::read(&journal).unwrap(), original);
    assert_eq!(fs::read_dir(&dir).unwrap().count(), 1, "no recovery copy");
    fs::remove_dir_all(&dir).unwrap();
}

#[test]
fn a_tampered_hash_or_link_is_refused_before_any_repair() {
    let audit = audit();
    for field in ["chain_hash", "world_sha", "prev_hash", "seq"] {
        let dir = scratch(field);
        let journal = dir.join("world.journal");
        let mut rec: Value = serde_json::from_slice(&audit).unwrap();
        if field == "seq" {
            rec["seq"] = Value::from(1);
        } else {
            let s = rec[field].as_str().unwrap();
            rec[field] = Value::from(&s[..s.len() - 1]);
        }
        let mut original = pyjson::dumps(&rec).unwrap().into_bytes();
        original.push(b'\n');
        original.extend_from_slice(&audit[..100]);
        fs::write(&journal, &original).unwrap();
        assert!(
            matches!(
                TransactionLog::from_journal(&journal),
                Err(TwinError::Tampered(_))
            ),
            "{field}"
        );
        assert_eq!(fs::read(&journal).unwrap(), original, "{field}");
        assert_eq!(
            fs::read_dir(&dir).unwrap().count(),
            1,
            "{field}: no recovery copy"
        );
        fs::remove_dir_all(&dir).unwrap();
    }
}

#[test]
fn python_float_repr_and_python_journals_match_byte_for_byte() {
    let fx = stewie_oracle::load("world_log_cases").unwrap().payload;
    assert!(fx["synthetic"].as_bool().unwrap());
    for pair in fx["floats"].as_array().unwrap() {
        assert_eq!(
            pyjson::float_repr(pair[0].as_f64().unwrap()).unwrap(),
            pair[1].as_str().unwrap()
        );
    }
    assert!(pyjson::float_repr(f64::NAN).is_err());
    let py = fx["journal"].as_str().unwrap();
    let dir = scratch("oracle");
    let journal = dir.join("world.journal");
    fs::write(&journal, py).unwrap();
    let log = TransactionLog::from_journal(&journal).unwrap();
    assert!(log.verify_chain());
    let chain: Vec<&str> = fx["chain"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_str().unwrap())
        .collect();
    assert_eq!(
        log.transactions()
            .iter()
            .map(|t| t.chain_hash.as_str())
            .collect::<Vec<_>>(),
        chain
    );
    let fresh = dir.join("rust.journal");
    fs::write(&fresh, b"").unwrap();
    let mut rust = TransactionLog::from_journal(&fresh).unwrap();
    for c in fx["commits"].as_array().unwrap() {
        rust.commit(snapshot_of(c)).unwrap();
    }
    assert_eq!(
        fs::read_to_string(&fresh).unwrap(),
        py,
        "Rust writes the bytes Python writes"
    );
    fs::remove_dir_all(&dir).unwrap();
}
