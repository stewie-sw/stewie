//! RW-55a2b and RW-55b1 against the Python oracles (`http_auth_cases`, `http_admin_cases`): the `FastAPI` `TestClient` session, request for request,
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

/// A PNG as the oracle records it: its size and the sha256 of its decoded RGB pixels.
fn png_summary(bytes: &[u8]) -> Value {
    let mut d = png::Decoder::new(std::io::Cursor::new(bytes));
    d.set_transformations(png::Transformations::EXPAND);
    let mut dec = d.read_info().unwrap();
    let mut buf = vec![0; dec.output_buffer_size().unwrap()];
    let info = dec.next_frame(&mut buf).unwrap();
    assert_eq!(info.bit_depth, png::BitDepth::Eight, "an 8-bit image");
    let px = &buf[..info.buffer_size()];
    // as PIL's convert("RGB"): alpha dropped, grey replicated
    let rgb: Vec<u8> = match info.color_type {
        png::ColorType::Rgb => px.to_vec(),
        png::ColorType::Rgba => px.chunks(4).flat_map(|c| [c[0], c[1], c[2]]).collect(),
        png::ColorType::Grayscale => px.iter().flat_map(|g| [*g; 3]).collect(),
        png::ColorType::GrayscaleAlpha => px.chunks(2).flat_map(|c| [c[0]; 3]).collect(),
        png::ColorType::Indexed => panic!("palette not expanded"),
    };
    let rgb = rgb.as_slice();
    let digest = Sha256::digest(rgb).iter().fold(String::new(), |mut h, b| {
        use std::fmt::Write as _;
        let _ = write!(h, "{b:02x}");
        h
    });
    json!({"png": {"width": info.width, "height": info.height, "rgb_sha256": digest}})
}

