//! Terrain Memory against the Python oracle `terrain_memory_cases`: mission deltas are `WorkSite` diffs on the
//! REAL Haworth 5 m bundle. The chain hashes match the Python's byte for byte (so numpy's pairwise sum and
//! Python's round are pinned bit-exactly on real heights first), the point-in-time queries and imprints match,
//! the Python's own `.npz` loads and verifies here, and a Rust-written file reloads to the same memory.

use std::path::Path;

use serde_json::Value;
use stewie_twin::numpy;
use stewie_twin::terrain_memory::{self as tmem, TerrainMemory};

fn fx() -> Value {
    stewie_oracle::load("terrain_memory_cases").unwrap().payload
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
            (a - b).abs() <= 1e-12 * b.abs().max(1.0),
            "{what}[{k}]: {a} vs {b}"
        );
    }
}

/// The Python's `base.derive_height()` on the real bundle: `datum + mass/density`, `datum = height - mass/density`.
fn haworth_heights() -> Vec<f64> {
    let dir = stewie_oracle::repo_root().join("samples/lunar_dem/haworth_10km_5m");
    let read = |n: &str| -> Vec<f64> {
        std::fs::read(dir.join(n))
            .unwrap()
            .chunks_exact(4)
            .map(|b| f64::from(f32::from_le_bytes([b[0], b[1], b[2], b[3]])))
            .collect()
    };
    let (h, m, d) = (
        read("heightmap.rf32"),
        read("mass_areal.rf32"),
        read("density.rf32"),
    );
    (0..h.len())
        .map(|i| (h[i] - m[i] / d[i]) + m[i] / d[i])
        .collect()
}

#[test]
fn numpy_sum_and_python_round_are_bit_exact_on_real_heights() {
    let fx = fx();
    // the oracle scales the real heights by 0.1 so the sums depend on the summation order
    let h: Vec<f64> = haworth_heights().iter().map(|v| v * 0.1).collect();
    for c in fx["pairwise_sums"].as_array().unwrap() {
        let n = usize::try_from(c["n"].as_u64().unwrap()).unwrap();
        assert_eq!(
            numpy::sum(&h[..n]).to_bits(),
            f(&c["sum"]).to_bits(),
            "sum of {n}"
        );
    }
    for c in fx["rounds"].as_array().unwrap() {
        assert_eq!(
            numpy::round(f(&c["x"]), 6).to_bits(),
            f(&c["r"]).to_bits(),
            "round {}",
            c["x"]
        );
    }
}

fn origin(v: &Value) -> (f64, f64) {
    (f(&v[0]), f(&v[1]))
}

/// The oracle's site memory rebuilt in Rust, with the placements it reported.
fn rebuilt(fx: &Value) -> TerrainMemory {
    let mut tm = TerrainMemory::new(
        fx["site"].as_str().unwrap(),
        20,
        20,
        f(&fx["cell_m"]),
        origin(&fx["origin"]),
    )
    .unwrap();
    for (k, m) in fx["missions"].as_array().unwrap().iter().enumerate() {
        let (name, mass) = (m["mission"].as_str().unwrap(), f(&m["mass_moved_kg"]));
        if m["kind"] == "subgrid" {
            let p = tm
                .apply_subgrid(
                    &vf(&m["delta"]),
                    12,
                    12,
                    origin(&m["sub_origin"]),
                    5.0,
                    name,
                    mass,
                )
                .unwrap();
            let want = &fx["placed"][k];
            assert_eq!(p.version, want["version"].as_u64().unwrap());
            assert_eq!(
                p.placed_cells as u64,
                want["placed_cells"].as_u64().unwrap()
            );
            assert_eq!(p.clipped, want["clipped"].as_bool().unwrap());
        } else {
            tm.apply(&vf(&m["delta"]), name, mass).unwrap();
        }
    }
    tm
}

#[track_caller]
fn check_chain(tm: &TerrainMemory, want: &Value) {
    let want = want.as_array().unwrap();
    assert_eq!(tm.chain().len(), want.len());
    for (r, w) in tm.chain().iter().zip(want) {
        assert_eq!(r.version, w["version"].as_u64().unwrap());
        assert_eq!(r.mission, w["mission"].as_str().unwrap());
        assert_eq!(
            r.mass_moved_kg.to_bits(),
            f(&w["mass_moved_kg"]).to_bits(),
            "{}",
            r.mission
        );
        assert_eq!(
            r.net_volume_m3.to_bits(),
            f(&w["net_volume_m3"]).to_bits(),
            "{}",
            r.mission
        );
        assert_eq!(r.hash, w["hash"].as_str().unwrap(), "{} hash", r.mission);
    }
    assert!(tm.verify_chain());
}

#[track_caller]
fn check_summary(tm: &TerrainMemory, want: &Value) {
    let s = tm.summary();
    assert_eq!(s.version, want["version"].as_u64().unwrap());
    assert_eq!(
        s.cells_changed as u64,
        want["cells_changed"].as_u64().unwrap()
    );
    for (got, key) in [
        (s.net_volume_m3, "net_volume_m3"),
        (s.max_cut_m, "max_cut_m"),
        (s.max_fill_m, "max_fill_m"),
    ] {
        assert_eq!(got.to_bits(), f(&want[key]).to_bits(), "{key}");
    }
    let missions: Vec<&str> = want["missions"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_str().unwrap())
        .collect();
    assert_eq!(s.missions, missions);
}

