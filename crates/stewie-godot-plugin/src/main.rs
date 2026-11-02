//! The Godot renderer plugin (RW-51, D-R01): a `stewie-plugin-v1` process (one JSON object per line on stdin and
//! stdout) that renders a scene bundle (INTERFACE.md) through the headless `stewie/godot` sidecar.
//!
//! `render` takes `scene` (an absolute scene directory holding `metadata.json`), `out` (an absolute `.png` path),
//! and optionally `layers`, `size` (`WxH`), `pose` (six numbers: camera position and look-at target), `sun_elev`
//! and `sun_azim` [deg]. It runs the project's `render.sh` (Godot under xvfb with Vulkan; never `--headless`, which
//! disables the renderer) with the binary `STEWIE_GODOT` names, and answers the PNG it wrote with its size. Every
//! way the render can fail (no binary configured, a non-zero exit, a timeout, no PNG) is an error reply naming why;
//! nothing is ever substituted for a render.

use std::io::{BufRead, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

use serde_json::{Map, Value, json};

const PROTOCOL: &str = "stewie-plugin-v1";
/// The longest one render may take (the Python pipeline's own bound).
const RENDER_TIMEOUT: Duration = Duration::from_mins(4);

/// The render's command-line arguments after `--` (the sidecar's documented flags).
fn sidecar_args(p: &Map<String, Value>) -> Result<(PathBuf, Vec<String>), String> {
    let text = |k: &str| p.get(k).and_then(Value::as_str);
    let scene =
        PathBuf::from(text("scene").ok_or("render needs `scene`, an absolute scene directory")?);
    if !scene.is_absolute() || !scene.join("metadata.json").is_file() {
        return Err(format!(
            "scene {} is not an absolute scene directory with metadata.json",
            scene.display()
        ));
    }
    let out = PathBuf::from(text("out").ok_or("render needs `out`, an absolute .png path")?);
    if !out.is_absolute() || out.extension().is_none_or(|e| e != "png") {
        return Err(format!(
            "out {} is not an absolute .png path",
            out.display()
        ));
    }
    let layers = text("layers").unwrap_or("terrain");
    if layers.is_empty()
        || !layers
            .bytes()
            .all(|c| c.is_ascii_lowercase() || c == b'_' || c == b',')
    {
        return Err(format!(
            "layers {layers:?} must be a comma list of layer names"
        ));
    }
    let size = text("size").unwrap_or("1024x768");
    let dims: Vec<u32> = size.split('x').filter_map(|d| d.parse().ok()).collect();
    if dims.len() != 2 || dims.iter().any(|d| !(16..=4096).contains(d)) {
        return Err(format!("size {size:?} must be WxH with each side 16..4096"));
    }
    let mut args: Vec<String> = [
        "--scene",
        &scene.display().to_string(),
        "--layers",
        layers,
        "--size",
        size,
        "--out",
        &out.display().to_string(),
    ]
    .iter()
    .map(|s| (*s).to_owned())
    .collect();
    if let Some(pose) = p.get("pose").filter(|v| !v.is_null()) {
        let xs: Vec<f64> = pose
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(Value::as_f64)
            .collect();
        if xs.len() != 6
            || pose.as_array().is_none_or(|a| a.len() != 6)
            || xs.iter().any(|x| !x.is_finite())
        {
            return Err("pose must be six finite numbers: x, y, z, target x, y, z".to_owned());
        }
        args.push("--pose".to_owned());
        args.push(xs.iter().map(f64::to_string).collect::<Vec<_>>().join(","));
    }
    for (key, flag) in [("sun_elev", "--sun-elev"), ("sun_azim", "--sun-azim")] {
        if let Some(v) = p.get(key).filter(|v| !v.is_null()) {
            let x = v
                .as_f64()
                .filter(|x| x.is_finite())
                .ok_or_else(|| format!("{key} must be a finite number"))?;
            args.push(flag.to_owned());
            args.push(x.to_string());
        }
    }
    Ok((out, args))
}

/// The width and height a PNG file declares (its IHDR), or why it is not one.
fn png_size(path: &Path) -> Result<(u32, u32, u64), String> {
    let bytes = std::fs::read(path)
        .map_err(|e| format!("the render wrote no PNG at {}: {e}", path.display()))?;
    if bytes.len() < 24
        || bytes[..8] != [0x89, b'P', b'N', b'G', 0x0d, 0x0a, 0x1a, 0x0a]
        || &bytes[12..16] != b"IHDR"
    {
        return Err(format!("{} is not a PNG", path.display()));
    }
    let be = |i: usize| u32::from_be_bytes([bytes[i], bytes[i + 1], bytes[i + 2], bytes[i + 3]]);
    Ok((be(16), be(20), bytes.len() as u64))
}

/// Run one render through the sidecar and report what it wrote.
fn render(p: &Map<String, Value>) -> Result<Value, String> {
    let (out, args) = sidecar_args(p)?;
    let godot = std::env::var("STEWIE_GODOT")
        .ok()
        .filter(|g| !g.is_empty())
        .ok_or("STEWIE_GODOT is not set: there is no Godot binary to render with")?;
    if !Path::new(&godot).is_file() {
        return Err(format!("STEWIE_GODOT {godot} is not a file"));
    }
    let project = std::env::var("STEWIE_GODOT_PROJECT")
        .map_or_else(|_| PathBuf::from("../../stewie/godot"), PathBuf::from)
        .canonicalize()
        .map_err(|e| format!("the Godot project directory: {e}"))?;
    if let Some(dir) = out.parent() {
        std::fs::create_dir_all(dir).map_err(|e| format!("{}: {e}", dir.display()))?;
    }
    // a stale image must never pass for this render
    let _ = std::fs::remove_file(&out);
    let log = out.with_extension("log");
    let log_file = std::fs::File::create(&log).map_err(|e| format!("{}: {e}", log.display()))?;
    let mut child = Command::new("bash")
        .arg(project.join("render.sh"))
        .arg("res://sidecar.tscn")
        .arg("--")
        .args(&args)
        .env("GODOT", &godot)
        .stdin(Stdio::null())
        .stdout(log_file.try_clone().map_err(|e| e.to_string())?)
        .stderr(log_file)
        .spawn()
        .map_err(|e| format!("cannot start the sidecar: {e}"))?;
    let started = Instant::now();
    let status = loop {
        if let Some(s) = child.try_wait().map_err(|e| e.to_string())? {
            break s;
        }
        if started.elapsed() > RENDER_TIMEOUT {
            let _ = child.kill();
            let _ = child.wait();
            return Err(format!(
                "the render did not finish within {RENDER_TIMEOUT:?}"
            ));
        }
        std::thread::sleep(Duration::from_millis(50));
    };
    if !status.success() {
        let tail: String = std::fs::read_to_string(&log)
            .unwrap_or_default()
            .lines()
            .rev()
            .take(5)
            .collect::<Vec<_>>()
            .into_iter()
            .rev()
            .collect::<Vec<_>>()
            .join(" | ");
        return Err(format!("the sidecar exited with {status}: {tail}"));
    }
    let (width, height, bytes) = png_size(&out)?;
    Ok(
        json!({"png": out.display().to_string(), "width": width, "height": height, "bytes": bytes,
              "seconds": started.elapsed().as_secs_f64()}),
    )
}

fn main() {
    let stdin = std::io::stdin();
    let mut stdout = std::io::stdout();
    for line in stdin.lock().lines().map_while(Result::ok) {
        let Ok(Value::Object(msg)) = serde_json::from_str::<Value>(&line) else {
            continue;
        };
        let op = msg.get("op").and_then(Value::as_str).unwrap_or("");
        let reply = if op == "hello" {
            // `render` is offered only when a Godot binary is configured, so a host can tell "not available" from
            // a render that failed
            let configured = std::env::var("STEWIE_GODOT")
                .is_ok_and(|g| !g.is_empty() && Path::new(&g).is_file());
            let caps: &[&str] = if configured { &["render"] } else { &[] };
            json!({"ok": true, "protocol": PROTOCOL, "name": "godot", "capabilities": caps})
        } else {
            let id = msg.get("id").cloned().unwrap_or(Value::Null);
            let params = msg
                .get("params")
                .and_then(Value::as_object)
                .cloned()
                .unwrap_or_default();
            match op {
                "render" => match render(&params) {
                    Ok(result) => json!({"id": id, "ok": true, "result": result}),
                    Err(e) => json!({"id": id, "ok": false, "error": e}),
                },
                _ => json!({"id": id, "ok": false, "error": format!("unknown op {op:?}")}),
            }
        };
        if writeln!(stdout, "{reply}")
            .and_then(|()| stdout.flush())
            .is_err()
        {
            break;
        }
    }
}