/// Replay the fixture `name` (seeded from `seed`) through a fresh app; `before(i, step, clock, dir)` reproduces
/// what the oracle did between requests. Headers and cookies are compared where the fixture recorded them.
#[allow(clippy::too_many_lines)] // one request loop, then the stores and journals
async fn replay(
    name: &str,
    seed: &[u8],
    before: impl Fn(usize, &Value, &PinnedClock, &std::path::Path),
    departure: impl Fn(&Value, &mut Value),
) {
    let fx = stewie_oracle::load(name).unwrap().payload;
    let dir = std::env::temp_dir().join(format!("stewie-{name}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let mut env: HashMap<String, String> = fx["env"]
        .as_object()
        .unwrap()
        .iter()
        .map(|(k, v)| (k.clone(), v.as_str().unwrap().to_owned()))
        .collect();
    env.insert("STEWIE_DATA_DIR".into(), dir.display().to_string());
    // the committed planner parameters (the Python planner's own values, D-R115)
    env.insert(
        "STEWIE_PLANNER_CONFIG".into(),
        stewie_oracle::repo_root()
            .join("deploy/planner.json")
            .display()
            .to_string(),
    );
    // the in-repo verbatim subset of the real site vectors (the oracle reads the same file)
    env.insert(
        "STEWIE_SITE_VECTORS".into(),
        stewie_oracle::repo_root()
            .join("stewie/server/fixtures/artemis_sites_sample.geojson")
            .display()
            .to_string(),
    );
    let clock: &'static PinnedClock = Box::leak(Box::new(PinnedClock(Mutex::new(
        fx["clock0"].as_f64().unwrap(),
    ))));
    let bytes: &'static SeededBytes = Box::leak(Box::new(SeededBytes {
        seed: Sha256::digest(seed).into(),
        n: Mutex::new(0),
    }));
    let state = AppState::from_env(&|k| env.get(k).cloned(), clock, bytes).unwrap();
    let app = router(Arc::new(state));
    let steps = fx["steps"].as_array().unwrap();
    for (i, step) in steps.iter().enumerate() {
        before(i, step, clock, &dir);
        let r = &step["request"];
        let mut req = Request::builder()
            .method(r["method"].as_str().unwrap())
            .uri(r["path"].as_str().unwrap());
        for (k, v) in r["headers"].as_object().unwrap() {
            req = req.header(k, v.as_str().unwrap());
        }
        let body = if let Some(sent) = r.get("sent").and_then(Value::as_str) {
            // the exact bytes the oracle's client sent (key order matters to the Python repr)
            if !r["json"].is_null() {
                req = req.header("content-type", "application/json");
            }
            sent.to_owned()
        } else if let Some(raw) = r["raw"].as_str() {
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
        let header_of = |n: &str| {
            resp.headers()
                .get(n)
                .and_then(|v| v.to_str().ok())
                .map(str::to_owned)
        };
        let (resp_cache, resp_type) = (header_of("cache-control"), header_of("content-type"));
        let raw = resp.into_body().collect().await.unwrap().to_bytes();
        let mut body: Value = if resp_type.as_deref() == Some("image/png") {
            png_summary(&raw)
        } else {
            serde_json::from_slice(&raw)
                .unwrap_or_else(|_| json!(String::from_utf8_lossy(&raw).into_owned()))
        };
        normalise(&mut body);
        departure(step, &mut body);
        let what = format!("step {} {} {}", i + 1, r["method"], r["path"]);
        assert_eq!(
            u64::from(status),
            step["status"].as_u64().unwrap(),
            "{what}: status ({body})"
        );
        assert_eq!(body, step["body"], "{what}: body");
        // the caching policy and media type, where the fixture recorded them
        if step.get("cache_control").is_some() {
            let got = resp_cache.as_deref().map_or(Value::Null, |v| json!(v));
            assert_eq!(got, step["cache_control"], "{what}: Cache-Control");
            assert_eq!(
                resp_type.as_deref().map_or(Value::Null, |v| json!(v)),
                step["content_type"],
                "{what}: Content-Type"
            );
        }
        if step.get("headers").is_some() {
            assert_eq!(Value::Object(headers), step["headers"], "{what}: headers");
            assert_eq!(Value::Array(cookies), step["cookies"], "{what}: cookies");
        }
    }
    // a session that enrolled nobody leaves no store (the fixture records null)
    let store: Value = std::fs::read_to_string(dir.join("operators.json"))
        .map_or(Value::Null, |t| serde_json::from_str(&t).unwrap());
    assert_eq!(store, fx["store"], "the account store");
    // a session that audited nothing leaves no ledger (the fixture records an empty one)
    let mut ledger: Vec<Value> = std::fs::read_to_string(dir.join("events.jsonl"))
        .unwrap_or_default()
        .lines()
        .map(|l| serde_json::from_str(l).unwrap())
        .collect();
    for line in &mut ledger {
        if line["action"] == "revocation.read_failed" {
            line["target"] = json!("<the read error>");
        }
    }
    assert_eq!(Value::Array(ledger), fx["ledger"], "the audit ledger");
    // the durable journals, byte for byte, where the fixture recorded them
    if let Some(journals) = fx.get("journals").and_then(Value::as_object) {
        for (name, want) in journals {
            let raw = std::fs::read(dir.join("twin").join(name)).unwrap();
            let got = Sha256::digest(&raw).iter().fold(String::new(), |mut h, b| {
                use std::fmt::Write as _;
                let _ = write!(h, "{b:02x}");
                h
            });
            assert_eq!(&json!(got), want, "the journal {name}");
        }
        assert!(!journals.is_empty(), "vacuity: journals were recorded");
    }
    std::fs::remove_dir_all(&dir).unwrap();
}

#[tokio::test]
async fn the_python_identity_session_replays_exactly() {
    // the oracle advanced its clock before requests 15, 18 and 24 (1-based), and corrupted the revocation store
    // before the last two
    let steps = stewie_oracle::load("http_auth_cases").unwrap().payload["steps"]
        .as_array()
        .unwrap()
        .len();
    replay(
        "http_auth_cases",
        b"stewie-http-auth-oracle",
        |i, _, clock, dir| {
            if [15, 18, 24].contains(&(i + 1)) {
                *clock.0.lock().unwrap() += 1.0;
            }
            if i + 2 == steps {
                std::fs::write(dir.join("revoked_jti.json"), "[not json").unwrap();
            }
        },
        |_, _| {},
    )
    .await;
}

#[tokio::test]
async fn the_python_administration_session_replays_exactly() {
    replay(
        "http_admin_cases",
        b"stewie-http-admin-oracle",
        |_, step, clock, _| {
            *clock.0.lock().unwrap() = step["clock"].as_f64().unwrap();
        },
        |_, _| {},
    )
    .await;
}

