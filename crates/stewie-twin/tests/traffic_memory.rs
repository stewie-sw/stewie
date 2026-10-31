//! Traffic Memory against the Python oracle `traffic_memory_cases`: two routed legs on the REAL Haworth route
//! window, rasterised by the server's own segment sampler, folded at the real IPEx static wheel loads (dry,
//! then a 20 kg drum), with one event re-committed (a no-op, H-09). The Python's soil, contact length,
//! material endpoints and gravity are passed for parity.

use serde_json::Value;
use stewie_physics::material::MaterialModel;
use stewie_physics::soil::SoilParams;
use stewie_twin::traffic_memory::{self as tw, Hardening, TrafficMemory, TrafficParams};

fn fx() -> Value {
    stewie_oracle::load("traffic_memory_cases").unwrap().payload
}

fn f(v: &Value) -> f64 {
    v.as_f64().unwrap()
}

fn vf(v: &Value) -> Vec<f64> {
    v.as_array().unwrap().iter().map(f).collect()
}

#[track_caller]
fn close_all(got: &[f64], want: &[f64], what: &str) {
    assert_eq!(got.len(), want.len(), "{what} length");
    for (k, (a, b)) in got.iter().zip(want).enumerate() {
        assert!(
            (a - b).abs() <= 1e-9 * b.abs().max(1.0),
            "{what}[{k}]: {a} vs {b}"
        );
    }
}

fn soil(fx: &Value) -> SoilParams {
    let s = &fx["soil"];
    SoilParams {
        k_c: f(&s["k_c"]),
        k_phi: f(&s["k_phi"]),
        n: f(&s["n_sinkage"]),
        cohesion_pa: f(&s["cohesion"]),
        phi_rad: f(&s["phi_rad"]),
        k_shear_m: f(&s["k_shear"]),
        slip_c1: f(&s["slip_c1"]),
        slip_c2: f(&s["slip_c2"]),
        rho_surface: f(&fx["rho_surface"]),
        rho_deep: f(&fx["rho_deep"]),
        analog: false,
    }
}

fn material(fx: &Value) -> MaterialModel {
    let m = &fx["material"];
    MaterialModel {
        rho_surface: f(&m["rho_surface"]),
        rho_deep: f(&m["rho_deep"]),
        phi_loose_deg: f(&m["phi_loose_deg"]),
        phi_dense_deg: f(&m["phi_dense_deg"]),
        cohesion_loose_pa: f(&m["cohesion_loose_pa"]),
        cohesion_dense_pa: f(&m["cohesion_dense_pa"]),
    }
}

#[allow(clippy::cast_possible_truncation)]
fn folded(fx: &Value) -> (TrafficMemory, Vec<u64>) {
    let n = fx["rows"].as_u64().unwrap() as usize;
    let mut tm = TrafficMemory::new(
        "haworth",
        n,
        n,
        f(&fx["cell_m"]),
        (0.0, 0.0),
        TrafficParams {
            mass_areal: f(&fx["mass_areal"]),
            sigma_c_n: f(&fx["sigma_c_n"]),
            contact_width_m: f(&fx["contact_width_m"]),
        },
    )
    .unwrap();
    let versions = fx["events"]
        .as_array()
        .unwrap()
        .iter()
        .map(|e| {
            let cells: Vec<(i64, i64)> = e["cells"]
                .as_array()
                .unwrap()
                .iter()
                .map(|c| (c[0].as_i64().unwrap(), c[1].as_i64().unwrap()))
                .collect();
            tm.apply_path(
                &cells,
                f(&e["load_n"]),
                e["mission"].as_str().unwrap(),
                e["event_id"].as_str().unwrap(),
            )
            .unwrap()
        })
        .collect();
    (tm, versions)
}

