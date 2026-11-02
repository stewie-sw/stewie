//! `stewie-viz2-runtime`: serve a viz2 session runtime for the live Godot client (Python `viz2_serve.py`, its flags
//! and its log lines). The runtime is built over a real bundle, its seam bound and its 0600 token file written into
//! `--session-dir`; it is held for `--seconds` or until a `STOP` file appears there. The planner file is
//! `STEWIE_PLANNER_CONFIG`. Use `--start-xy=<x>,<y>` (a negative x would read as a flag when separated).

use std::path::PathBuf;
use std::time::{Duration, Instant};

use stewie_viz2::config::{production_calib, production_setup};
use stewie_viz2::runtime::{Options, Runtime};
use stewie_viz2::transport::Served;

struct Args {
    bundle: PathBuf,
    session_dir: PathBuf,
    seconds: f64,
    fine_cell_m: Option<f64>,
    start_xy: Option<(f64, f64)>,
}

fn parse() -> Result<Args, String> {
    let mut it = std::env::args().skip(1);
    let (mut bundle, mut session_dir, mut seconds, mut fine, mut start) =
        (None, None, 60.0, None, None);
    let float = |s: &str, flag: &str| {
        s.trim()
            .parse::<f64>()
            .map_err(|_| format!("{flag}: invalid float value: {s:?}"))
    };
    while let Some(a) = it.next() {
        let (flag, inline) = a
            .split_once('=')
            .map_or((a.as_str(), None), |(f, v)| (f, Some(v.to_owned())));
        let mut value = || {
            inline
                .clone()
                .or_else(|| it.next())
                .ok_or_else(|| format!("{flag}: expected one argument"))
        };
        match flag {
            "--bundle" => bundle = Some(PathBuf::from(value()?)),
            "--session-dir" => session_dir = Some(PathBuf::from(value()?)),
            "--seconds" => seconds = float(&value()?, flag)?,
            "--fine-cell-m" => fine = Some(float(&value()?, flag)?),
            "--start-xy" => {
                let v = value()?;
                if !v.is_empty() {
                    let (x, y) = v.split_once(',').ok_or("--start-xy: expected \"x,y\"")?;
                    start = Some((float(x, flag)?, float(y, flag)?));
                }
            }
            other => return Err(format!("unrecognized arguments: {other}")),
        }
    }
    Ok(Args {
        bundle: bundle.ok_or("the following arguments are required: --bundle")?,
        session_dir: session_dir.ok_or("the following arguments are required: --session-dir")?,
        seconds,
        fine_cell_m: fine,
        start_xy: start,
    })
}

fn run() -> Result<(), String> {
    let a = parse()?;
    let planner = std::env::var("STEWIE_PLANNER_CONFIG")
        .ok()
        .filter(|p| !p.trim().is_empty())
        .ok_or("the planner parameters are not configured: set STEWIE_PLANNER_CONFIG (deploy/planner.json)")?;
    let setup = stewie_viz2::runtime::with_fine(production_setup("moon")?, a.fine_cell_m);
    let calib = production_calib("small", std::path::Path::new(&planner))?;
    std::fs::create_dir_all(&a.session_dir).map_err(|e| e.to_string())?;
    let rt = Runtime::new(
        &a.bundle,
        &a.session_dir,
        Options {
            start_xy: a.start_xy,
            ..Options::default()
        },
        setup,
        calib,
    )?;
    let (h, w) = rt.window_shape();
    let fine =
        stewie_twin::pyjson::float_repr(rt.ws.fine_cell_m()).map_err(|e| format!("{e:?}"))?;
    let served = Served::start(rt, "127.0.0.1")?;
    println!(
        "viz2_serve: ready port={} token={} window=({h}, {w}) fine_cell_m={fine}",
        served.port,
        served.token_path.display()
    );
    let (end, stop_path) = (
        Instant::now() + Duration::from_secs_f64(a.seconds.max(0.0)),
        a.session_dir.join("STOP"),
    );
    let mut failure = None;
    while Instant::now() < end && !stop_path.exists() {
        if let Some(e) = served.failed.lock().ok().and_then(|f| f.clone()) {
            failure = Some(e);
            break;
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    served.stop();
    if let Some(e) = failure {
        return Err(format!("the runtime stopped: {e}"));
    }
    println!("viz2_serve: stopped");
    Ok(())
}

fn main() {
    if let Err(e) = run() {
        eprintln!("viz2_serve: {e}");
        std::process::exit(1);
    }
}
