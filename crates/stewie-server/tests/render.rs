//! RW-51b: the select-area render. The crop (scipy's zoom, the datum zero-based) and the pad flatten on the real
//! Haworth bundle equal the Python's (`render_earthwork_cases`, 1e-9) at every pick, and `POST /render` drives the
//! Godot renderer plugin: with Godot configured it answers the composed BEFORE | AFTER figure and the earthwork;
//! without it (CI has no GPU) it is a 503, as with no plugin installed.

use std::collections::HashMap;
use std::net::SocketAddr;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use axum::body::Body;
use axum::extract::ConnectInfo;
use axum::http::Request;
use http_body_util::BodyExt as _;
use serde_json::{Value, json};
use stewie_physics::column::Regolith;
use stewie_server::app::{AppState, router};
use stewie_server::render_routes::{crop_window, plan_flatten};
use stewie_server::{Clock, Entropy};
use tower::ServiceExt as _;

fn repo() -> PathBuf {
    stewie_oracle::repo_root()
}

fn regolith() -> Regolith {
    let (bodies, base) = stewie_physics::soil::bundled();
    Regolith::new(
        bodies.get("moon").and_then(|b| b.bulk_density).unwrap(),
        &base,
    )
}

fn close(got: f64, want: f64, what: &str) {
    assert!(
        (got - want).abs() <= 1e-9 * want.abs().max(1.0),
        "{what}: {got} vs {want}"
    );
}

#[test]
fn the_crop_and_flatten_equal_the_pythons() {
    let fx = stewie_oracle::load("render_earthwork_cases")
        .unwrap()
        .payload;
    let r = regolith();
    let (full, _) = stewie_physics::worksite::coarse_base_from_bundle(
        &repo().join("samples/lunar_dem/haworth_10km_5m"),
        &r,
    )
    .unwrap();
    for c in fx["cases"].as_array().unwrap() {
        let f = |k: &str| c[k].as_f64().unwrap();
        let tag = format!("u={} v={} pad={}", f("u"), f("v"), f("pad_frac"));
        let mut cs = crop_window(&full, f("u"), f("v"), &r).unwrap();
        assert_eq!((cs.height(), cs.width()), (100, 100), "{tag}");
        close(cs.cell_m(), f("cell_m"), &tag);
        let h0 = cs.derive_height();
        close(h0.iter().sum(), f("h0_sum"), &format!("{tag} h0 sum"));
        for (got, want) in [h0[0], h0[99], h0[9900], h0[9999]]
            .iter()
            .zip(c["h0_corners"].as_array().unwrap())
        {
            close(*got, want.as_f64().unwrap(), &format!("{tag} h0 corner"));
        }
        let plan = plan_flatten(&mut cs, f("pad_frac"), &r).unwrap();
        for (got, k) in [
            (plan.target, "target"),
            (plan.cut_kg, "cut_kg"),
            (plan.fill_kg, "fill_kg"),
            (plan.cut_vol_m3, "cut_vol_m3"),
            (plan.fill_vol_m3, "fill_vol_m3"),
            (cs.drum_inventory(), "drum_kg"),
        ] {
            close(got, f(k), &format!("{tag} {k}"));
        }
        let h1 = cs.derive_height();
        close(h1.iter().sum(), f("h1_sum"), &format!("{tag} h1 sum"));
        close(
            h1[50 * 100 + 50],
            f("h1_center"),
            &format!("{tag} h1 centre"),
        );
        if let Some(full_h1) = c.get("h1").and_then(Value::as_array) {
            for (i, (got, want)) in h1.iter().zip(full_h1).enumerate() {
                close(*got, want.as_f64().unwrap(), &format!("{tag} h1[{i}]"));
            }
        }
    }
}

#[derive(Debug)]
struct Pinned(Mutex<f64>);
impl Clock for Pinned {
    fn now(&self) -> f64 {
        *self.0.lock().unwrap()
    }
}

#[derive(Debug)]
struct Counting(Mutex<u8>);
impl Entropy for Counting {
    fn fill(&self, buf: &mut [u8]) {
        let mut n = self.0.lock().unwrap();
        for b in buf {
            *n = n.wrapping_add(1);
            *b = *n;
        }
    }
}

