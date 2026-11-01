//! RW-55a2b against the Python oracle (`http_auth_cases`): the `FastAPI` `TestClient` session, request for request,
//! through the Axum app from the same peer (127.0.0.1) on the same pinned clock and seeded bytes. Each response's
//! status, JSON body, hardening headers and parsed Set-Cookie attributes must match, then the account store and
//! the audit ledger. The clock, the byte stream, emails, passwords and keys are SYNTHETIC test inputs.

use std::collections::HashMap;
use std::net::SocketAddr;
use std::sync::{Arc, Mutex};

use axum::body::Body;
use axum::extract::ConnectInfo;
use axum::http::Request;
use http_body_util::BodyExt as _;
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};
use stewie_server::app::{AppState, router};
use stewie_server::{Clock, Entropy};
use tower::ServiceExt as _;

/// SYNTHETIC: a settable clock.
struct PinnedClock(Mutex<f64>);

impl Clock for PinnedClock {
    fn now(&self) -> f64 {
        *self.0.lock().unwrap()
    }
}

/// SYNTHETIC: the oracle's deterministic stream, sha256(seed || counter) blocks, the tail of the last block dropped.
struct SeededBytes {
    seed: [u8; 32],
    n: Mutex<u64>,
}

impl Entropy for SeededBytes {
    fn fill(&self, buf: &mut [u8]) {
        let mut out = Vec::new();
        let mut n = self.n.lock().unwrap();
        while out.len() < buf.len() {
            let mut h = Sha256::new();
            h.update(self.seed);
            h.update(n.to_be_bytes());
            out.extend_from_slice(&h.finalize());
            *n += 1;
        }
        buf.copy_from_slice(&out[..buf.len()]);
    }
}

const KEEP_HEADERS: [&str; 7] = [
    "content-type",
    "x-correlation-id",
    "x-content-type-options",
    "referrer-policy",
    "permissions-policy",
    "cache-control",
    "access-control-allow-origin",
];

/// The Set-Cookie lines parsed as the oracle parses them: name, unquoted value, attributes lower-cased.
fn cookies_of(headers: &axum::http::HeaderMap) -> Vec<Value> {
    headers
        .get_all("set-cookie")
        .iter()
        .map(|line| {
            let line = line.to_str().unwrap();
            let mut parts = line.split(';').map(str::trim);
            let (name, value) = parts.next().unwrap().split_once('=').unwrap_or((line, ""));
            let mut c = Map::new();
            c.insert("name".into(), json!(name));
            c.insert("value".into(), json!(value.trim_matches('"')));
            for p in parts {
                match p.split_once('=') {
                    Some((k, v)) => c.insert(k.to_lowercase(), json!(v)),
                    None => c.insert(p.to_lowercase(), json!(true)),
                };
            }
            Value::Object(c)
        })
        .collect()
}

fn normalise(body: &mut Value) {
    if let Some(m) = body.as_object_mut() {
        if m.contains_key("uptime_s") {
            m.insert("uptime_s".into(), json!("<uptime>"));
        }
        if let Some(r) = m.get_mut("revocation")
            && !r["last_error"].is_null()
        {
            r["last_error"] = json!("<the read error>");
        }
    }
}

