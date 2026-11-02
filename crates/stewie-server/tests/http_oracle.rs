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
use sqlx::Connection as _;
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
fn png_summary(bytes: &[u8], want: &Value) -> Value {
    let mut d = png::Decoder::new(std::io::Cursor::new(bytes));
    d.set_transformations(png::Transformations::EXPAND);
    let mut dec = d.read_info().unwrap();
    let mut buf = vec![0; dec.output_buffer_size().unwrap()];
    let info = dec.next_frame(&mut buf).unwrap();
    assert_eq!(info.bit_depth, png::BitDepth::Eight, "an 8-bit image");
    let px = &buf[..info.buffer_size()];
    // as PIL's convert("RGBA") / convert("RGB"): grey replicated, a missing alpha opaque / alpha dropped
    let rgba: Vec<u8> = match info.color_type {
        png::ColorType::Rgb => px.chunks(3).flat_map(|c| [c[0], c[1], c[2], 255]).collect(),
        png::ColorType::Rgba => px.to_vec(),
        png::ColorType::Grayscale => px.iter().flat_map(|g| [*g, *g, *g, 255]).collect(),
        png::ColorType::GrayscaleAlpha => px
            .chunks(2)
            .flat_map(|c| [c[0], c[0], c[0], c[1]])
            .collect(),
        png::ColorType::Indexed => panic!("palette not expanded"),
    };
    let hex = |b: &[u8]| {
        Sha256::digest(b).iter().fold(String::new(), |mut h, x| {
            use std::fmt::Write as _;
            let _ = write!(h, "{x:02x}");
            h
        })
    };
    let want = &want["png"];
    if want.get("rgba_sha256").is_none() {
        let rgb: Vec<u8> = rgba.chunks(4).flat_map(|c| [c[0], c[1], c[2]]).collect();
        return json!({"png": {"width": info.width, "height": info.height, "rgb_sha256": hex(&rgb)}});
    }
    let mut out =
        json!({"png": {"width": info.width, "height": info.height, "rgba_sha256": hex(&rgba)}});
    if let Some(b64) = want.get("rgba_b64").and_then(Value::as_str) {
        use base64::Engine as _;
        let recorded = base64::engine::general_purpose::STANDARD
            .decode(b64)
            .unwrap();
        // a float cast to a byte can land one step apart across hosts (an ULP over an integer boundary): one step
        // on at most 0.1% of the channels is that; anything more is a real difference
        let flicker = recorded.len() == rgba.len() && {
            let diffs: Vec<u8> = recorded
                .iter()
                .zip(&rgba)
                .map(|(a, b)| a.abs_diff(*b))
                .collect();
            diffs.iter().all(|d| *d <= 1)
                && diffs.iter().filter(|d| **d > 0).count() * 1000 <= diffs.len()
        };
        out["png"]["rgba_b64"] = json!(b64);
        if flicker {
            let n = recorded.iter().zip(&rgba).filter(|(a, b)| a != b).count();
            if n > 0 {
                eprintln!(
                    "png {}x{}: accepted a one-step byte flicker on {n} of {} channels",
                    info.width,
                    info.height,
                    rgba.len()
                );
            }
            out["png"]["rgba_sha256"] = want["rgba_sha256"].clone();
        } else {
            out["png"]["rgba_b64"] = json!(base64::engine::general_purpose::STANDARD.encode(&rgba));
        }
    }
    out
}