#[tokio::test]
async fn the_python_construction_session_replays_with_the_recorded_departure() {
    // D-R101: the Rust site plan adds one advisory per footprint pair closer than the minimum gap but not
    // overlapping; strip exactly those (each checked to be one) before the exact comparison
    let extras = std::sync::atomic::AtomicUsize::new(0);
    replay(
        "http_build_cases",
        b"stewie-http-build-oracle",
        |_, step, clock, _| {
            *clock.0.lock().unwrap() = step["clock"].as_f64().unwrap();
        },
        |step, body| {
            let request = &step["request"];
            let (Some(clear), Some(adv)) =
                (body.get("clearances").cloned(), body.get_mut("advisories"))
            else {
                return;
            };
            // as the server reads it: a number or a numeric string (Pydantic's lax float)
            let g = &request["json"]["min_gap_m"];
            let min_gap = g
                .as_f64()
                .or_else(|| g.as_str().and_then(|t| t.trim().parse().ok()))
                .unwrap_or(2.0);
            let n = clear
                .as_array()
                .unwrap()
                .iter()
                .filter(|c| c["overlap"] == false && c["gap_m"].as_f64().unwrap() < min_gap)
                .count();
            let adv = adv.as_array_mut().unwrap();
            for a in adv.drain(adv.len() - n..) {
                assert!(
                    a.as_str()
                        .unwrap()
                        .contains(" apart -- footprints should clear by"),
                    "{a}"
                );
            }
            extras.fetch_add(n, std::sync::atomic::Ordering::Relaxed);
        },
    )
    .await;
    assert!(
        extras.into_inner() > 0,
        "vacuity: a sub-minimum clearance was advised"
    );
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

#[test]
fn startup_refuses_a_configured_database_projection() {
    // SYNTHETIC environment (D-R113: the journal is the authority; the projection is not ported)
    let env = [("STEWIE_DATABASE_URL", "postgresql://example.invalid/stewie")];
    let e = stewie_server::app::Settings::from_env(&|k| {
        env.iter()
            .find(|(n, _)| *n == k)
            .map(|(_, v)| (*v).to_owned())
    })
    .unwrap_err();
    assert!(e.contains("D-R113"), "{e}");
}

#[tokio::test]
async fn the_python_twin_session_replays_exactly() {
    replay(
        "http_twin_cases",
        b"stewie-http-twin-oracle",
        |_, step, clock, dir| {
            *clock.0.lock().unwrap() = step["clock"].as_f64().unwrap();
            // the oracle recorded this memory between requests (SYNTHETIC, labelled)
            if step["request"]["path"] == "/twin/terrain/shackleton_rim" {
                let mut mem = stewie_twin::terrain_memory::TerrainMemory::new(
                    "shackleton_rim",
                    3,
                    4,
                    0.5,
                    (2.0, -1.0),
                )
                .unwrap();
                let mut delta = vec![0.0; 12];
                delta[0] = -0.2;
                delta[1] = -0.2;
                delta[11] = 0.15;
                mem.apply(&delta, "rim-pad", 64.0).unwrap();
                stewie_twin::terrain_memory::save_site(dir, &mem).unwrap();
            }
        },
        |_, _| {},
    )
    .await;
}

#[tokio::test]
async fn a_resync_whose_world_commit_fails_is_rolled_back() {
    // SYNTHETIC: a directory where the world journal belongs makes the commit fail; the patch must be undone
    let dir = std::env::temp_dir().join(format!("stewie-resync-rollback-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(dir.join("twin")).unwrap();
    let env: HashMap<&str, String> = [
        ("STEWIE_API_KEY", "automation-key-0123456789".to_owned()),
        ("STEWIE_DATA_DIR", dir.display().to_string()),
    ]
    .into_iter()
    .collect();
    let clock: &'static PinnedClock = Box::leak(Box::new(PinnedClock(Mutex::new(1.8e9))));
    let bytes: &'static SeededBytes = Box::leak(Box::new(SeededBytes {
        seed: Sha256::digest(b"stewie-resync-rollback").into(),
        n: Mutex::new(0),
    }));
    let state = AppState::from_env(&|k| env.get(k).cloned(), clock, bytes).unwrap();
    std::fs::create_dir(dir.join("twin/world.journal")).unwrap();
    let app = router(Arc::new(state));
    let send = |method: &str, path: &str, body: Option<Value>| {
        let builder = Request::builder()
            .method(method)
            .uri(path)
            .header("x-api-key", "automation-key-0123456789");
        let (builder, text) = match body {
            Some(b) => (
                builder.header("content-type", "application/json"),
                b.to_string(),
            ),
            None => (builder, String::new()),
        };
        let mut req = builder.body(Body::from(text)).unwrap();
        req.extensions_mut()
            .insert(ConnectInfo(SocketAddr::from(([127, 0, 0, 1], 50000))));
        app.clone().oneshot(req)
    };
    let r = send(
        "POST",
        "/twin/resync",
        Some(json!({"heights_m": [[1100.0]], "origin_rc": [10, 10], "provenance": "doomed"})),
    )
    .await
    .unwrap();
    assert_eq!(r.status().as_u16(), 500);
    let body: Value =
        serde_json::from_slice(&r.into_body().collect().await.unwrap().to_bytes()).unwrap();
    assert!(
        body["error"]
            .as_str()
            .unwrap()
            .starts_with("resync rolled back: world-state commit failed"),
        "{body}"
    );
    let v = send("GET", "/twin/version", None).await.unwrap();
    let v: Value =
        serde_json::from_slice(&v.into_body().collect().await.unwrap().to_bytes()).unwrap();
    // the store is append-only (as the Python's): the patch stays in history, compensated by an undo event
    assert_eq!(v["twin_version"], 2, "a patch then its undo");
    assert_eq!(v["chain_valid"], true);
    let hist = send("GET", "/twin/history", None).await.unwrap();
    let hist: Value =
        serde_json::from_slice(&hist.into_body().collect().await.unwrap().to_bytes()).unwrap();
    let kinds: Vec<&str> = hist["events"]
        .as_array()
        .unwrap()
        .iter()
        .map(|e| e["kind"].as_str().unwrap())
        .collect();
    assert_eq!(kinds, ["patch", "undo"], "{hist}");
    assert_eq!(hist["events"][1]["target"], hist["events"][0]["seq"]);
    std::fs::remove_dir_all(&dir).unwrap();
}

