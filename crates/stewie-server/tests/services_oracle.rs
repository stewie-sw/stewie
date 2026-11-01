//! RW-55a2a against the Python oracle (`services_cases`): redaction, payload fingerprints, the accountable-action
//! classes, the audit ledger (records, correlation ids, rotation, a failed write that degrades and a critical one
//! that is refused), revocation health, and the fixed-window rate limiter, on the oracle's pinned clock. Actors,
//! actions, field values, keys and the clock are SYNTHETIC test inputs.

use std::path::Path;
use std::sync::Mutex;

use serde_json::{Map, Value, json};
use stewie_server::auth::{Auth, AuthConfig};
use stewie_server::operators::Store;
use stewie_server::services::{
    AUDIT_DEFAULT_MAX_BYTES, Ledger, RateLimiter, hash_payload, is_critical_action, redact,
};
use stewie_server::{Clock, OsEntropy};

/// SYNTHETIC: a settable clock.
struct PinnedClock(Mutex<f64>);

impl Clock for PinnedClock {
    fn now(&self) -> f64 {
        *self.0.lock().unwrap()
    }
}

impl PinnedClock {
    fn advance(&self, s: f64) {
        *self.0.lock().unwrap() += s;
    }
}

fn fields(v: &Value) -> Map<String, Value> {
    v.as_object().cloned().unwrap_or_default()
}

/// The ledger as the oracle snapshots it: rolled file names and the live records.
fn ledger_state(dir: &Path) -> Value {
    let mut rotated: Vec<String> = std::fs::read_dir(dir)
        .unwrap()
        .flatten()
        .map(|e| e.file_name().to_string_lossy().into_owned())
        .filter(|n| n.starts_with("events.jsonl."))
        .collect();
    rotated.sort();
    let live: Vec<Value> = std::fs::read_to_string(dir.join("events.jsonl"))
        .map(|t| {
            t.lines()
                .map(|l| serde_json::from_str(l).unwrap())
                .collect()
        })
        .unwrap_or_default();
    json!({"rotated": rotated, "live": live})
}