#[test]
fn traffic_folds_hardens_and_chains_as_the_python_does() {
    let fx = fx();
    let (tm, versions) = folded(&fx);
    let want: Vec<u64> = fx["versions"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_u64().unwrap())
        .collect();
    assert_eq!(versions, want, "a re-committed event is a no-op");
    let chain = fx["chain"].as_array().unwrap();
    assert_eq!(tm.chain().len(), chain.len());
    for (r, w) in tm.chain().iter().zip(chain) {
        assert_eq!(r.event_id, w["event_id"].as_str().unwrap());
        assert_eq!(r.cells, w["cells"].as_u64().unwrap());
        assert_eq!(
            r.added_load_n.to_bits(),
            f(&w["added_load_n"]).to_bits(),
            "{}",
            r.event_id
        );
        assert_eq!(r.hash, w["hash"].as_str().unwrap(), "{} hash", r.event_id);
    }
    assert!(tm.verify_chain());
    let (s, m) = (soil(&fx), material(&fx));
    let h = Hardening {
        soil: &s,
        contact_len_m: f(&fx["contact_len_m"]),
        material: &m,
        gravity_ms2: f(&fx["g"]),
    };
    close_all(
        &tm.equilibrium_density(&h),
        &vf(&fx["equilibrium"]),
        "equilibrium",
    );
    close_all(
        &tm.densified_density(&h),
        &vf(&fx["densified"]),
        "densified",
    );
    close_all(&tm.relative_density(&h), &vf(&fx["relative"]), "relative");
    close_all(
        &tm.bearing_uplift_pa(&h, 0.30, 3.0),
        &vf(&fx["uplift"]),
        "uplift",
    );
    let sum = tm.summary(&h, 0.30, 3.0);
    let w = &fx["summary"];
    assert_eq!(
        sum.cells_trafficked as u64,
        w["cells_trafficked"].as_u64().unwrap()
    );
    assert_eq!(u64::from(sum.max_passes), w["max_passes"].as_u64().unwrap());
    assert_eq!(
        sum.cells_firm_dr_gt_0p5 as u64,
        w["cells_firm_dr_gt_0p5"].as_u64().unwrap()
    );
    for (got, key) in [
        (sum.max_load_cycles_n, "max_load_cycles_n"),
        (sum.peak_relative_density, "peak_relative_density"),
        (sum.peak_bearing_uplift_pa, "peak_bearing_uplift_pa"),
    ] {
        assert_eq!(got.to_bits(), f(&w[key]).to_bits(), "{key}");
    }
    // vacuity: the loaded pass firmed some road past the dry one
    assert!(sum.peak_bearing_uplift_pa > 0.0 && sum.max_passes == 3);
}

#[test]
fn the_python_npz_loads_and_a_rust_save_reloads_identically() {
    let fx = fx();
    let (ours, _) = folded(&fx);
    let py =
        TrafficMemory::load(&stewie_oracle::repo_root().join(fx["npz"].as_str().unwrap())).unwrap();
    assert!(py.verify_chain());
    assert_eq!(
        py, ours,
        "the Python file is the same memory, applied event ids included"
    );
    let dir = std::env::temp_dir().join(format!("stewie_tw_{}", std::process::id()));
    assert!(tw::load_site(&dir, "haworth").unwrap().is_none());
    let path = tw::save_site(&dir, &ours).unwrap();
    assert_eq!(path, dir.join("traffic_memory/haworth.npz"));
    let mut back = tw::load_site(&dir, "haworth").unwrap().unwrap();
    assert_eq!(back, ours);
    let before = tw::snapshot_site(&dir, "haworth").unwrap();
    // the loaded memory still remembers its folded events
    assert_eq!(
        back.apply_path(&[(0, 0)], 50.0, "m1", "m1:leg0").unwrap(),
        ours.version()
    );
    back.apply_path(&[(0, 0)], 50.0, "m3", "m3:leg0").unwrap();
    tw::save_site(&dir, &back).unwrap();
    tw::restore_site(&dir, "haworth", before.as_deref()).unwrap();
    assert_eq!(tw::load_site(&dir, "haworth").unwrap().unwrap(), ours);
    std::fs::remove_dir_all(&dir).unwrap();
}

#[test]
fn bad_fields_and_parameters_are_refused() {
    let p = TrafficParams {
        mass_areal: 130.0,
        sigma_c_n: 60.0,
        contact_width_m: 0.18,
    };
    let mut tm = TrafficMemory::new("s", 2, 2, 5.0, (0.0, 0.0), p).unwrap();
    assert!(tm.apply(&[0.0; 3], "m", "e1").is_err());
    assert!(tm.apply(&[f64::NAN, 0.0, 0.0, 0.0], "m", "e2").is_err());
    assert_eq!(tm.version(), 0);
    // negative loads count as zero; off-grid cells are dropped (SYNTHETIC inputs, labelled)
    tm.apply(&[-5.0, 0.0, 10.0, 0.0], "m", "e3").unwrap();
    assert_eq!(tm.passes(), &[0, 0, 1, 0]);
    tm.apply_path(&[(-1, 0), (0, 9), (1, 1)], 4.0, "m", "e4")
        .unwrap();
    assert_eq!(tm.chain()[1].cells, 1);
    let zero = TrafficParams {
        sigma_c_n: 0.0,
        ..p
    };
    assert!(TrafficMemory::new("s", 2, 2, 5.0, (0.0, 0.0), zero).is_err());
}