#[tokio::test]
async fn the_python_record_and_volume_session_replays_exactly() {
    replay(
        "http_record_cases",
        b"stewie-http-record-oracle",
        |_, step, clock, _| {
            *clock.0.lock().unwrap() = step["clock"].as_f64().unwrap();
        },
        |_, _| {},
    )
    .await;
}

/// SYNTHETIC: an app over a fresh data dir with the automation key (and the planner parameters when `planner`).
fn bare_app(tag: &str, planner: bool) -> (axum::Router, std::path::PathBuf) {
    let dir = std::env::temp_dir().join(format!("stewie-{tag}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(dir.join("twin")).unwrap();
    let mut env: HashMap<&str, String> = [
        ("STEWIE_API_KEY", "automation-key-0123456789".to_owned()),
        ("STEWIE_DATA_DIR", dir.display().to_string()),
    ]
    .into_iter()
    .collect();
    if planner {
        env.insert(
            "STEWIE_PLANNER_CONFIG",
            stewie_oracle::repo_root()
                .join("deploy/planner.json")
                .display()
                .to_string(),
        );
    }
    let clock: &'static PinnedClock = Box::leak(Box::new(PinnedClock(Mutex::new(1.8e9))));
    let bytes: &'static SeededBytes = Box::leak(Box::new(SeededBytes {
        seed: Sha256::digest(tag.as_bytes()).into(),
        n: Mutex::new(0),
    }));
    let state = AppState::from_env(&|k| env.get(k).cloned(), clock, bytes).unwrap();
    (router(Arc::new(state)), dir)
}

async fn post(app: &axum::Router, path: &str, body: Value) -> (u16, Value) {
    let mut req = Request::builder()
        .method("POST")
        .uri(path)
        .header("x-api-key", "automation-key-0123456789")
        .header("content-type", "application/json")
        .body(Body::from(body.to_string()))
        .unwrap();
    req.extensions_mut()
        .insert(ConnectInfo(SocketAddr::from(([127, 0, 0, 1], 50000))));
    let r = app.clone().oneshot(req).await.unwrap();
    let status = r.status().as_u16();
    let v = serde_json::from_slice(&r.into_body().collect().await.unwrap().to_bytes()).unwrap();
    (status, v)
}

#[tokio::test]
async fn a_terrain_record_whose_world_commit_fails_restores_the_prior_memory() {
    // SYNTHETIC mission; a directory where the world journal belongs makes the commit fail
    let (app, dir) = bare_app("record-rollback", true);
    std::fs::create_dir(dir.join("twin/world.journal")).unwrap();
    let mission = json!({"mission": {"name": "pad", "body": "moon", "orders": [
        {"action": "Level pad", "kind": "cut", "x": 0.0, "y": 0.0, "footprint_m2": 9.0, "depth_m": 0.1}]}});
    let (status, body) = post(&app, "/twin/terrain/haworth", mission).await;
    assert_eq!(status, 500, "{body}");
    assert!(
        body["error"]
            .as_str()
            .unwrap()
            .starts_with("terrain record rolled back: world-state commit failed"),
        "{body}"
    );
    assert!(
        !stewie_twin::terrain_memory::terrain_path(&dir, "haworth").exists(),
        "the fresh site's memory was rolled back to nothing"
    );
    std::fs::remove_dir_all(&dir).unwrap();
}