/// A server over a scratch data directory with the repository's plugins (or none).
fn app(tag: &str, plugins: bool) -> (axum::Router, PathBuf) {
    let dir = std::env::temp_dir().join(format!("stewie-render-{tag}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let mut env: HashMap<&str, String> = [
        ("STEWIE_API_KEY", "automation-key-0123456789".to_owned()),
        ("STEWIE_DATA_DIR", dir.display().to_string()),
        (
            "STEWIE_PLANNER_CONFIG",
            repo().join("deploy/planner.json").display().to_string(),
        ),
    ]
    .into_iter()
    .collect();
    if plugins {
        env.insert(
            "STEWIE_PLUGIN_PATH",
            repo().join("plugins").display().to_string(),
        );
    }
    let clock: &'static Pinned = Box::leak(Box::new(Pinned(Mutex::new(1.8e9))));
    let bytes: &'static Counting = Box::leak(Box::new(Counting(Mutex::new(0))));
    let state = AppState::from_env(&|k| env.get(k).cloned(), clock, bytes).unwrap();
    (router(Arc::new(state)), dir)
}

async fn post(app: &axum::Router, body: Value) -> (u16, Value) {
    let mut req = Request::builder()
        .method("POST")
        .uri("/render")
        .header("x-api-key", "automation-key-0123456789")
        .header("content-type", "application/json")
        .body(Body::from(body.to_string()))
        .unwrap();
    req.extensions_mut()
        .insert(ConnectInfo(SocketAddr::from(([127, 0, 0, 1], 50000))));
    let r = app.clone().oneshot(req).await.unwrap();
    let status = r.status().as_u16();
    (
        status,
        serde_json::from_slice(&r.into_body().collect().await.unwrap().to_bytes()).unwrap(),
    )
}

#[tokio::test(flavor = "multi_thread")]
#[allow(clippy::cast_possible_truncation)] // a mass in kg, rounded as the Python's round()
async fn render_drives_the_godot_plugin_or_says_it_cannot() {
    let (none, dir) = app("none", false);
    let (status, body) = post(&none, json!({})).await;
    assert_eq!(status, 503, "{body}");
    assert!(
        body["error"]
            .as_str()
            .unwrap()
            .starts_with("render pipeline unavailable (renderer plugin: not available"),
        "{body}"
    );
    std::fs::remove_dir_all(&dir).unwrap();
    let (with, dir) = app("with", true);
    let (status, body) = post(&with, json!({"pad_frac": 0})).await;
    assert_eq!(status, 400, "{body}");
    if std::env::var("STEWIE_GODOT").map_or(true, |g| g.is_empty()) {
        let (status, body) = post(&with, json!({})).await;
        assert_eq!(status, 503, "{body}");
        assert_eq!(
            body["error"],
            "render pipeline unavailable (the renderer plugin has no Godot binary configured)"
        );
        std::fs::remove_dir_all(&dir).unwrap();
        return;
    }
    let (status, body) = post(&with, json!({"u": 0.5, "v": 0.5, "pad_frac": 0.5})).await;
    assert_eq!(status, 200, "{body}");
    let fx = stewie_oracle::load("render_earthwork_cases")
        .unwrap()
        .payload;
    let want = &fx["cases"][0];
    let r2 = |x: f64| (x * 100.0).round() / 100.0;
    assert_eq!(
        body["cut_vol_m3"],
        json!(r2(want["cut_vol_m3"].as_f64().unwrap()))
    );
    assert_eq!(
        body["fill_vol_m3"],
        json!(r2(want["fill_vol_m3"].as_f64().unwrap()))
    );
    assert_eq!(
        body["cut_kg"],
        json!(want["cut_kg"].as_f64().unwrap().round_ties_even() as i64)
    );
    assert_eq!(
        (body["extent_m"].as_f64(), body["cell_m"].as_f64()),
        (Some(50.0), Some(0.5))
    );
    let fig = dir.join("reports").join(
        body["figure"]
            .as_str()
            .unwrap()
            .trim_start_matches("/reports/"),
    );
    let rgb = |path: &std::path::Path| {
        let mut reader =
            png::Decoder::new(std::io::BufReader::new(std::fs::File::open(path).unwrap()))
                .read_info()
                .unwrap();
        let mut buf = vec![0; reader.output_buffer_size().unwrap()];
        let info = reader.next_frame(&mut buf).unwrap();
        let px: Vec<u8> = match info.color_type {
            png::ColorType::Rgba => buf[..info.buffer_size()]
                .chunks_exact(4)
                .flat_map(|p| [p[0], p[1], p[2]])
                .collect(),
            _ => buf[..info.buffer_size()].to_vec(),
        };
        (info.width as usize, info.height as usize, px)
    };
    let (w, h, figure) = rgb(&fig);
    assert_eq!((w, h), (2048, 768), "BEFORE | AFTER at 1024 x 768 each");
    // the figure's halves are the two renders the plugin wrote beside it, BEFORE left and AFTER right
    let run = fig.with_extension("");
    for (png_name, offset) in [("win_before.png", 0), ("win_after.png", 1024 * 3)] {
        let (_, _, render) = rgb(&run.join(png_name));
        for y in 0..768 {
            assert_eq!(
                &figure[y * 2048 * 3 + offset..y * 2048 * 3 + offset + 1024 * 3],
                &render[y * 1024 * 3..(y + 1) * 1024 * 3],
                "{png_name} row {y}"
            );
        }
    }
    let (_, _, before) = rgb(&run.join("win_before.png"));
    let (_, _, after) = rgb(&run.join("win_after.png"));
    assert_ne!(before, after, "the flatten changed the scene");
    // STEWIE_RENDER_KEEP=<path> keeps the figure for a look
    if let Ok(keep) = std::env::var("STEWIE_RENDER_KEEP") {
        std::fs::copy(&fig, keep).unwrap();
    }
    std::fs::remove_dir_all(&dir).unwrap();
}