#[tokio::test]
async fn the_python_identity_session_replays_exactly() {
    let fx = stewie_oracle::load("http_auth_cases").unwrap().payload;
    let dir = std::env::temp_dir().join(format!("stewie-http-oracle-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let mut env: HashMap<String, String> = fx["env"]
        .as_object()
        .unwrap()
        .iter()
        .map(|(k, v)| (k.clone(), v.as_str().unwrap().to_owned()))
        .collect();
    env.insert("STEWIE_DATA_DIR".into(), dir.display().to_string());
    let clock: &'static PinnedClock = Box::leak(Box::new(PinnedClock(Mutex::new(
        fx["clock0"].as_f64().unwrap(),
    ))));
    let bytes: &'static SeededBytes = Box::leak(Box::new(SeededBytes {
        seed: Sha256::digest(b"stewie-http-auth-oracle").into(),
        n: Mutex::new(0),
    }));
    let state = AppState::from_env(&|k| env.get(k).cloned(), clock, bytes).unwrap();
    let app = router(Arc::new(state));
    let steps = fx["steps"].as_array().unwrap();
    // the oracle advanced its clock before these requests (1-based), and corrupted the revocation store before the
    // last two
    let advance_before = [15, 18, 24];
    for (i, step) in steps.iter().enumerate() {
        if advance_before.contains(&(i + 1)) {
            *clock.0.lock().unwrap() += 1.0;
        }
        if i + 2 == steps.len() {
            std::fs::write(dir.join("revoked_jti.json"), "[not json").unwrap();
        }
        let r = &step["request"];
        let mut req = Request::builder()
            .method(r["method"].as_str().unwrap())
            .uri(r["path"].as_str().unwrap());
        for (k, v) in r["headers"].as_object().unwrap() {
            req = req.header(k, v.as_str().unwrap());
        }
        let body = if let Some(raw) = r["raw"].as_str() {
            raw.to_owned()
        } else if r["json"].is_null() {
            String::new()
        } else {
            req = req.header("content-type", "application/json");
            r["json"].to_string()
        };
        req = req.header("content-length", body.len());
        let mut req = req.body(Body::from(body)).unwrap();
        req.extensions_mut()
            .insert(ConnectInfo(SocketAddr::from(([127, 0, 0, 1], 50000))));
        let resp = app.clone().oneshot(req).await.unwrap();
        let status = resp.status().as_u16();
        let headers: Map<String, Value> = KEEP_HEADERS
            .iter()
            .filter_map(|k| {
                resp.headers()
                    .get(*k)
                    .map(|v| ((*k).to_owned(), json!(v.to_str().unwrap())))
            })
            .collect();
        let cookies = cookies_of(resp.headers());
        let raw = resp.into_body().collect().await.unwrap().to_bytes();
        let mut body: Value = serde_json::from_slice(&raw)
            .unwrap_or_else(|_| json!(String::from_utf8_lossy(&raw).into_owned()));
        normalise(&mut body);
        let what = format!("step {} {} {}", i + 1, r["method"], r["path"]);
        assert_eq!(
            u64::from(status),
            step["status"].as_u64().unwrap(),
            "{what}: status ({body})"
        );
        assert_eq!(body, step["body"], "{what}: body");
        assert_eq!(Value::Object(headers), step["headers"], "{what}: headers");
        assert_eq!(Value::Array(cookies), step["cookies"], "{what}: cookies");
    }
    let store: Value =
        serde_json::from_str(&std::fs::read_to_string(dir.join("operators.json")).unwrap())
            .unwrap();
    assert_eq!(store, fx["store"], "the account store");
    let mut ledger: Vec<Value> = std::fs::read_to_string(dir.join("events.jsonl"))
        .unwrap()
        .lines()
        .map(|l| serde_json::from_str(l).unwrap())
        .collect();
    for line in &mut ledger {
        if line["action"] == "revocation.read_failed" {
            line["target"] = json!("<the read error>");
        }
    }
    assert_eq!(Value::Array(ledger), fx["ledger"], "the audit ledger");
    std::fs::remove_dir_all(&dir).unwrap();
}

#[test]
fn startup_refuses_a_configured_cross_origin_allowlist() {
    // SYNTHETIC environment (D-R108: same-origin only until CORS is ported)
    let env = [("STEWIE_CORS_ORIGINS", "https://example.org")];
    let e = stewie_server::app::Settings::from_env(&|k| {
        env.iter()
            .find(|(n, _)| *n == k)
            .map(|(_, v)| (*v).to_owned())
    })
    .unwrap_err();
    assert!(e.contains("same-origin"), "{e}");
}