#[tokio::test]
async fn the_planning_routes_refuse_without_planner_parameters() {
    // SYNTHETIC: no STEWIE_PLANNER_CONFIG (D-R115: never compiled defaults)
    let (app, dir) = bare_app("no-planner", false);
    let orders = json!([{"action": "Level pad", "kind": "cut", "x": 0.0, "y": 0.0, "footprint_m2": 9.0, "depth_m": 0.1}]);
    let (status, body) = post(
        &app,
        "/siteplan/volume",
        json!({"orders": orders, "density_kg_m3": 1500.0}),
    )
    .await;
    assert_eq!(status, 503, "{body}");
    assert!(
        body["error"]
            .as_str()
            .unwrap()
            .contains("STEWIE_PLANNER_CONFIG"),
        "{body}"
    );
    let (status, _) = post(
        &app,
        "/twin/terrain/haworth",
        json!({"mission": {"name": "pad", "body": "moon", "orders": orders}}),
    )
    .await;
    assert_eq!(status, 503);
    std::fs::remove_dir_all(&dir).unwrap();
}

#[tokio::test]
async fn the_python_world_session_replays_exactly() {
    replay(
        "http_world_cases",
        b"stewie-http-world-oracle",
        |_, step, clock, dir| {
            *clock.0.lock().unwrap() = step["clock"].as_f64().unwrap();
            // the oracle recorded this traffic memory between requests (SYNTHETIC, labelled)
            if step["request"]["path"] == "/world/traffic-layer?site=shackleton_rim" {
                let mut tm = stewie_twin::traffic_memory::TrafficMemory::new(
                    "shackleton_rim",
                    4,
                    5,
                    0.5,
                    (1.0, -2.0),
                    stewie_twin::traffic_memory::TrafficParams {
                        mass_areal: 130.0,
                        sigma_c_n: 60.0,
                        contact_width_m: 0.18,
                    },
                )
                .unwrap();
                let mut load = vec![0.0; 20];
                for c in 1..4 {
                    load[5 + c] = 2400.0;
                }
                load[12] = 900.0;
                tm.apply(&load, "haul-1", "ev-1").unwrap();
                stewie_twin::traffic_memory::save_site(dir, &tm).unwrap();
            }
        },
        |_, _| {},
    )
    .await;
}

#[tokio::test]
async fn the_python_dem_session_replays_exactly() {
    replay(
        "http_dem_cases",
        b"stewie-http-dem-oracle",
        |i, _, _, dir| {
            // the oracle wrote this boulder scene after its second request (SYNTHETIC, labelled)
            if i == 2 {
                std::fs::write(
                    dir.join("clasts_scene.json"),
                    r#"{"n": 2, "clasts": [{"x": 1.5, "y": -2.0, "z": 0.25, "r": 0.4}, {"x": 3.0, "y": 4.5, "z": 0.1, "r": 0.2}], "solver": "test"}"#,
                )
                .unwrap();
            }
        },
        |step, body| {
            // the georef's unrounded lat/lon: the closed-form inverse against PROJ's agrees to 1e-9 deg
            // (RW-10), not bit for bit; checked, then taken as recorded
            let path = step["request"]["path"].as_str().unwrap_or("");
            if !path.starts_with("/dem/georef") || step["status"] != 200 {
                return;
            }
            let want = &step["body"];
            let mut pairs: Vec<(String, usize)> = vec![("center".into(), usize::MAX)];
            pairs.extend((0..4).map(|i| ("corners".to_owned(), i)));
            for (key, i) in pairs {
                for c in ["lat", "lon"] {
                    let (got, exp) = if i == usize::MAX {
                        (&mut body[&key][c], &want[&key][c])
                    } else {
                        (&mut body[&key][i][c], &want[&key][i][c])
                    };
                    let d = (got.as_f64().unwrap() - exp.as_f64().unwrap()).abs();
                    assert!(d < 1e-9, "{path} {key}[{i}].{c}: off by {d}");
                    *got = exp.clone();
                }
            }
        },
    )
    .await;
}
