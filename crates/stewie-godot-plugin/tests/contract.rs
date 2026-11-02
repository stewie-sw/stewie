//! RW-51a: the Godot renderer plugin's contract, round-tripped through the plugin host. The shipped `plugins/godot`
//! manifest is discovered, its launcher starts the plugin, and the handshake, every refusal and the unconfigured
//! answer are checked. Where `STEWIE_GODOT` names a Godot binary, the scene the Python /render pipeline writes for a
//! real Haworth window (`godot_scene_cases`) is rendered for real and its decoded pixels must equal the recorded
//! session (`fixtures/recorded_session.json`; `STEWIE_GODOT_RECORD=1` records it).

use std::path::{Path, PathBuf};
use std::time::Duration;

use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use stewie_plugins::{Kind, PluginError, Registry, Session};

fn repo() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}

fn scratch(tag: &str) -> PathBuf {
    let d = std::env::temp_dir().join(format!("stewie-godot-{tag}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&d);
    std::fs::create_dir_all(&d).unwrap();
    d
}

/// Lay the recorded real Haworth window down as an INTERFACE.md bundle: each raster row-major little-endian
/// (`<f4`, or `u1` for the state label), `metadata.json` last.
fn lay_scene(dir: &Path) {
    let fx: Value = serde_json::from_str(
        &std::fs::read_to_string(
            repo().join("crates/stewie-oracle/fixtures/godot_scene_cases.payload.json"),
        )
        .unwrap(),
    )
    .unwrap();
    let meta = &fx["metadata"];
    for (name, values) in fx["fields"].as_object().unwrap() {
        let file = meta["fields"][name]["file"].as_str().unwrap();
        let bytes: Vec<u8> = if meta["fields"][name]["dtype"] == "u1" {
            values
                .as_array()
                .unwrap()
                .iter()
                .map(|v| u8::try_from(v.as_u64().unwrap()).unwrap())
                .collect()
        } else {
            #[allow(clippy::cast_possible_truncation)] // the recorded values are float32
            values
                .as_array()
                .unwrap()
                .iter()
                .flat_map(|v| (v.as_f64().unwrap() as f32).to_le_bytes())
                .collect()
        };
        std::fs::write(dir.join(file), bytes).unwrap();
    }
    std::fs::write(dir.join("metadata.json"), meta.to_string()).unwrap();
}

fn start() -> Session {
    let reg = Registry::discover(&[repo().join("plugins")]);
    assert!(reg.rejected().is_empty(), "{:?}", reg.rejected());
    let plugin = reg.require(Kind::Renderer).unwrap();
    assert_eq!(&*plugin.manifest.name, "godot");
    let s = Session::start(plugin, Duration::from_mins(5)).unwrap();
    assert_eq!(s.capabilities, ["render"]);
    s
}

fn refused(s: &mut Session, params: &Value) -> String {
    match s.call("render", params) {
        Err(PluginError::Failed(m)) => m,
        other => panic!("{params}: expected a refusal, got {other:?}"),
    }
}

/// The recorded session's request: the /render pipeline's oblique bird's-eye view of a 50 m window under a lit sun.
fn request(scene: &Path, out: &Path) -> Value {
    json!({"scene": scene.display().to_string(), "out": out.display().to_string(), "layers": "terrain",
           "size": "640x480", "pose": [25.0, 42.5, 55.0, 25.0, 0.0, 25.0], "sun_elev": 25.0, "sun_azim": 215.0})
}

#[test]
fn the_godot_plugin_honours_its_contract() {
    let dir = scratch("contract");
    let scene = dir.join("scene");
    std::fs::create_dir_all(&scene).unwrap();
    lay_scene(&scene);
    let out = dir.join("render.png");
    let mut s = start();
    let ok = request(&scene, &out);
    let with = |k: &str, v: Value| {
        let mut p = ok.clone();
        p[k] = v;
        p
    };
    assert!(
        refused(&mut s, &with("scene", json!("relative/scene")))
            .contains("not an absolute scene directory")
    );
    assert!(
        refused(&mut s, &with("scene", json!(dir.display().to_string())))
            .contains("with metadata.json")
    );
    assert!(
        refused(&mut s, &with("out", json!("render.jpg"))).contains("not an absolute .png path")
    );
    assert!(refused(&mut s, &with("size", json!("8x8"))).contains("each side 16..4096"));
    assert!(refused(&mut s, &with("pose", json!([1, 2, 3, 4, 5]))).contains("six finite numbers"));
    assert!(refused(&mut s, &with("layers", json!("terrain;rm"))).contains("comma list"));
    assert!(refused(&mut s, &with("sun_elev", json!("high"))).contains("finite number"));
    match s.call("paint", &json!({})) {
        Err(PluginError::Failed(m)) => assert_eq!(m, "unknown op \"paint\""),
        other => panic!("expected the unknown op refused, got {other:?}"),
    }
    let recorded_path = repo().join("crates/stewie-godot-plugin/fixtures/recorded_session.json");
    if std::env::var("STEWIE_GODOT").map_or(true, |g| g.is_empty()) {
        // no renderer configured on this host: the plugin says so rather than answer anything
        assert!(refused(&mut s, &ok).starts_with("STEWIE_GODOT is not set"));
        std::fs::remove_dir_all(&dir).unwrap();
        return;
    }
    let r = s.call("render", &ok).unwrap();
    assert_eq!(
        (r["width"].as_u64(), r["height"].as_u64()),
        (Some(640), Some(480)),
        "{r}"
    );
    assert_eq!(r["png"], json!(out.display().to_string()));
    let decoder = png::Decoder::new(std::io::BufReader::new(std::fs::File::open(&out).unwrap()));
    let mut reader = decoder.read_info().unwrap();
    let mut buf = vec![0; reader.output_buffer_size().unwrap()];
    let info = reader.next_frame(&mut buf).unwrap();
    let pixels = &buf[..info.buffer_size()];
    let sha = Sha256::digest(pixels)
        .iter()
        .fold(String::new(), |mut out, b| {
            use std::fmt::Write as _;
            let _ = write!(out, "{b:02x}");
            out
        });
    let mut req = ok.clone();
    for k in ["scene", "out"] {
        req.as_object_mut().unwrap().remove(k);
    }
    if std::env::var("STEWIE_GODOT_RECORD").is_ok_and(|v| v == "1") {
        let rec = json!({"request": req, "scene": "godot_scene_cases", "width": 640, "height": 480,
                         "color_type": format!("{:?}", info.color_type), "pixels_sha256": sha,
                         "renderer": "Godot 4.6.3, Vulkan Forward+, NVIDIA GeForce RTX 3090 under xvfb (render.sh)"});
        std::fs::write(
            &recorded_path,
            format!("{}\n", serde_json::to_string_pretty(&rec).unwrap()),
        )
        .unwrap();
    }
    let rec: Value =
        serde_json::from_str(&std::fs::read_to_string(&recorded_path).unwrap()).unwrap();
    assert_eq!(rec["request"], req, "the recorded session's request");
    assert_eq!(rec["color_type"], json!(format!("{:?}", info.color_type)));
    assert_eq!(
        rec["pixels_sha256"],
        json!(sha),
        "the render's decoded pixels against the recorded session"
    );
    // a scene whose rasters are missing makes the sidecar fail: that is reported, and the image already at `out`
    // (the good render above) never passes for this one
    let broken = dir.join("broken");
    std::fs::create_dir_all(&broken).unwrap();
    std::fs::copy(scene.join("metadata.json"), broken.join("metadata.json")).unwrap();
    let why = refused(&mut s, &with("scene", json!(broken.display().to_string())));
    assert!(why.starts_with("the sidecar exited with"), "{why}");
    assert!(
        !out.exists(),
        "the stale image was cleared before the render"
    );
    std::fs::remove_dir_all(&dir).unwrap();
}
