//! RW-51e1b: the viz2 session runtime stepped on a pinned clock equals the Python's (`viz2_runtime_cases`, over the
//! real 1 m `SfS` bundle, its SYNTHETIC command script labelled there): every published frame (telemetry key by key,
//! values to 1e-9), every counter, every generation's manifest (structure exact, its digests the sha256 of the
//! Rust's own bytes), the sampled crops by value, and the generations left after the prune.

use std::collections::BTreeSet;

use serde_json::{Map, Value, json};
use stewie_physics::column::Regolith;
use stewie_physics::drive::Vehicle;
use stewie_physics::drum_sensor::ErrorBands;
use stewie_physics::soil::SoilParams;
use stewie_physics::worksite::Setup;
use stewie_viz2::runtime::{Calib, Drum, Options, Runtime};

fn f(v: &Value) -> f64 {
    v.as_f64().unwrap()
}

/// The Python worksite's own legacy defaults (`worksite_native` records them), as the worksite tests use (D-R54).
#[allow(clippy::cast_possible_truncation)]
fn python_setup() -> Setup {
    let fx = stewie_oracle::load("worksite_native").unwrap().payload;
    let s = &fx["soil"];
    let (reg, base) = stewie_physics::soil::bundled();
    Setup {
        vehicle: Vehicle {
            mass_kg: f(&fx["mass_kg"]),
            n_wheels: fx["n_wheels"].as_u64().unwrap() as u32,
            gauge_m: f(&fx["gauge_m"]),
            wheelbase_m: f(&fx["wheelbase_m"]),
            wheel_radius_m: f(&fx["wheel_radius_m"]),
            wheel_width_m: f(&fx["wheel_width_m"]),
            nominal_contact_len_m: f(&fx["contact_len_m"]),
            cg_height_m: f(&fx["cg_height_m"]),
            track_m: f(&fx["track_m"]),
        },
        soil: SoilParams {
            k_c: f(&s["k_c"]),
            k_phi: f(&s["k_phi"]),
            n: f(&s["n_sinkage"]),
            cohesion_pa: f(&s["cohesion"]),
            phi_rad: f(&s["phi_rad"]),
            k_shear_m: f(&s["k_shear"]),
            slip_c1: f(&s["slip_c1"]),
            slip_c2: f(&s["slip_c2"]),
            rho_surface: f(&s["rho_surface"]),
            rho_deep: f(&s["rho_deep"]),
            analog: false,
        },
        material: None,
        regolith: Regolith::new(reg["moon"].bulk_density.unwrap(), &base),
        gravity_ms2: f(&fx["g"]),
        v_max: f(&fx["v_max"]),
        tile_base_cells: 4,
        fine_cell_m: None,
    }
}

/// The figures from their committed sources: the IPEx profile's small drum, the planner's CALIB values and the
/// report's error bands.
fn calib() -> Calib {
    let profile: Value = serde_json::from_str(include_str!(
        "../../stewie-contracts/fixtures/rover_ipex.json"
    ))
    .unwrap();
    let report: Value = serde_json::from_str(include_str!(
        "../../stewie-contracts/fixtures/plan_report.json"
    ))
    .unwrap();
    let planner: Value = serde_json::from_str(
        &std::fs::read_to_string(stewie_oracle::repo_root().join("deploy/planner.json")).unwrap(),
    )
    .unwrap();
    let small = &profile["drums"]["small"];
    Calib {
        drum: Drum {
            width_m: f(&small["width_m"]["value"]),
            capacity_kg: f(&small["capacity_kg"]["value"]),
            scoop_height_m: f(&small["scoop_height_m"]["value"]),
        },
        max_cut_depth_frac: f(&profile["max_cut_depth_frac"]["value"]),
        dig_energy_per_kg: f(&planner["ipex_dig_j_per_kg"]["value"]),
        fdc_baseline_a: f(&planner["fdc_baseline_a"]["value"]),
        fdc_slope_a_per_kg: f(&planner["fdc_slope_a_per_kg"]["value"]),
        bands: ErrorBands {
            mpe_all: f(&report["fdc_mpe_all"]),
            mpe_half_full: f(&report["fdc_mpe_half_full"]),
        },
    }
}