#[test]
fn missions_fold_chain_and_query_as_the_python_does() {
    let fx = fx();
    let b = &fx["before_revert"];
    let mut tm = rebuilt(&fx);
    check_chain(&tm, &b["chain"]);
    check_summary(&tm, &b["summary"]);
    close_all(tm.cumulative_delta(), &vf(&b["cumulative"]), "cumulative");
    for (v, want) in (1..=3).zip(b["delta_at"].as_array().unwrap()) {
        close_all(
            &tm.delta_at(v).unwrap(),
            &vf(want),
            &format!("delta_at {v}"),
        );
    }
    close_all(
        &tm.cumulative_delta_at(2).unwrap(),
        &vf(&b["cumulative_at_2"]),
        "cumulative_at 2",
    );
    close_all(
        &tm.height_at(&vf(&fx["base_0_20"]), 1).unwrap(),
        &vf(&b["height_at_1"]),
        "height_at 1",
    );
    let dem = vf(&fx["dem"]);
    let imprint = tm
        .imprint_on_dem(&dem, 40, 5.0, origin(&fx["dem_origin"]))
        .unwrap();
    close_all(&imprint, &vf(&b["imprint"]), "imprint");
    assert!(tm.delta_at(4).is_err() && tm.cumulative_delta_at(4).is_err());
    tm.revert_to(2).unwrap();
    let a = &fx["after_revert"];
    check_chain(&tm, &a["chain"]);
    check_summary(&tm, &a["summary"]);
    close_all(tm.cumulative_delta(), &vf(&a["cumulative"]), "after revert");
    assert!(tm.apply(&[0.0; 3], "ragged", 0.0).is_err());
    assert!(tm.apply(&[f64::NAN; 400], "nan", 0.0).is_err());
    assert!(
        tm.imprint_on_dem(&dem, 40, 1.0, (0.0, 0.0)).is_err(),
        "cell mismatch"
    );
}

#[test]
fn a_fine_memory_imprints_onto_the_coarse_dem_conserving_volume() {
    let fx = fx();
    let fine = &fx["fine"];
    let mut tm = TerrainMemory::new("haworth fine", 60, 60, 1.0, origin(&fine["origin"])).unwrap();
    let delta = vf(&fine["delta"]);
    tm.apply(
        &delta,
        fine["mission"].as_str().unwrap(),
        f(&fine["mass_moved_kg"]),
    )
    .unwrap();
    check_chain(&tm, &fine["chain"]);
    let dem = vf(&fx["dem"]);
    let got = tm
        .imprint_on_dem_resampled(&dem, 40, 5.0, origin(&fine["dem_origin"]))
        .unwrap();
    close_all(&got, &vf(&fine["resampled"]), "resampled");
    let added: f64 = got.iter().zip(&dem).map(|(a, b)| a - b).sum::<f64>() * 25.0;
    let built: f64 = delta.iter().sum::<f64>();
    assert!(
        (added - built).abs() < 1e-9 * built.abs().max(1.0),
        "volume {added} vs {built}"
    );
}

#[test]
fn the_python_npz_loads_verifies_and_a_rust_save_reloads_identically() {
    let fx = fx();
    let py =
        TerrainMemory::load(&stewie_oracle::repo_root().join(fx["npz"].as_str().unwrap())).unwrap();
    let ours = rebuilt(&fx);
    assert!(py.verify_chain());
    assert_eq!(
        py, ours,
        "the Python file is the same memory, history included"
    );
    let dir = std::env::temp_dir().join(format!("stewie_tm_{}", std::process::id()));
    let snapshot_none = tmem::snapshot_site(&dir, "haworth").unwrap();
    assert!(snapshot_none.is_none());
    let path = tmem::save_site(&dir, &ours).unwrap();
    assert_eq!(path, dir.join("terrain_memory/haworth.npz"));
    assert_eq!(tmem::load_site(&dir, "haworth").unwrap().unwrap(), ours);
    // compensation: snapshot, mutate and save, then restore the snapshot
    let before = tmem::snapshot_site(&dir, "haworth").unwrap().unwrap();
    let mut changed = ours.clone();
    changed.revert_to(1).unwrap();
    tmem::save_site(&dir, &changed).unwrap();
    tmem::restore_site(&dir, "haworth", Some(&before)).unwrap();
    assert_eq!(tmem::load_site(&dir, "haworth").unwrap().unwrap(), ours);
    tmem::restore_site(&dir, "haworth", None).unwrap();
    assert!(tmem::load_site(&dir, "haworth").unwrap().is_none());
    assert!(!Path::new(&format!("{}.part", path.display())).exists());
    std::fs::remove_dir_all(&dir).unwrap();
    assert_eq!(tmem::safe_site("../etc/pass wd"), "etcpasswd");
    assert_eq!(tmem::safe_site("//"), "site");
}

#[test]
fn an_edited_record_breaks_the_chain() {
    let fx = fx();
    let path = stewie_oracle::repo_root().join(fx["npz"].as_str().unwrap());
    let mut arrays = numpy::read_npz(std::fs::File::open(&path).unwrap()).unwrap();
    // SYNTHETIC tamper (labelled): rename one mission in the stored meta, re-written as a valid npz
    let Some(numpy::Array::Str(meta)) = arrays.get_mut("meta") else {
        panic!("no meta")
    };
    assert!(meta.contains("m2 dump"));
    *meta = meta.replace("m2 dump", "m2 fill");
    let dir = std::env::temp_dir().join(format!("stewie_tm_tamper_{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let p = dir.join("t.npz");
    let order = ["delta", "meta", "hist_idx", "hist_val", "hist_off"];
    let named: Vec<(&str, numpy::Array)> = order.iter().map(|k| (*k, arrays[*k].clone())).collect();
    numpy::write_npz(std::fs::File::create(&p).unwrap(), &named).unwrap();
    let tm = TerrainMemory::load(&p).unwrap();
    std::fs::remove_dir_all(&dir).unwrap();
    assert!(!tm.verify_chain(), "a renamed mission must break the chain");
}