/// The body as the oracle recorded it: structure, strings, integers and booleans exactly, floats to 1e-12
/// relative. The server calls the platform libm (`hypot`, `sin`, ...), whose last bit differs between glibc
/// releases (the CI runner's 2.39 against the fixture host's 2.36 moved a haul distance by one ULP); anything wider
/// than a few ULP is a real difference. `Err` names the first place that differs.
#[allow(clippy::float_cmp)] // equal floats short-circuit; the tolerance covers the rest
fn close(got: &Value, want: &Value, at: &str) -> Result<(), String> {
    match (got, want) {
        (Value::Number(a), Value::Number(b)) if a.is_f64() || b.is_f64() => {
            let (x, y) = (a.as_f64().unwrap(), b.as_f64().unwrap());
            if x == y || (x - y).abs() <= 1e-12 * x.abs().max(y.abs()) {
                Ok(())
            } else {
                Err(format!("{at}: {x} vs {y}"))
            }
        }
        (Value::Array(a), Value::Array(b)) if a.len() == b.len() => a
            .iter()
            .zip(b)
            .enumerate()
            .try_for_each(|(i, (x, y))| close(x, y, &format!("{at}/{i}"))),
        (Value::Object(a), Value::Object(b)) if a.len() == b.len() => {
            a.iter().try_for_each(|(k, x)| {
                b.get(k)
                    .ok_or_else(|| format!("{at}/{k}: missing"))
                    .and_then(|y| close(x, y, &format!("{at}/{k}")))
            })
        }
        _ if got == want => Ok(()),
        _ => Err(at.to_owned()),
    }
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
    // files the oracle laid down in its data directory before its first request (SYNTHETIC inputs, labelled there)
    if let Some(files) = fx.get("seed_files").and_then(Value::as_object) {
        use base64::Engine as _;
        for (rel, b64) in files {
            let p = dir.join(rel);
            std::fs::create_dir_all(p.parent().unwrap()).unwrap();
            let bytes = base64::engine::general_purpose::STANDARD
                .decode(b64.as_str().unwrap())
                .unwrap();
            std::fs::write(p, bytes).unwrap();
        }
    }
    let mut env: HashMap<String, String> = fx["env"]
        .as_object()
        .unwrap()
        .iter()
        // `{data_dir}` stands for the session's own data directory (the oracle's was a temp dir of its own)
        .map(|(k, v)| {
            (
                k.clone(),
                v.as_str()
                    .unwrap()
                    .replace("{data_dir}", &dir.display().to_string()),
            )
        })
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
    let state = AppState::from_env(&|k| env.get(k).cloned(), clock, bytes)
        .unwrap()
        .with_environment(env.clone());
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
        let headers_all: Vec<(String, String)> = resp
            .headers()
            .iter()
            .filter_map(|(k, v)| {
                v.to_str()
                    .ok()
                    .map(|v| (k.as_str().to_owned(), v.to_owned()))
            })
            .collect();
        let raw = resp.into_body().collect().await.unwrap().to_bytes();
        let mut body: Value = if resp_type.as_deref() == Some("image/png") {
            png_summary(&raw, &step["body"])
        } else if resp_type.as_deref() == Some("application/octet-stream") {
            // as the oracle records a binary body: its digest, length and X-Dem-* headers
            let x_dem: Map<String, Value> = headers_all
                .iter()
                .filter(|(k, _)| k.starts_with("x-dem-"))
                .map(|(k, v)| (k.clone(), json!(v)))
                .collect();
            let digest = Sha256::digest(&raw).iter().fold(String::new(), |mut h, b| {
                use std::fmt::Write as _;
                let _ = write!(h, "{b:02x}");
                h
            });
            json!({"bytes_sha256": digest, "len": raw.len(), "x_dem": x_dem})
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
        if let Err(at) = close(&body, &step["body"], "") {
            assert_eq!(body, step["body"], "{what}: body differs at {at}");
        }
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
    // the edit-session store's rows, column for column (the JSON columns as their stored text)
    if let Some(want) = fx.get("db_rows") {
        use sqlx::Row as _;
        let mut db = sqlx::SqliteConnection::connect(&format!(
            "sqlite://{}",
            dir.join("edit_session.db").display()
        ))
        .await
        .unwrap();
        let sessions: Vec<Value> = sqlx::query(
            "SELECT opaque_id, plan_id, version, created_at, fid_seq, marker_seq, features, markers \
             FROM edit_session ORDER BY opaque_id",
        )
        .fetch_all(&mut db)
        .await
        .unwrap()
        .iter()
        .map(|r| {
            json!([r.get::<String, _>(0), r.get::<Option<String>, _>(1), r.get::<i64, _>(2), r.get::<f64, _>(3),
                   r.get::<i64, _>(4), r.get::<i64, _>(5), r.get::<String, _>(6), r.get::<String, _>(7)])
        })
        .collect();
        let audit: Vec<Value> = sqlx::query(
            "SELECT id, session_id, version, op, fid, kind, \"before\", \"after\", ts, target, reverted_op \
             FROM edit_audit ORDER BY session_id, version",
        )
        .fetch_all(&mut db)
        .await
        .unwrap()
        .iter()
        .map(|r| {
            json!([r.get::<i64, _>(0), r.get::<String, _>(1), r.get::<i64, _>(2), r.get::<String, _>(3),
                   r.get::<Option<String>, _>(4), r.get::<Option<String>, _>(5), r.get::<Option<String>, _>(6),
                   r.get::<Option<String>, _>(7), r.get::<f64, _>(8), r.get::<Option<i64>, _>(9),
                   r.get::<Option<String>, _>(10)])
        })
        .collect();
        assert!(!audit.is_empty(), "vacuity: audit rows were written");
        assert_eq!(
            json!(sessions),
            want["edit_session"],
            "the edit_session rows"
        );
        assert_eq!(json!(audit), want["edit_audit"], "the edit_audit rows");
    }
    // the data-directory files the session wrote, byte for byte, where the fixture recorded them
    if let Some(files) = fx.get("data_files").and_then(Value::as_object) {
        for (rel, want) in files {
            let got = Sha256::digest(std::fs::read(dir.join(rel)).unwrap())
                .iter()
                .fold(String::new(), |mut h, b| {
                    use std::fmt::Write as _;
                    let _ = write!(h, "{b:02x}");
                    h
                });
            assert_eq!(&json!(got), want, "the data file {rel}");
        }
        assert!(!files.is_empty(), "vacuity: data files were recorded");
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

#[test]
fn startup_refuses_the_constant_overlay_it_would_ignore() {
    // SYNTHETIC environments (D-R135: the Rust compiles the N15 overlay's constants in)
    let settings = |env: &[(&str, &str)]| {
        stewie_server::app::Settings::from_env(&|k| {
            env.iter()
                .find(|(n, _)| *n == k)
                .map(|(_, v)| (*v).to_owned())
        })
    };
    let e = settings(&[
        ("STEWIE_RHO_SURFACE", "1250"),
        ("STEWIE_ROVER_MASS_DRY_KG", "25"),
    ])
    .unwrap_err();
    assert!(
        e.contains("D-R135")
            && e.contains("STEWIE_RHO_SURFACE")
            && e.contains("STEWIE_ROVER_MASS_DRY_KG"),
        "{e}"
    );
    let e = settings(&[("STEWIE_CONFIG", "/etc/stewie.toml")]).unwrap_err();
    assert!(e.contains("STEWIE_CONFIG") && e.contains("D-R135"), "{e}");
    // an empty STEWIE_CONFIG is unset, as the Python's; a setting that is not a constant is no overlay
    assert!(settings(&[("STEWIE_CONFIG", ""), ("STEWIE_REPORTS_TTL_S", "604800")]).is_ok());
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
        |i, step, clock, dir| {
            *clock.0.lock().unwrap() = step["clock"].as_f64().unwrap();
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

#[tokio::test]
async fn the_python_spec_session_replays_exactly() {
    replay(
        "http_spec_cases",
        b"stewie-http-spec-oracle",
        |i, step, clock, dir| {
            *clock.0.lock().unwrap() = step["clock"].as_f64().unwrap();
            // the oracle's tileset, written before its first request (SYNTHETIC, labelled)
            if i == 0 {
                let t = dir.join("tiles").join("twin");
                std::fs::create_dir_all(&t).unwrap();
                std::fs::write(
                    t.join("tileset.json"),
                    r#"{"asset": {"version": "1.0"}, "geometricError": 12.5, "root": {"content": {"uri": "points.pnts"}}}"#,
                )
                .unwrap();
                std::fs::write(t.join("points.pnts"), (0..64).collect::<Vec<u8>>()).unwrap();
            }
        },
        |step, body| {
            // D-R131: the Rust sun is the bundled DE440 pack, named as such; the Python answered from SPICE but labels
            // every answer `analytic`. The two agree to 1e-6 deg (RW-15).
            let path = step["request"]["path"].as_str().unwrap_or("");
            if !path.starts_with("/ephemeris") || step["status"] != 200 {
                return;
            }
            let (got, want) = (&mut body["ephemeris"], &step["body"]["ephemeris"]);
            assert_eq!(got["source"], "de440", "{path}: source");
            assert_eq!(want["source"], "analytic", "{path}: the Python's label");
            got["source"] = want["source"].clone();
            for k in ["sun_az_deg", "sun_el_deg"] {
                let d = (got[k].as_f64().unwrap() - want[k].as_f64().unwrap()).abs();
                let d = if k == "sun_az_deg" { d.min(360.0 - d) } else { d };
                assert!(d < 1e-6, "{path} {k}: off by {d} deg");
                got[k] = want[k].clone();
            }
        },
    )
    .await;
}

#[tokio::test]
async fn the_python_content_session_replays_exactly() {
    replay(
        "http_content_cases",
        b"stewie-http-content-oracle",
        |_, step, clock, _| {
            *clock.0.lock().unwrap() = step["clock"].as_f64().unwrap();
        },
        |_, _| {},
    )
    .await;
}

#[tokio::test]
async fn the_static_pages_serve_the_committed_files() {
    // the Python serves the committed files as they are (FileResponse, json.load): the bytes and the types
    const HTML: &str = "text/html; charset=utf-8";
    let (app, dir) = bare_app("program", false);
    let root = stewie_oracle::repo_root();
    for (path, file, ctype) in [
        (
            "/program",
            "stewie/server/web/program.html",
            "text/html; charset=utf-8",
        ),
        (
            "/program/snapshot",
            "stewie/server/program_snapshot.json",
            "application/json",
        ),
        ("/landing", "stewie/server/web/landing.html", HTML),
        ("/landing.html", "stewie/server/web/landing.html", HTML),
        ("/viz", "stewie/server/web/viz_haworth.html", HTML),
        (
            "/viz_haworth.html",
            "stewie/server/web/viz_haworth.html",
            HTML,
        ),
    ] {
        let mut req = Request::builder().uri(path).body(Body::empty()).unwrap();
        req.extensions_mut()
            .insert(ConnectInfo(SocketAddr::from(([127, 0, 0, 1], 50000))));
        let r = app.clone().oneshot(req).await.unwrap();
        assert_eq!(r.status().as_u16(), 200, "{path}");
        assert_eq!(r.headers()["content-type"], ctype, "{path}");
        let got = r.into_body().collect().await.unwrap().to_bytes();
        let want = std::fs::read(root.join(file)).unwrap();
        if path == "/program/snapshot" {
            let (g, w): (Value, Value) = (
                serde_json::from_slice(&got).unwrap(),
                serde_json::from_slice(&want).unwrap(),
            );
            assert!(
                w.as_object().is_some_and(|m| !m.is_empty()),
                "vacuity: a real snapshot"
            );
            assert_eq!(g, w, "{path}");
        } else {
            assert_eq!(&got[..], &want[..], "{path}");
        }
    }
    std::fs::remove_dir_all(&dir).unwrap();
}

#[tokio::test]
async fn a_site_whose_bundle_is_not_on_disk_is_not_imported() {
    // SYNTHETIC: an empty samples directory, so no named bundle is present
    let dir = std::env::temp_dir().join(format!("stewie-sites-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(dir.join("samples")).unwrap();
    let env: HashMap<&str, String> = [
        ("STEWIE_API_KEY", "automation-key-0123456789".to_owned()),
        ("STEWIE_DATA_DIR", dir.display().to_string()),
        (
            "STEWIE_SAMPLES_DIR",
            dir.join("samples").display().to_string(),
        ),
    ]
    .into_iter()
    .collect();
    let clock: &'static PinnedClock = Box::leak(Box::new(PinnedClock(Mutex::new(1.8e9))));
    let bytes: &'static SeededBytes = Box::leak(Box::new(SeededBytes {
        seed: Sha256::digest(b"sites").into(),
        n: Mutex::new(0),
    }));
    let app = router(Arc::new(
        AppState::from_env(&|k| env.get(k).cloned(), clock, bytes).unwrap(),
    ));
    let mut req = Request::builder()
        .uri("/sites")
        .header("x-api-key", "automation-key-0123456789")
        .body(Body::empty())
        .unwrap();
    req.extensions_mut()
        .insert(ConnectInfo(SocketAddr::from(([127, 0, 0, 1], 50000))));
    let r = app.oneshot(req).await.unwrap();
    assert_eq!(r.status().as_u16(), 200);
    let v: Value =
        serde_json::from_slice(&r.into_body().collect().await.unwrap().to_bytes()).unwrap();
    let rows = v["sites"].as_array().unwrap();
    assert_eq!(rows.len(), 14, "vacuity: the whole registry");
    assert!(rows.iter().all(|s| s["imported"] == false), "{rows:?}");
    std::fs::remove_dir_all(&dir).unwrap();
}

#[tokio::test]
async fn the_python_configuration_session_replays_with_the_spice_departure() {
    fn norm(v: &mut Value, dir: &str, repo: &str) {
        match v {
            Value::String(s) => *s = s.replace(dir, "{data_dir}").replace(repo, "{repo}"),
            Value::Array(a) => a.iter_mut().for_each(|x| norm(x, dir, repo)),
            Value::Object(m) => m.values_mut().for_each(|x| norm(x, dir, repo)),
            _ => {}
        }
    }
    // the recorded bodies name the session's data directory and this checkout as `{data_dir}` and `{repo}`
    let dir = std::env::temp_dir()
        .join(format!("stewie-http_config_cases-{}", std::process::id()))
        .display()
        .to_string();
    let repo = stewie_oracle::repo_root().display().to_string();
    replay(
        "http_config_cases",
        b"stewie-http-config-oracle",
        |_, step, clock, _| {
            *clock.0.lock().unwrap() = step["clock"].as_f64().unwrap();
        },
        |step, body| {
            norm(body, &dir, &repo);
            // D-R135: the Rust loads no SPICE kernels (its sun is the DE440 pack, D-R131); the Python had them pinned
            if step["request"]["path"] == "/config/full" && step["status"] == 200 {
                assert_eq!(body["data"]["spice_available"], false);
                assert_eq!(step["body"]["data"]["spice_available"], true);
                body["data"]["spice_available"] = json!(true);
            }
        },
    )
    .await;
}

#[tokio::test]
async fn the_python_structures_session_replays_exactly() {
    replay(
        "http_structures_cases",
        b"stewie-http-structures-oracle",
        |_, step, clock, _| {
            *clock.0.lock().unwrap() = step["clock"].as_f64().unwrap();
        },
        |_, _| {},
    )
    .await;
}

#[tokio::test]
async fn the_python_missions_session_replays_exactly() {
    replay(
        "http_missions_cases",
        b"stewie-http-missions-oracle",
        |_, step, clock, _| {
            *clock.0.lock().unwrap() = step["clock"].as_f64().unwrap();
        },
        |_, _| {},
    )
    .await;
}

#[tokio::test]
async fn drafts_and_soils_share_one_autosave_quota() {
    // SYNTHETIC: the Python's _draft_quota (120 per 60 s per identity), shared by PUT /draft and POST /soil
    let (app, dir) = bare_app("autosave", false);
    let send = |method: &str, path: &str, body: &str| {
        let mut req = Request::builder()
            .method(method)
            .uri(path)
            .header("x-api-key", "automation-key-0123456789")
            .header("content-type", "application/json")
            .body(Body::from(body.to_owned()))
            .unwrap();
        req.extensions_mut()
            .insert(ConnectInfo(SocketAddr::from(([127, 0, 0, 1], 50000))));
        let app = app.clone();
        async move {
            let r = app.oneshot(req).await.unwrap();
            let status = r.status().as_u16();
            let v: Value =
                serde_json::from_slice(&r.into_body().collect().await.unwrap().to_bytes()).unwrap();
            (status, v)
        }
    };
    for i in 0..119 {
        assert_eq!(send("PUT", "/draft", "{}").await.0, 200, "draft {i}");
    }
    let soil = r#"{"provenance": "lab", "confidence": "ESTIMATED"}"#;
    assert_eq!(send("POST", "/soil/s", soil).await.0, 200, "the 120th unit");
    let (status, v) = send("PUT", "/draft", "{}").await;
    assert_eq!(
        (status, v["error"].clone()),
        (429, json!("draft autosave quota exceeded; slow down"))
    );
    let (status, v) = send("POST", "/soil/s", soil).await;
    assert_eq!(
        (status, v["error"].clone()),
        (429, json!("soil-save quota exceeded; slow down"))
    );
    std::fs::remove_dir_all(&dir).unwrap();
}

#[tokio::test]
async fn the_python_library_session_replays_with_mtimes_normalised() {
    // a record's mtime-derived `created` differs between hosts; the oracle kept it as `<mtime>` (D-R138)
    fn norm(v: &mut Value) {
        match v {
            Value::Object(m) => {
                m.values_mut().for_each(norm);
                let timed = m
                    .get("type")
                    .and_then(Value::as_str)
                    .is_some_and(|t| ["report", "site", "twin", "dem"].contains(&t));
                if timed && m.get("created").is_some_and(Value::is_f64) {
                    m.insert("created".into(), json!("<mtime>"));
                }
            }
            Value::Array(a) => a.iter_mut().for_each(norm),
            _ => {}
        }
    }
    replay(
        "http_library_cases",
        b"stewie-http-library-oracle",
        |_, step, clock, _| {
            *clock.0.lock().unwrap() = step["clock"].as_f64().unwrap();
        },
        |_, body| norm(body),
    )
    .await;
}

#[tokio::test]
async fn the_python_assets_session_replays_exactly() {
    replay(
        "http_assets_cases",
        b"stewie-http-assets-oracle",
        |_, step, clock, _| {
            *clock.0.lock().unwrap() = step["clock"].as_f64().unwrap();
        },
        |_, _| {},
    )
    .await;
}

#[tokio::test]
async fn every_bundled_file_is_served_as_it_is_on_disk() {
    fn walk(
        base: &std::path::Path,
        d: &std::path::Path,
        out: &mut Vec<(String, std::path::PathBuf)>,
    ) {
        for e in std::fs::read_dir(d).unwrap() {
            let p = e.unwrap().path();
            if p.is_dir() {
                walk(base, &p, out);
            } else {
                let rel = p.strip_prefix(base).unwrap().to_str().unwrap().to_owned();
                out.push((format!("/assets/{rel}"), p));
            }
        }
    }
    // the fonts, icons, cockpit assets and body registry, byte for byte with the Python's media types
    let (app, dir) = bare_app("bundled", false);
    let server = stewie_oracle::repo_root().join("stewie/server");
    let mut files: Vec<(String, std::path::PathBuf)> =
        vec![("/bodies.json".into(), server.join("bodies.json"))];
    for (route, sub) in [("/fonts", "fonts"), ("/icons", "icons")] {
        for e in std::fs::read_dir(server.join(sub)).unwrap() {
            let p = e.unwrap().path();
            files.push((
                format!("{route}/{}", p.file_name().unwrap().to_str().unwrap()),
                p,
            ));
        }
    }
    let assets = server.join("web/assets");
    walk(&assets, &assets, &mut files);
    assert!(
        files.len() > 100,
        "vacuity: the bundle is present ({})",
        files.len()
    );
    for (uri, path) in files {
        let mut req = Request::builder().uri(&uri).body(Body::empty()).unwrap();
        req.extensions_mut()
            .insert(ConnectInfo(SocketAddr::from(([127, 0, 0, 1], 50000))));
        let r = app.clone().oneshot(req).await.unwrap();
        assert_eq!(r.status().as_u16(), 200, "{uri}");
        let want = match path.extension().and_then(|e| e.to_str()) {
            _ if uri.starts_with("/icons/") => "image/png",
            Some("ttf") if uri.starts_with("/fonts/") => "font/ttf",
            _ if uri.starts_with("/fonts/") => "text/plain; charset=utf-8",
            Some("json") => "application/json",
            Some("png") => "image/png",
            Some("js") => "text/javascript; charset=utf-8",
            Some("css") => "text/css; charset=utf-8",
            Some("html") => "text/html; charset=utf-8",
            Some("md") => "text/markdown; charset=utf-8",
            Some("pdf") => "application/pdf",
            Some("wasm") => "application/wasm",
            _ => "application/octet-stream",
        };
        assert_eq!(r.headers()["content-type"], want, "{uri}");
        let got = r.into_body().collect().await.unwrap().to_bytes();
        assert_eq!(&got[..], &std::fs::read(&path).unwrap()[..], "{uri}");
    }
    std::fs::remove_dir_all(&dir).unwrap();
}

#[tokio::test]
async fn the_python_edit_session_replays_with_its_store_rows() {
    replay(
        "http_editsession_cases",
        b"stewie-http-editsession-oracle",
        |_, step, clock, _| {
            *clock.0.lock().unwrap() = step["clock"].as_f64().unwrap();
        },
        |_, _| {},
    )
    .await;
}

/// SYNTHETIC: an app over an existing data dir, with its own settable clock.
fn app_on(dir: &std::path::Path, tag: &str) -> (axum::Router, &'static PinnedClock) {
    let env: HashMap<&str, String> = [
        ("STEWIE_API_KEY", "automation-key-0123456789".to_owned()),
        ("STEWIE_DATA_DIR", dir.display().to_string()),
    ]
    .into_iter()
    .collect();
    let clock: &'static PinnedClock = Box::leak(Box::new(PinnedClock(Mutex::new(1.8e9))));
    let bytes: &'static SeededBytes = Box::leak(Box::new(SeededBytes {
        seed: Sha256::digest(tag.as_bytes()).into(),
        n: Mutex::new(0),
    }));
    let state = AppState::from_env(&|k| env.get(k).cloned(), clock, bytes).unwrap();
    (router(Arc::new(state)), clock)
}

async fn call(app: &axum::Router, method: &str, path: &str, body: Option<Value>) -> (u16, Value) {
    let mut b = Request::builder().method(method).uri(path);
    if body.is_some() {
        b = b.header("content-type", "application/json");
    }
    let mut req = b
        .body(body.map_or_else(Body::empty, |v| Body::from(v.to_string())))
        .unwrap();
    req.extensions_mut()
        .insert(ConnectInfo(SocketAddr::from(([127, 0, 0, 1], 50000))));
    let r = app.clone().oneshot(req).await.unwrap();
    let status = r.status().as_u16();
    let v = serde_json::from_slice(&r.into_body().collect().await.unwrap().to_bytes()).unwrap();
    (status, v)
}

#[tokio::test]
async fn sessions_the_python_stored_read_back_through_the_rust_routes() {
    // the oracle's own rows, inserted with the Python's DDL, then read through the routes
    let fx = stewie_oracle::load("http_editsession_cases")
        .unwrap()
        .payload;
    let dir = std::env::temp_dir().join(format!("stewie-es-py-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let (app, _) = app_on(&dir, "es-py");
    assert_eq!(call(&app, "GET", "/edit/session/none", None).await.0, 404); // opens the store, makes the schema
    let mut db = sqlx::SqliteConnection::connect(&format!(
        "sqlite://{}",
        dir.join("edit_session.db").display()
    ))
    .await
    .unwrap();
    for r in fx["db_rows"]["edit_session"].as_array().unwrap() {
        let mut q = sqlx::query("INSERT INTO edit_session VALUES (?, ?, ?, ?, ?, ?, ?, ?)");
        q = q
            .bind(r[0].as_str())
            .bind(r[1].as_str())
            .bind(r[2].as_i64())
            .bind(r[3].as_f64());
        q = q
            .bind(r[4].as_i64())
            .bind(r[5].as_i64())
            .bind(r[6].as_str())
            .bind(r[7].as_str());
        q.execute(&mut db).await.unwrap();
    }
    for r in fx["db_rows"]["edit_audit"].as_array().unwrap() {
        let mut q = sqlx::query("INSERT INTO edit_audit VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)");
        q = q
            .bind(r[0].as_i64())
            .bind(r[1].as_str())
            .bind(r[2].as_i64())
            .bind(r[3].as_str());
        q = q
            .bind(r[4].as_str())
            .bind(r[5].as_str())
            .bind(r[6].as_str())
            .bind(r[7].as_str());
        q = q
            .bind(r[8].as_f64())
            .bind(r[9].as_i64())
            .bind(r[10].as_str());
        q.execute(&mut db).await.unwrap();
    }
    // the oracle's last full read of the authored session is its final state
    let step = fx["steps"]
        .as_array()
        .unwrap()
        .iter()
        .find(|s| {
            s["request"]["method"] == "GET"
                && s["status"] == 200
                && s["body"]["features"]
                    .as_array()
                    .is_some_and(|f| f.len() > 10)
        })
        .unwrap();
    let path = step["request"]["path"].as_str().unwrap();
    let (status, body) = call(&app, "GET", path, None).await;
    assert_eq!(status, 200);
    assert_eq!(body, step["body"], "{path}");
    std::fs::remove_dir_all(&dir).unwrap();
}

#[tokio::test]
async fn an_edit_session_survives_a_restart() {
    let dir = std::env::temp_dir().join(format!("stewie-es-restart-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let (app, _) = app_on(&dir, "es-restart");
    let sid = call(&app, "POST", "/edit/session", None).await.1["session"]
        .as_str()
        .unwrap()
        .to_owned();
    let ko = json!({"kind": "circle", "cx": 1, "cy": 2, "r": 3}); // SYNTHETIC
    assert_eq!(
        call(
            &app,
            "POST",
            &format!("/edit/session/{sid}/keepout"),
            Some(ko)
        )
        .await
        .0,
        200
    );
    let before = call(&app, "GET", &format!("/edit/session/{sid}"), None)
        .await
        .1;
    drop(app);
    let (again, _) = app_on(&dir, "es-restart-2");
    let (status, after) = call(&again, "GET", &format!("/edit/session/{sid}"), None).await;
    assert_eq!((status, &after), (200, &before));
    let (status, undone) = call(&again, "POST", &format!("/edit/session/{sid}/undo"), None).await;
    assert_eq!((status, undone["features"].clone()), (200, json!([])));
    std::fs::remove_dir_all(&dir).unwrap();
}

#[tokio::test]
async fn a_full_store_evicts_only_an_empty_session_and_refuses_when_none_is() {
    // SYNTHETIC: 512 sessions (the Python's MAX_SESSIONS), created one second apart so "oldest" is defined
    let dir = std::env::temp_dir().join(format!("stewie-es-cap-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let (app, clock) = app_on(&dir, "es-cap");
    let mut sids = Vec::new();
    for _ in 0..512 {
        *clock.0.lock().unwrap() += 1.0;
        sids.push(
            call(&app, "POST", "/edit/session", None).await.1["session"]
                .as_str()
                .unwrap()
                .to_owned(),
        );
    }
    let ko = json!({"kind": "circle", "cx": 0, "cy": 0, "r": 1});
    for sid in &sids[..2] {
        assert_eq!(
            call(
                &app,
                "POST",
                &format!("/edit/session/{sid}/keepout"),
                Some(ko.clone())
            )
            .await
            .0,
            200
        );
    }
    *clock.0.lock().unwrap() += 1.0;
    assert_eq!(call(&app, "POST", "/edit/session", None).await.0, 200);
    // the two oldest hold work and stay; the oldest empty one (the third) made room
    assert_eq!(
        call(&app, "GET", &format!("/edit/session/{}", sids[0]), None)
            .await
            .0,
        200
    );
    assert_eq!(
        call(&app, "GET", &format!("/edit/session/{}", sids[2]), None)
            .await
            .0,
        404
    );
    // with every session holding work, a new one is refused rather than evict anyone
    let mut db = sqlx::SqliteConnection::connect(&format!(
        "sqlite://{}",
        dir.join("edit_session.db").display()
    ))
    .await
    .unwrap();
    sqlx::query("UPDATE edit_session SET features = '{\"ko1\": {}}'")
        .execute(&mut db)
        .await
        .unwrap();
    let (status, body) = call(&app, "POST", "/edit/session", None).await;
    assert_eq!(status, 503, "{body}");
    assert_eq!(
        body["error"],
        "edit-session store is full (512/512) and every session holds authored features; refusing to delete an \
         operator's geometry to make room"
    );
    std::fs::remove_dir_all(&dir).unwrap();
}

#[tokio::test(flavor = "multi_thread", worker_threads = 8)]
async fn concurrent_edits_to_one_session_all_land_in_order() {
    // SYNTHETIC: twenty simultaneous creates; each edit is one immediate transaction, so none is lost or refused
    let dir = std::env::temp_dir().join(format!("stewie-es-conc-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let (app, _) = app_on(&dir, "es-conc");
    let sid = call(&app, "POST", "/edit/session", None).await.1["session"]
        .as_str()
        .unwrap()
        .to_owned();
    let tasks: Vec<_> = (0..20)
        .map(|i| {
            let (app, path) = (app.clone(), format!("/edit/session/{sid}/keepout"));
            tokio::spawn(async move {
                call(
                    &app,
                    "POST",
                    &path,
                    Some(json!({"kind": "circle", "cx": i, "cy": 0, "r": 1})),
                )
                .await
            })
        })
        .collect();
    for t in tasks {
        let (status, body) = t.await.unwrap();
        assert_eq!(status, 200, "{body}");
    }
    let (_, state) = call(&app, "GET", &format!("/edit/session/{sid}"), None).await;
    assert_eq!(state["version"], 20);
    let fids: Vec<&str> = state["features"]
        .as_array()
        .unwrap()
        .iter()
        .map(|f| f["fid"].as_str().unwrap())
        .collect();
    assert_eq!(fids, (1..=20).map(|i| format!("ko{i}")).collect::<Vec<_>>());
    std::fs::remove_dir_all(&dir).unwrap();
}

#[tokio::test]
async fn the_python_models_session_replays_exactly() {
    replay(
        "http_models_cases",
        b"stewie-http-models-oracle",
        |_, step, clock, _| {
            *clock.0.lock().unwrap() = step["clock"].as_f64().unwrap();
        },
        |_, _| {},
    )
    .await;
}

#[tokio::test]
async fn the_python_plan_math_session_replays_exactly() {
    replay(
        "http_planmath_cases",
        b"stewie-http-planmath-oracle",
        |_, step, clock, _| {
            *clock.0.lock().unwrap() = step["clock"].as_f64().unwrap();
        },
        |_, _| {},
    )
    .await;
}

/// D-R96: the Rust plan IR splits an action one charge cannot finish into `part: [k, n]` actions that the Python
/// keeps whole. Check each split merges back into the Python's action (same op, site, destination and orders; the
/// parts' mass, energy, duration and haul summing to its, to the parts' 0.1 rounding), and its precedence maps onto
/// the Python's; then put the Python's action, ids, precedence and (content-hashed, so changed) `plan_id` in place,
/// so everything else compares exactly.
fn merge_split_ir(want: &Value, got: &mut Value) {
    let Some(actions) = got["actions"].as_array() else {
        return;
    };
    if !actions.iter().any(|a| a.get("part").is_some()) {
        return;
    }
    let num = |v: &Value| v.as_f64().unwrap();
    let mut merged: Vec<Value> = Vec::new();
    let mut idmap = Vec::new();
    let mut sums = [0.0; 4];
    for a in actions {
        let Some(part) = a.get("part") else {
            idmap.push(merged.len());
            let mut whole = a.clone();
            whole["id"] = json!(merged.len());
            merged.push(whole);
            continue;
        };
        let (k, n) = (part[0].as_u64().unwrap(), part[1].as_u64().unwrap());
        idmap.push(merged.len());
        if k == 1 {
            sums = [0.0; 4];
        }
        for (s, v) in sums.iter_mut().zip([
            &a["mass_kg"],
            &a["expect"]["energy_J"],
            &a["expect"]["duration_s"],
            &a["haul_m"],
        ]) {
            *s += num(v);
        }
        if k == n {
            let py = &want["actions"][merged.len()];
            for key in ["op", "vehicle", "site", "dest", "actions"] {
                assert_eq!(a[key], py[key], "split action {}: {key}", merged.len());
            }
            #[allow(clippy::cast_precision_loss)]
            let tol = 0.05 * n as f64 + 1e-9;
            for (s, v) in sums.iter().zip([
                &py["mass_kg"],
                &py["expect"]["energy_J"],
                &py["expect"]["duration_s"],
                &py["haul_m"],
            ]) {
                assert!(
                    (s - num(v)).abs() <= tol,
                    "split action {}: parts sum {s} vs {v}",
                    merged.len()
                );
            }
            merged.push(py.clone());
        }
    }
    let at = |v: &Value| idmap[usize::try_from(v.as_u64().unwrap()).unwrap()];
    let mut prec: Vec<(usize, usize)> = got["precedence"]
        .as_array()
        .unwrap()
        .iter()
        .map(|p| (at(&p[0]), at(&p[1])))
        .collect();
    prec.sort_unstable();
    prec.dedup();
    assert_eq!(json!(prec), want["precedence"], "split IR precedence");
    got["actions"] = json!(merged);
    got["precedence"] = want["precedence"].clone();
    got["plan_id"] = want["plan_id"].clone();
}

#[tokio::test]
async fn the_python_plan_session_replays_exactly() {
    replay(
        "http_plan_cases",
        b"stewie-http-plan-oracle",
        |_, step, clock, _| {
            *clock.0.lock().unwrap() = step["clock"].as_f64().unwrap();
        },
        |step, body| {
            // the source commit and package version name the build (the fixture records placeholders)
            if body.get("plan_result").is_some() {
                // a mass drift is the residue of two ~1e5 kg sums: to 1e-3 kg, as the acceptance oracles
                for path in [
                    "/validation/mass_drift_kg",
                    "/ordered_acceptance/mass_drift_kg",
                ] {
                    let want = &step["body"].pointer(path).unwrap();
                    let got = body.pointer_mut(path).unwrap();
                    if (got.as_f64().unwrap() - want.as_f64().unwrap()).abs() <= 1e-3 {
                        *got = (*want).clone();
                    }
                }
                merge_split_ir(&step["body"]["plan_ir"], &mut body["plan_ir"]);
                for path in ["/provenance", "/timeline/provenance", "/plan_ir/provenance"] {
                    // an H-03 suppressed IR carries none
                    let Some(prov) = body.pointer_mut(path) else {
                        continue;
                    };
                    prov["commit"] = json!("<commit>");
                    prov["version"] = json!("<version>");
                }
            }
        },
    )
    .await;
}

#[tokio::test]
async fn the_python_resync_session_replays_exactly() {
    replay(
        "http_resync_cases",
        b"stewie-http-resync-oracle",
        |_, step, clock, _| {
            *clock.0.lock().unwrap() = step["clock"].as_f64().unwrap();
        },
        |_, body| {
            // each future's wall time is measured (the fixture records a placeholder)
            let futures = body.get_mut("futures").and_then(Value::as_array_mut);
            for f in futures.into_iter().flatten() {
                assert!(
                    f["wall_s"].as_f64().is_some_and(|w| w >= 0.0),
                    "wall_s {}",
                    f["wall_s"]
                );
                f["wall_s"] = json!("<wall_s>");
            }
        },
    )
    .await;
}

#[tokio::test]
async fn the_python_layers_session_replays_exactly() {
    replay(
        "http_layers_cases",
        b"stewie-http-layers-oracle",
        |i, step, clock, dir| {
            *clock.0.lock().unwrap() = step["clock"].as_f64().unwrap();
            // the oracle planted this traffic memory before its second traffic request (SYNTHETIC, labelled)
            if step["request"]["path"] == "/layers/raster/traffic.png" && i > 7 {
                let mut tm = stewie_twin::traffic_memory::TrafficMemory::new(
                    "haworth",
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

/// A GET's status, content type and raw body.
async fn get_raw(app: &axum::Router, path: &str) -> (u16, String, Vec<u8>) {
    let mut req = Request::builder().uri(path).body(Body::empty()).unwrap();
    req.extensions_mut()
        .insert(ConnectInfo(SocketAddr::from(([127, 0, 0, 1], 50000))));
    let r = app.clone().oneshot(req).await.unwrap();
    let ctype = r
        .headers()
        .get("content-type")
        .map_or_else(String::new, |v| v.to_str().unwrap().to_owned());
    (
        r.status().as_u16(),
        ctype,
        r.into_body().collect().await.unwrap().to_bytes().to_vec(),
    )
}

#[tokio::test]
async fn the_cockpit_pages_and_the_api_docs_are_served_as_the_python() {
    // SYNTHETIC: a stand-in React build (labelled), so the test does not depend on a local `npm run build`
    let dir = std::env::temp_dir().join(format!("stewie-pages-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    let dist = dir.join("dist");
    std::fs::create_dir_all(dist.join("assets")).unwrap();
    std::fs::write(dist.join("index.html"), "<!doctype html>SYNTHETIC shell").unwrap();
    std::fs::write(dist.join("assets/app.js"), "/* SYNTHETIC bundle */").unwrap();
    std::fs::write(dir.join("secret.txt"), "outside the build").unwrap();
    let env: HashMap<&str, String> = [
        ("STEWIE_API_KEY", "automation-key-0123456789".to_owned()),
        ("STEWIE_DATA_DIR", dir.display().to_string()),
        ("STEWIE_APP_DIST", dist.display().to_string()),
    ]
    .into_iter()
    .collect();
    let clock: &'static PinnedClock = Box::leak(Box::new(PinnedClock(Mutex::new(1.8e9))));
    let bytes: &'static SeededBytes = Box::leak(Box::new(SeededBytes {
        seed: Sha256::digest(b"pages").into(),
        n: Mutex::new(0),
    }));
    let app = router(Arc::new(
        AppState::from_env(&|k| env.get(k).cloned(), clock, bytes).unwrap(),
    ));
    let cockpit = std::fs::read(
        std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../stewie/server/index.html"),
    )
    .unwrap();
    for p in ["/", "/index.html"] {
        assert_eq!(
            get_raw(&app, p).await,
            (200, "text/html; charset=utf-8".to_owned(), cockpit.clone()),
            "{p}"
        );
    }
    let shell = (
        200,
        "text/html; charset=utf-8".to_owned(),
        b"<!doctype html>SYNTHETIC shell".to_vec(),
    );
    for p in [
        "/app",
        "/app/",
        "/app/missions/7",
        "/app/assets/missing.js",
        "/app/assets/../../secret.txt",
    ] {
        assert_eq!(get_raw(&app, p).await, shell, "{p}");
    }
    let (s, ct, b) = get_raw(&app, "/app/assets/app.js").await;
    assert_eq!(
        (s, b.as_slice()),
        (200, b"/* SYNTHETIC bundle */".as_slice())
    );
    assert!(ct.starts_with("text/javascript"), "{ct}");
    // the docs page reads the schema, which names the API's routes
    let (s, _, page) = get_raw(&app, "/docs").await;
    assert!(
        s == 200
            && String::from_utf8(page)
                .unwrap()
                .contains("url: '/openapi.json'")
    );
    let (s, ct, schema) = get_raw(&app, "/openapi.json").await;
    let schema: Value = serde_json::from_slice(&schema).unwrap();
    assert_eq!((s, ct.as_str()), (200, "application/json"));
    assert!(
        schema["paths"]["/plan"]["post"].is_object()
            && schema["paths"].as_object().unwrap().len() > 150
    );
    // no build: the Python's 404
    std::fs::remove_dir_all(&dist).unwrap();
    let (s, _, b) = get_raw(&app, "/app").await;
    let b: Value = serde_json::from_slice(&b).unwrap();
    assert_eq!(
        (s, b),
        (
            404,
            json!({"ok": false, "error": "cockpit app build not present"})
        )
    );
}

#[tokio::test]
async fn the_heavy_quota_refuses_after_auth_and_before_validation() {
    // SYNTHETIC: a quota of one; the Python checks it after auth and before the model, so a bad body counts
    let dir = std::env::temp_dir().join(format!("stewie-heavy-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let env: HashMap<&str, String> = [
        ("STEWIE_API_KEY", "automation-key-0123456789".to_owned()),
        ("STEWIE_DATA_DIR", dir.display().to_string()),
        ("STEWIE_HEAVY_QUOTA_MAX", "1".to_owned()),
    ]
    .into_iter()
    .collect();
    let clock: &'static PinnedClock = Box::leak(Box::new(PinnedClock(Mutex::new(1.8e9))));
    let bytes: &'static SeededBytes = Box::leak(Box::new(SeededBytes {
        seed: Sha256::digest(b"heavy").into(),
        n: Mutex::new(0),
    }));
    let app = router(Arc::new(
        AppState::from_env(&|k| env.get(k).cloned(), clock, bytes).unwrap(),
    ));
    let bad = json!({"vehicles": 0});
    let (s1, b1) = post(&app, "/plan/math", bad.clone()).await;
    assert_eq!(
        (s1, b1["error"].clone()),
        (
            400,
            json!("vehicles: Input should be greater than or equal to 1")
        )
    );
    let (s2, b2) = post(&app, "/plan/math", bad).await;
    assert_eq!(
        (s2, b2["error"].clone()),
        (
            429,
            json!("per-identity compute quota exceeded for heavy planning; slow down")
        )
    );
    std::fs::remove_dir_all(&dir).unwrap();
}

#[test]
fn the_endurance_report_matches_the_python_on_the_real_haworth_dem() {
    let fx = stewie_oracle::load("endurance_cases").unwrap().payload;
    let dir = std::env::temp_dir().join(format!("stewie-endurance-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let cfg = stewie_oracle::repo_root()
        .join("deploy/planner.json")
        .display()
        .to_string();
    let env: HashMap<&str, String> = [
        ("STEWIE_API_KEY", "automation-key-0123456789".to_owned()),
        ("STEWIE_DATA_DIR", dir.display().to_string()),
        ("STEWIE_PLANNER_CONFIG", cfg),
    ]
    .into_iter()
    .collect();
    let clock: &'static PinnedClock = Box::leak(Box::new(PinnedClock(Mutex::new(1.8e9))));
    let bytes: &'static SeededBytes = Box::leak(Box::new(SeededBytes {
        seed: Sha256::digest(b"endurance").into(),
        n: Mutex::new(0),
    }));
    let st = AppState::from_env(&|k| env.get(k).cloned(), clock, bytes).unwrap();
    let (site, origin) = st.terrain.moon_dem("haworth").unwrap();
    assert_eq!(
        json!([origin.0, origin.1]),
        fx["origin"],
        "the flattest anchor"
    );
    let dem_at = |o: (f64, f64)| stewie_traverse::route::Dem {
        z: &site.z,
        width: site.cols,
        height: site.rows,
        cell_m: site.cell_m,
        origin: o,
    };
    let cases = fx["cases"].as_array().unwrap();
    assert!(
        cases.iter().any(|c| c["result"].get("reach").is_some()),
        "vacuity: a reach field"
    );
    for (i, c) in cases.iter().enumerate() {
        let m = st.planning.mission(&c["payload"]).unwrap();
        let inputs = st.planning.inputs(&m).unwrap();
        let o = c
            .get("origin")
            .map_or(origin, |o| (o[0].as_f64().unwrap(), o[1].as_f64().unwrap()));
        let dem = dem_at(o);
        let got = st
            .planning
            .endurance(
                &m,
                &inputs,
                c["site"].is_string().then_some(&dem),
                c["power_site"].as_str().unwrap(),
                c["temp_c"].as_f64(),
            )
            .unwrap();
        if let Err(e) = close(&got, &c["result"], &format!("case {i}")) {
            panic!("{e}");
        }
    }
    std::fs::remove_dir_all(&dir).unwrap();
}

#[test]
fn the_plan_timeline_and_provenance_match_the_python_on_the_real_haworth_dem() {
    let fx = stewie_oracle::load("timeline_cases").unwrap().payload;
    let dir = std::env::temp_dir().join(format!("stewie-timeline-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let cfg = stewie_oracle::repo_root()
        .join("deploy/planner.json")
        .display()
        .to_string();
    let env: HashMap<&str, String> = [
        ("STEWIE_API_KEY", "automation-key-0123456789".to_owned()),
        ("STEWIE_DATA_DIR", dir.display().to_string()),
        ("STEWIE_PLANNER_CONFIG", cfg),
    ]
    .into_iter()
    .collect();
    let clock: &'static PinnedClock = Box::leak(Box::new(PinnedClock(Mutex::new(1.8e9))));
    let bytes: &'static SeededBytes = Box::leak(Box::new(SeededBytes {
        seed: Sha256::digest(b"timeline").into(),
        n: Mutex::new(0),
    }));
    let st = AppState::from_env(&|k| env.get(k).cloned(), clock, bytes).unwrap();
    let (site, origin) = st.terrain.moon_dem("haworth").unwrap();
    assert_eq!(
        json!([origin.0, origin.1]),
        fx["origin"],
        "the flattest anchor"
    );
    let dem = stewie_traverse::route::Dem {
        z: &site.z,
        width: site.cols,
        height: site.rows,
        cell_m: site.cell_m,
        origin,
    };
    let cases = fx["cases"].as_array().unwrap();
    assert!(
        cases.iter().any(|c| c["vehicles"] == 2),
        "vacuity: a fleet plan"
    );
    for (i, c) in cases.iter().enumerate() {
        let m = st.planning.mission(&c["payload"]).unwrap();
        let inputs = st.planning.inputs(&m).unwrap();
        let (algorithm, objective) = (
            c["algorithm"].as_str().unwrap(),
            c["objective"].as_str().unwrap(),
        );
        let vehicles = usize::try_from(c["vehicles"].as_u64().unwrap()).unwrap();
        let cfg = stewie_plan::assemble::PlanConfig {
            algorithm,
            objective,
            vehicles,
            idle_power_w: inputs.idle_power_w,
            reallocate_stranded: true,
        };
        let plan = stewie_plan::assemble::plan_and_simulate(
            &m,
            &st.planning.fleet,
            &inputs.build(dem, 25.0),
            &cfg,
        )
        .unwrap();
        let req = stewie_plan::provenance::Request {
            origin,
            algorithm,
            objective,
            vehicles,
            default_return_buffer_frac: st
                .planning
                .config
                .as_ref()
                .unwrap()
                .report
                .default_return_buffer_frac,
        };
        let canon = stewie_plan::provenance::canonical(&m, &req, &st.planning.provenance).unwrap();
        assert_eq!(
            canon,
            c["canon"].as_str().unwrap(),
            "case {i}: the hashed text"
        );
        let got = st
            .planning
            .timeline(
                &m,
                &plan,
                origin,
                (algorithm, objective, vehicles),
                "<commit>",
            )
            .unwrap();
        if let Err(e) = close(&got, &c["timeline"], &format!("case {i}")) {
            panic!("{e}");
        }
    }
    std::fs::remove_dir_all(&dir).unwrap();
}

#[test]
fn the_closed_loop_autonomy_overlay_matches_the_python_on_the_real_haworth_dem() {
    let fx = stewie_oracle::load("autonomy_cases").unwrap().payload;
    let dir = std::env::temp_dir().join(format!("stewie-autonomy-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let cfg = stewie_oracle::repo_root()
        .join("deploy/planner.json")
        .display()
        .to_string();
    let env: HashMap<&str, String> = [
        ("STEWIE_API_KEY", "automation-key-0123456789".to_owned()),
        ("STEWIE_DATA_DIR", dir.display().to_string()),
        ("STEWIE_PLANNER_CONFIG", cfg),
    ]
    .into_iter()
    .collect();
    let clock: &'static PinnedClock = Box::leak(Box::new(PinnedClock(Mutex::new(1.8e9))));
    let bytes: &'static SeededBytes = Box::leak(Box::new(SeededBytes {
        seed: Sha256::digest(b"autonomy").into(),
        n: Mutex::new(0),
    }));
    let st = AppState::from_env(&|k| env.get(k).cloned(), clock, bytes).unwrap();
    let (site, origin) = st.terrain.moon_dem("haworth").unwrap();
    assert_eq!(
        json!([origin.0, origin.1]),
        fx["origin"],
        "the flattest anchor"
    );
    let dem = stewie_traverse::route::Dem {
        z: &site.z,
        width: site.cols,
        height: site.rows,
        cell_m: site.cell_m,
        origin,
    };
    for (i, c) in fx["cases"].as_array().unwrap().iter().enumerate() {
        let m = st.planning.mission(&c["payload"]).unwrap();
        let inputs = st.planning.inputs(&m).unwrap();
        let cfg = stewie_plan::assemble::PlanConfig {
            algorithm: c["algorithm"].as_str().unwrap(),
            objective: c["objective"].as_str().unwrap(),
            vehicles: 1,
            idle_power_w: inputs.idle_power_w,
            reallocate_stranded: true,
        };
        let plan = stewie_plan::assemble::plan_and_simulate(
            &m,
            &st.planning.fleet,
            &inputs.build(dem, 25.0),
            &cfg,
        )
        .unwrap();
        let (autonomy, perception) = st
            .planning
            .autonomy_perception(&m, &inputs, &plan, &dem)
            .unwrap();
        for (got, key) in [(autonomy, "autonomy"), (perception, "perception")] {
            if let Err(e) = close(&got, &c[key], &format!("case {i} {key}")) {
                panic!("{e}");
            }
        }
    }
    std::fs::remove_dir_all(&dir).unwrap();
}

#[test]
fn the_dem_scan_match_fix_matches_the_python_on_the_real_haworth_dem() {
    let fx = stewie_oracle::load("dem_fix_cases").unwrap().payload;
    let dir = std::env::temp_dir().join(format!("stewie-demfix-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let env: HashMap<&str, String> = [
        ("STEWIE_API_KEY", "automation-key-0123456789".to_owned()),
        ("STEWIE_DATA_DIR", dir.display().to_string()),
    ]
    .into_iter()
    .collect();
    let clock: &'static PinnedClock = Box::leak(Box::new(PinnedClock(Mutex::new(1.8e9))));
    let bytes: &'static SeededBytes = Box::leak(Box::new(SeededBytes {
        seed: Sha256::digest(b"demfix").into(),
        n: Mutex::new(0),
    }));
    let st = AppState::from_env(&|k| env.get(k).cloned(), clock, bytes).unwrap();
    let (site, origin) = st.terrain.moon_dem("haworth").unwrap();
    assert_eq!(
        json!([origin.0, origin.1]),
        fx["origin"],
        "the flattest anchor"
    );
    let dem = stewie_traverse::route::Dem {
        z: &site.z,
        width: site.cols,
        height: site.rows,
        cell_m: site.cell_m,
        origin,
    };
    let xy = |v: &Value| (v[0].as_f64().unwrap(), v[1].as_f64().unwrap());
    let cases = fx["cases"].as_array().unwrap();
    assert!(
        cases.iter().any(|c| c["fix"].is_null()),
        "vacuity: an abstention"
    );
    for (i, c) in cases.iter().enumerate() {
        let got = stewie_plan::autonomy::dem_position_fix(&dem, xy(&c["pose"]), xy(&c["guess"]), 0.10).map(|f| {
            json!({"xy": [f.xy.0, f.xy.1], "sigma": f.sigma, "confidence": f.confidence,
                   "residual_rmse_m": f.residual_rmse_m, "shift_cells": [f.shift_cells.0, f.shift_cells.1]})
        });
        if let Err(e) = close(&json!(got), &c["fix"], &format!("case {i}")) {
            panic!("{e}");
        }
    }
    std::fs::remove_dir_all(&dir).unwrap();
}
