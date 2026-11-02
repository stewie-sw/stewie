//! RW-51e3: the live Godot client (`viz2.tscn --live --auto`, the client `viz2_live.sh` runs) drives THROUGH the Rust
//! runtime on the real 1 m `SfS` bundle: it reads the 0600 token file, authenticates, builds its window from the
//! connect keyframe, applies and acks the manifests while it drives (it trusts the manifest-last commit marker and
//! re-checks no digest; `tests/runtime.rs` holds every digest to its bytes), and its rendered pose equals the
//! runtime's telemetry. Where `STEWIE_GODOT` names no binary (CI has no GPU) there is no client to run.

use std::process::Command;
use std::time::Duration;

use stewie_viz2::config::{production_calib, production_setup};
use stewie_viz2::runtime::{Options, Runtime};
use stewie_viz2::transport::Served;

/// The number after `key` in `text`.
fn after<'a>(text: &'a str, key: &str) -> Option<&'a str> {
    text.find(key).map(|i| {
        text[i + key.len()..]
            .split([' ', ',', ')'])
            .next()
            .unwrap_or("")
    })
}

#[test]
#[allow(clippy::too_many_lines)] // one live session, end to end
fn the_live_godot_client_drives_through_the_rust_runtime() {
    let Some(godot) = std::env::var("STEWIE_GODOT").ok().filter(|g| !g.is_empty()) else {
        return;
    };
    let repo = stewie_oracle::repo_root();
    let dir = std::env::temp_dir().join(format!("stewie-viz2-live-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    let (session, out) = (dir.join("session"), dir.join("out"));
    std::fs::create_dir_all(&session).unwrap();
    std::fs::create_dir_all(&out).unwrap();
    let bundle = repo.join("samples/lunar_dem/haworth_sfs_2km_1m");
    let rt = Runtime::new(
        &bundle,
        &session,
        Options::default(),
        production_setup("moon").unwrap(),
        production_calib("small", &repo.join("deploy/planner.json")).unwrap(),
    )
    .unwrap();
    let start = rt.start_xy;
    // the window geometry Godot must build from the manifests: its side and cell
    let (rows, cols) = rt.window_shape();
    let cell = rt.ws.fine_cell_m();
    #[allow(clippy::cast_precision_loss)] // a window of a few cells
    let geometry = format!("side={:.2} m cell={cell:.3}", cols as f64 * cell);
    assert_eq!(rows, cols, "a square window");
    let served = Served::start(rt, "127.0.0.1").unwrap();
    let run = Command::new("timeout")
        .arg("170")
        .args([
            "xvfb-run",
            "-a",
            "--server-args=-screen 0 1920x1080x24",
            &godot,
            "--rendering-driver",
            "vulkan",
        ])
        .arg("--path")
        .arg(repo.join("stewie/godot"))
        .args(["res://viz2.tscn", "--", "--live", "--session-dir"])
        .arg(&session)
        .arg("--site")
        .arg(&bundle)
        .arg("--out")
        .arg(&out)
        .args(["--auto", "4", "--size", "640x360"])
        .output()
        .unwrap();
    let log =
        String::from_utf8_lossy(&run.stdout).into_owned() + &String::from_utf8_lossy(&run.stderr);
    assert!(
        run.status.success(),
        "godot exited {:?}:\n{log}",
        run.status.code()
    );
    assert!(
        log.contains("viz2: LIVE connected to Viz2Runtime (epoch 1)"),
        "{log}"
    );
    assert!(
        log.contains("viz2: live window ready gen=1 "),
        "the connect keyframe built the window:\n{log}"
    );
    assert!(
        log.contains(&geometry),
        "Godot built the window the runtime serves ({geometry}):\n{log}"
    );
    let done = log
        .lines()
        .find(|l| l.contains("LIVE auto done"))
        .expect("the auto drive finished");
    let gen_done: u64 = after(done, "gen=").unwrap().trim().parse().unwrap();
    assert!(gen_done >= 30, "the client applied {gen_done} generations");
    // the rendered pose is the runtime's telemetry pose, to the cell
    assert!(
        log.contains("POSE-TRACK") && after(&log, "delta=") == Some("0.000"),
        "{log}"
    );
    let rt = served.runtime.lock().unwrap();
    assert!(
        rt.last_acked_gen() >= gen_done / 2,
        "acked {} of {gen_done}",
        rt.last_acked_gen()
    );
    let pose = rt.ws.pose_xy().unwrap();
    assert!(
        (pose.0 - start.0).hypot(pose.1 - start.1) > 0.3,
        "the rover moved: {start:?} -> {pose:?}"
    );
    assert!(
        rt.rejected_bounds >= 2,
        "its dig and dump were refused (D-R185)"
    );
    drop(rt);
    for png in [
        "viz2_live_000.png",
        "viz2_live_topdown.png",
        "viz2_live_dig_chase.png",
    ] {
        let len = std::fs::metadata(out.join(png)).unwrap().len();
        assert!(len > 1000, "{png}: {len} bytes");
    }
    assert!(served.failed.lock().unwrap().is_none());
    served.stop();
    std::thread::sleep(Duration::from_millis(100));
    std::fs::remove_dir_all(&dir).unwrap();
}