#[test]
#[allow(clippy::too_many_lines)] // one scenario, step for step as the oracle's
fn the_python_services_scenario_replays_exactly() {
    let fx = stewie_oracle::load("services_cases").unwrap().payload;
    let want = fx["steps"].as_array().unwrap();
    let dir = std::env::temp_dir().join(format!("stewie-services-oracle-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let clock = PinnedClock(Mutex::new(fx["clock0"].as_f64().unwrap()));
    let ledger = Ledger::new(dir.clone(), AUDIT_DEFAULT_MAX_BYTES, &clock);
    let mut got: Vec<Value> = Vec::new();
    let push = |got: &mut Vec<Value>, op: &str, args: &Value, ok: Value| {
        got.push(json!({"op": op, "args": args, "ok": ok}));
    };
    let mut it = want.iter().cloned();

    // redaction, fingerprints, classes: the inputs are the oracle's own
    for _ in 0..4 {
        let want_step = it.next().unwrap();
        push(
            &mut got,
            "redact",
            &want_step["args"],
            redact(&want_step["args"][0]),
        );
    }
    for _ in 0..4 {
        let want_step = it.next().unwrap();
        push(
            &mut got,
            "hash_payload",
            &want_step["args"],
            json!(hash_payload(&want_step["args"][0])),
        );
    }
    for _ in 0..11 {
        let want_step = it.next().unwrap();
        push(
            &mut got,
            "is_critical_action",
            &want_step["args"],
            json!(is_critical_action(want_step["args"][0].as_str().unwrap())),
        );
    }
    // the ledger
    let want_step = it.next().unwrap();
    ledger.log_event("alice", "auth.login", "password", None, &Map::new());
    push(&mut got, "log_event", &want_step["args"], Value::Null);
    clock.advance(0.0004);
    let want_step = it.next().unwrap();
    ledger.log_event(
        "bob",
        "plan.run",
        "",
        Some("cid-0001"),
        &fields(&want_step["args"][3]),
    );
    push(&mut got, "log_event", &want_step["args"], Value::Null);
    let want_step = it.next().unwrap();
    let mut f = fields(&want_step["args"][3]);
    let cid = f.remove("correlation_id").unwrap();
    ledger.log_event("bob", "plan.run", "t", cid.as_str(), &f);
    push(&mut got, "log_event", &want_step["args"], Value::Null);
    clock.advance(1.0);
    let want_step = it.next().unwrap();
    ledger
        .critical_event(
            "alice",
            "operator.approve",
            "carol",
            None,
            &fields(&want_step["args"][3]),
        )
        .unwrap();
    push(&mut got, "critical_event", &want_step["args"], Value::Null);
    let want_step = it.next().unwrap();
    push(
        &mut got,
        "audit_health",
        &want_step["args"],
        ledger.audit_health().to_json(),
    );
    let before_rotation = ledger_state(&dir);
    ledger.set_max_bytes(64);
    clock.advance(1.0);
    let want_step = it.next().unwrap();
    ledger.log_event("alice", "after.rotation", "", None, &Map::new());
    push(&mut got, "log_event", &want_step["args"], Value::Null);
    ledger.set_max_bytes(AUDIT_DEFAULT_MAX_BYTES);
    let after_rotation = ledger_state(&dir);
    // a failed write: a directory where the live ledger should be (a real EISDIR)
    let held = dir.join("held.jsonl");
    std::fs::rename(ledger.path(), &held).unwrap();
    std::fs::create_dir(ledger.path()).unwrap();
    let want_step = it.next().unwrap();
    ledger.log_event("alice", "lost", "", None, &Map::new());
    push(&mut got, "log_event", &want_step["args"], Value::Null);
    let want_step = it.next().unwrap();
    let refused = ledger.critical_event("alice", "rc.goto", "rover-1", None, &Map::new());
    assert!(refused.unwrap_err().to_string().contains("refused"));
    got.push(
        json!({"op": "critical_event", "args": want_step["args"], "error": "AuditWriteRefused"}),
    );
    let audit = ledger.audit_health();
    let want_step = it.next().unwrap();
    push(
        &mut got,
        "audit_health",
        &want_step["args"],
        json!({"degraded": audit.degraded, "failures": audit.failures, "has_error": audit.last_error.is_some()}),
    );
    std::fs::remove_dir(ledger.path()).unwrap();
    std::fs::rename(&held, ledger.path()).unwrap();
    // revocation health
    std::fs::write(dir.join("revoked_jti.json"), "[not json").unwrap();
    clock.advance(1.0);
    let env = [
        ("STEWIE_API_KEY", "automation-key-0123456789".to_owned()),
        ("STEWIE_DATA_DIR", dir.display().to_string()),
    ];
    let cfg = AuthConfig::from_env(&|k| env.iter().find(|(n, _)| *n == k).map(|(_, v)| v.clone()))
        .unwrap();
    let store = Store::new(dir.clone(), &clock, &OsEntropy);
    let auth = Auth {
        cfg: &cfg,
        store: &store,
        clock: &clock,
        entropy: &OsEntropy,
        ledger: &ledger,
        cid: None,
    };
    let want_step = it.next().unwrap();
    push(
        &mut got,
        "is_revoked",
        &want_step["args"],
        json!(auth.is_revoked(want_step["args"][0].as_str().unwrap())),
    );
    let revocation = ledger.revocation_health();
    let want_step = it.next().unwrap();
    push(
        &mut got,
        "revocation_health",
        &want_step["args"],
        json!({"degraded": revocation.degraded, "failures": revocation.failures, "has_error": revocation.last_error.is_some()}),
    );
    let mut final_state = ledger_state(&dir);
    for line in final_state["live"].as_array_mut().unwrap() {
        if line["action"] == "revocation.read_failed" {
            line["target"] = json!("<the read error>");
        }
    }
    // the rate limiter
    let rl = RateLimiter::new(3, 10.0);
    for want_step in it {
        let a = &want_step["args"];
        push(
            &mut got,
            "rate_allow",
            a,
            json!(rl.allow(
                a[0].as_str().unwrap(),
                a[1].as_f64().unwrap(),
                a[2].as_i64().unwrap()
            )),
        );
    }

    assert_eq!(got.len(), want.len(), "step count");
    for (k, (g, want_step)) in got.iter().zip(want).enumerate() {
        assert_eq!(g, want_step, "step {k}");
    }
    assert_eq!(
        before_rotation, fx["before_rotation"],
        "the ledger before rotation"
    );
    assert_eq!(
        after_rotation, fx["after_rotation"],
        "the ledger after rotation"
    );
    assert_eq!(final_state, fx["final"], "the final ledger");
    std::fs::remove_dir_all(&dir).unwrap();
}
