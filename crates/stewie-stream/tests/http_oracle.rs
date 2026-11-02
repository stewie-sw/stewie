//! RW-51d: the Python stream service's HTTP session (`stream_http_cases`: open, token-gated and rate-limited, over
//! the real `samples/lunar_dem` bundles and SYNTHETIC saved bags and routes) replays exactly through the Rust
//! service: every status, media type and body (a preview's grid by the sha256 of its float64 bytes, a file by its
//! sha256).

use std::collections::HashMap;
use std::net::SocketAddr;
use std::sync::{Arc, Mutex};

use axum::body::Body;
use axum::extract::ConnectInfo;
use axum::http::Request;
use http_body_util::BodyExt as _;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use stewie_stream::app::{Config, Stream, router};
use tower::ServiceExt as _;

fn hex(b: &[u8]) -> String {
    Sha256::digest(b).iter().fold(String::new(), |mut out, x| {
        use std::fmt::Write as _;
        let _ = write!(out, "{x:02x}");
        out
    })
}

#[tokio::test]
async fn the_python_stream_session_replays_exactly() {
    let fx = stewie_oracle::load("stream_http_cases").unwrap().payload;
    let repo = std::fs::canonicalize(stewie_oracle::repo_root()).unwrap();
    let tmp = std::env::temp_dir().join(format!("stewie-stream-http-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&tmp);
    for (rel, text) in fx["seed_files"].as_object().unwrap() {
        let p = tmp.join(rel);
        std::fs::create_dir_all(p.parent().unwrap()).unwrap();
        std::fs::write(p, text.as_str().unwrap()).unwrap();
    }
    let vars: Arc<Mutex<HashMap<String, String>>> = Arc::default();
    let env = {
        let vars = Arc::clone(&vars);
        Arc::new(move |k: &str| vars.lock().unwrap().get(k).cloned())
    };
    let fresh = || {
        let mut cfg = Config::for_checkout(&repo, env.clone());
        (cfg.bags_dir, cfg.routes_dir) = (tmp.join("viz2_bags"), tmp.join("viz2_routes"));
        router(Arc::new(Stream::new(cfg)))
    };
    let mut phase = String::new();
    let mut app = fresh();
    let repo_s = repo.display().to_string();
    for (i, step) in fx["steps"].as_array().unwrap().iter().enumerate() {
        if step["phase"] != phase.as_str() {
            phase = step["phase"].as_str().unwrap().to_owned();
            let mut v = vars.lock().unwrap();
            v.clear();
            match phase.as_str() {
                "token" => drop(v.insert(
                    "VIZ2_STREAM_TOKEN".into(),
                    "SYNTHETIC-stream-token-0123".into(),
                )),
                "rate" => drop(v.insert("VIZ2_STREAM_MAX_CONN_PER_MIN".into(), "3".into())),
                _ => {}
            }
            drop(v);
            app = fresh();
        }
        let url = step["url"].as_str().unwrap();
        let tag = format!("step {i} {phase} {} {url}", step["method"]);
        let mut req = Request::builder()
            .method(step["method"].as_str().unwrap())
            .uri(url)
            .body(Body::empty())
            .unwrap();
        // SYNTHETIC peer address (labelled): one remote client for the whole session
        req.extensions_mut()
            .insert(ConnectInfo(SocketAddr::from(([203, 0, 113, 9], 50000))));
        let r = app.clone().oneshot(req).await.unwrap();
        assert_eq!(
            r.status().as_u16(),
            u16::try_from(step["status"].as_u64().unwrap()).unwrap(),
            "{tag}"
        );
        let ctype = r
            .headers()
            .get("content-type")
            .map(|v| v.to_str().unwrap().to_owned())
            .unwrap_or_default();
        assert_eq!(ctype, step["content_type"].as_str().unwrap(), "{tag}");
        let bytes = r.into_body().collect().await.unwrap().to_bytes();
        if let Some(want) = step.get("body_sha256") {
            assert_eq!(hex(&bytes), want.as_str().unwrap(), "{tag}");
            continue;
        }
        let mut body: Value = serde_json::from_slice(&bytes).unwrap();
        let grid = body
            .get("z")
            .is_some_and(|z| z.as_array().is_some_and(|a| !a.is_empty()));
        if let Some(z) = body
            .as_object_mut()
            .filter(|_| grid)
            .and_then(|o| o.remove("z"))
        {
            let z: Vec<u8> = z
                .as_array()
                .unwrap()
                .iter()
                .flat_map(|x| x.as_f64().unwrap().to_le_bytes())
                .collect();
            body["z_len"] = json!(z.len() / 8);
            body["z_sha256"] = json!(hex(&z));
        }
        let text = body.to_string().replace(&repo_s, "{repo}");
        let body: Value = serde_json::from_str(&text).unwrap();
        assert_eq!(body, step["body"], "{tag}");
    }
    assert_eq!(phase, "rate", "vacuity: all three phases replayed");
    std::fs::remove_dir_all(&tmp).unwrap();
}