/// Values equal: numbers to 1e-9, everything else exactly, objects key by key.
#[track_caller]
fn same(got: &Value, want: &Value, at: &str) {
    match (got, want) {
        (Value::Number(a), Value::Number(b)) => {
            let (a, b) = (a.as_f64().unwrap(), b.as_f64().unwrap());
            assert!((a - b).abs() <= 1e-9 * b.abs().max(1.0), "{at}: {a} vs {b}");
        }
        (Value::Object(a), Value::Object(b)) => {
            let (ka, kb): (BTreeSet<_>, BTreeSet<_>) = (a.keys().collect(), b.keys().collect());
            assert_eq!(ka, kb, "{at}: keys");
            for k in kb {
                same(&a[k], &b[k], &format!("{at}.{k}"));
            }
        }
        (Value::Array(a), Value::Array(b)) => {
            assert_eq!(a.len(), b.len(), "{at}: length");
            for (i, (x, y)) in a.iter().zip(b).enumerate() {
                same(x, y, &format!("{at}[{i}]"));
            }
        }
        _ => assert_eq!(got, want, "{at}"),
    }
}

fn obj(v: Value) -> Map<String, Value> {
    match v {
        Value::Object(m) => m,
        other => panic!("not an object: {other}"),
    }
}

#[test]
#[allow(clippy::too_many_lines)] // one scripted session, as the oracle's
fn the_runtime_stepped_on_a_pinned_clock_equals_the_pythons() {
    let fx = stewie_oracle::load("viz2_runtime_cases").unwrap().payload;
    let dir = std::env::temp_dir().join(format!("stewie-viz2-runtime-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    let mut rt = Runtime::new(
        &stewie_oracle::repo_root().join(fx["bundle"].as_str().unwrap()),
        &dir,
        Options::default(),
        python_setup(),
        calib(),
    )
    .unwrap();
    same(
        &json!([rt.start_xy.0, rt.start_xy.1]),
        &fx["spawn"],
        "spawn",
    );
    assert_eq!(rt.dt.to_bits(), f(&fx["dt"]).to_bits());
    let mut clock = f(&fx["t0"]);
    let mut epoch = rt.register_session().unwrap();
    let mut ack = true;
    let ticks = fx["ticks"].as_array().unwrap();
    let mut k = 0;
    // the SYNTHETIC script, step for step as the oracle's
    let tick = |rt: &mut Runtime, clock: &mut f64, epoch: u64, ack: bool, k: &mut usize| {
        let want = &ticks[*k];
        let ok = rt.actor_once(*clock).unwrap();
        let frames: Vec<Value> = rt.take_outbound().into_iter().map(|(_, fr)| fr).collect();
        let tag = format!("tick {k} ({})", want["note"]);
        assert_eq!(json!(ok), want["ok"], "{tag}");
        same(&json!(frames), &want["frames"], &tag);
        for fr in &frames {
            if ack && fr.get("payload").is_some() {
                rt.enqueue(epoch, *clock, obj(json!({"cmd": "ack", "seq": fr["seq"]})));
            }
        }
        assert_eq!(json!(rt.rejected_stale), want["rejected_stale"], "{tag}");
        assert_eq!(json!(rt.rejected_bounds), want["rejected_bounds"], "{tag}");
        assert_eq!(json!(rt.safe_stopped()), want["safe_stopped"], "{tag}");
        assert_eq!(json!(rt.generation()), want["generation"], "{tag}");
        assert_eq!(json!(rt.last_acked_gen()), want["last_acked_gen"], "{tag}");
        assert_eq!(json!(rt.current_epoch()), want["epoch"], "{tag}");
        *clock += rt.dt;
        *k += 1;
    };
    let put = |rt: &mut Runtime, e: u64, at: f64, m: Value| assert!(rt.enqueue(e, at, obj(m)));
    tick(&mut rt, &mut clock, epoch, ack, &mut k);
    for m in [
        json!({"cmd": "arm", "front": 0.3, "back": "x"}),
        json!({"cmd": "dig"}),
        json!({"cmd": "dump"}),
        json!({"cmd": "twist", "v": true, "omega": 0.0}),
        json!({"cmd": "twist", "v": false, "omega": 0}),
        json!({"cmd": "warp"}),
    ] {
        put(&mut rt, epoch, clock, m);
    }
    tick(&mut rt, &mut clock, epoch, ack, &mut k);
    for i in 2..202 {
        put(
            &mut rt,
            epoch,
            clock,
            json!({"cmd": "twist", "v": 0.3, "omega": 0.05}),
        );
        if i == 5 {
            for s in [json!(5.0), json!("6"), Value::Null, json!("x")] {
                put(&mut rt, epoch, clock, json!({"cmd": "ack", "seq": s}));
            }
        }
        if i == 10 {
            put(
                &mut rt,
                epoch,
                clock,
                json!({"cmd": "arm", "front": 5, "back": -3}),
            );
        }
        if i == 20 {
            put(
                &mut rt,
                epoch,
                clock - 2.5,
                json!({"cmd": "twist", "v": 0.1, "omega": 0.0}),
            );
            put(
                &mut rt,
                epoch,
                clock - 2.5,
                json!({"cmd": "ack", "seq": 17}),
            );
        }
        if i == 30 {
            put(
                &mut rt,
                epoch,
                clock,
                json!({"cmd": "twist", "v": 0.31, "omega": 0.0}),
            );
            put(
                &mut rt,
                epoch,
                clock,
                json!({"cmd": "twist", "v": 0.0, "omega": 1.06}),
            );
            put(
                &mut rt,
                epoch,
                clock,
                json!({"cmd": "twist", "v": "0.2", "omega": 0.0}),
            );
        }
        if i == 40 {
            put(&mut rt, epoch, clock, json!({"cmd": "arm", "front": -0.1}));
        }
        tick(&mut rt, &mut clock, epoch, ack, &mut k);
    }
    for _ in 0..40 {
        tick(&mut rt, &mut clock, epoch, ack, &mut k);
    }
    put(&mut rt, epoch, clock, json!({"cmd": "dig"}));
    for _ in 0..3 {
        tick(&mut rt, &mut clock, epoch, ack, &mut k);
    }
    let stale = epoch;
    epoch = rt.register_session().unwrap();
    put(
        &mut rt,
        stale,
        clock,
        json!({"cmd": "twist", "v": 0.3, "omega": 0.0}),
    );
    for _ in 0..20 {
        put(
            &mut rt,
            epoch,
            clock,
            json!({"cmd": "twist", "v": -0.2, "omega": -0.1}),
        );
        tick(&mut rt, &mut clock, epoch, ack, &mut k);
    }
    ack = false;
    for _ in 0..40 {
        put(
            &mut rt,
            epoch,
            clock,
            json!({"cmd": "twist", "v": -0.2, "omega": -0.1}),
        );
        tick(&mut rt, &mut clock, epoch, ack, &mut k);
    }
    ack = true;
    epoch = rt.register_session().unwrap();
    for _ in 0..5 {
        tick(&mut rt, &mut clock, epoch, ack, &mut k);
    }
    assert_eq!(k, ticks.len(), "vacuity: every tick replayed");
    // the generations left after the prune, each manifest and the sampled crops
    let mut left: Vec<String> = std::fs::read_dir(&rt.generations_dir)
        .unwrap()
        .map(|e| e.unwrap().file_name().to_string_lossy().into_owned())
        .collect();
    left.sort();
    assert_eq!(json!(left), fx["generation_dirs"]);
    let mut seen = 0;
    for (gen_no, want) in fx["manifests"].as_object().unwrap() {
        let gdir = rt
            .generations_dir
            .join(format!("gen_{:08}", gen_no.parse::<u64>().unwrap()));
        let Ok(text) = std::fs::read_to_string(gdir.join("manifest.json")) else {
            assert!(!left.contains(&format!("gen_{:08}", gen_no.parse::<u64>().unwrap())));
            continue;
        };
        let mut got: Value = serde_json::from_str(&text).unwrap();
        for (name, fm) in got["fields"].as_object_mut().unwrap() {
            let bytes = std::fs::read(gdir.join(fm["file"].as_str().unwrap())).unwrap();
            let digest: String = {
                use sha2::Digest as _;
                sha2::Sha256::digest(&bytes)
                    .iter()
                    .fold(String::new(), |mut out, b| {
                        use std::fmt::Write as _;
                        let _ = write!(out, "{b:02x}");
                        out
                    })
            };
            assert_eq!(
                fm["digest"],
                json!(digest),
                "gen {gen_no} {name}: the digest is of the bytes beside it"
            );
            fm.as_object_mut().unwrap().remove("digest");
            if let Some(crop) = fx["crops"].get(gen_no).and_then(|c| c.get(name)) {
                let vals: Vec<Value> = if fm["dtype"] == "u1" {
                    bytes.iter().map(|b| json!(f64::from(*b))).collect()
                } else {
                    bytes
                        .chunks_exact(4)
                        .map(|b| json!(f64::from(f32::from_le_bytes([b[0], b[1], b[2], b[3]]))))
                        .collect()
                };
                // float32 crops of float64 state: within float32's own rounding
                for (i, (a, b)) in vals.iter().zip(crop.as_array().unwrap()).enumerate() {
                    let (a, b) = (f(a), f(b));
                    assert!(
                        (a - b).abs() <= 1e-6 * b.abs().max(1.0),
                        "gen {gen_no} {name}[{i}]: {a} vs {b}"
                    );
                }
            }
        }
        same(&got, want, &format!("manifest {gen_no}"));
        seen += 1;
    }
    assert_eq!(seen, 256, "vacuity: every retained manifest compared");
    assert_eq!(
        std::fs::read_to_string(dir.join("clasts.json")).unwrap(),
        "{\"clasts\": []}"
    );
    std::fs::remove_dir_all(&dir).unwrap();
}

/// A short scripted session from the oracle (`scenarios`): each tick's commands, frames acked as they arrive.
fn scripted(name: &str) {
    let fx = stewie_oracle::load("viz2_runtime_cases").unwrap().payload;
    let sc = &fx["scenarios"][name];
    let dir = std::env::temp_dir().join(format!("stewie-viz2-{name}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    let kw = &sc["kw"];
    let opts = Options {
        start_xy: kw["start_xy"].as_array().map(|p| (f(&p[0]), f(&p[1]))),
        start_yaw: kw["start_yaw"].as_f64().unwrap_or(0.0),
        retain_generations: kw["retain_generations"].as_u64().unwrap_or(256),
        keyframe_interval: kw["keyframe_interval"].as_u64().unwrap_or(90),
        ..Options::default()
    };
    let mut rt = Runtime::new(
        &stewie_oracle::repo_root().join(sc["bundle"].as_str().unwrap()),
        &dir,
        opts,
        python_setup(),
        calib(),
    )
    .unwrap();
    same(&json!([rt.start_xy.0, rt.start_xy.1]), &sc["spawn"], name);
    let epoch = rt.register_session().unwrap();
    let mut clock = f(&sc["t0"]);
    for (i, (msgs, want)) in sc["script"]
        .as_array()
        .unwrap()
        .iter()
        .zip(sc["ticks"].as_array().unwrap())
        .enumerate()
    {
        for m in msgs.as_array().unwrap() {
            assert!(rt.enqueue(epoch, clock, obj(m.clone())));
        }
        assert_eq!(
            json!(rt.actor_once(clock).unwrap()),
            want["ok"],
            "{name} tick {i}"
        );
        let frames: Vec<Value> = rt.take_outbound().into_iter().map(|(_, fr)| fr).collect();
        same(&json!(frames), &want["frames"], &format!("{name} tick {i}"));
        for fr in &frames {
            if fr.get("payload").is_some() {
                rt.enqueue(epoch, clock, obj(json!({"cmd": "ack", "seq": fr["seq"]})));
            }
        }
        clock += rt.dt;
    }
    let mut left: Vec<String> = std::fs::read_dir(&rt.generations_dir)
        .unwrap()
        .map(|e| e.unwrap().file_name().to_string_lossy().into_owned())
        .collect();
    left.sort();
    assert_eq!(json!(left), sc["generation_dirs"], "{name}");
    std::fs::remove_dir_all(&dir).unwrap();
}

#[test]
fn the_prune_keeps_the_newest_keyframe() {
    scripted("prune");
}

#[test]
fn a_drive_over_a_crater_slope_from_an_operator_section_equals_the_pythons() {
    scripted("slope");
}
