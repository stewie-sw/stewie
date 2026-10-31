//! The worksite session against the Python oracle `worksite_native`: `WorkSite(fine_cell_m=None)` on the real
//! Haworth 5 m bundle. The streaming path (recenter, per-tick step, flatten, page out, dump, relax, page back,
//! edge clamp) and the single-window path (`open_window`, drive, flatten, dump, relax) must match to 1e-9; every
//! refusal must leave the session unchanged. The Python's own soil and vehicle values are passed for parity
//! (production takes them from the registry and the rover profile, D-R50 / D-R54).

use serde_json::Value;
use stewie_physics::column::Fields;
use stewie_physics::column::Regolith;
use stewie_physics::drive::Vehicle;
use stewie_physics::soil::{SoilParams, bundled};
use stewie_physics::worksite::{Setup, StepReport, WorkSite, WorkSiteError, refine_block};

fn f(v: &Value) -> f64 {
    v.as_f64().unwrap()
}

fn vf(v: &Value) -> Vec<f64> {
    v.as_array().unwrap().iter().map(f).collect()
}

#[track_caller]
fn close(got: f64, want: f64, what: &str) {
    assert!(
        (got - want).abs() <= 1e-9 * want.abs().max(1.0),
        "{what}: {got} vs {want}"
    );
}

#[track_caller]
fn close_all(got: &[f64], want: &[f64], what: &str) {
    assert_eq!(got.len(), want.len(), "{what} length");
    for (k, (a, b)) in got.iter().zip(want).enumerate() {
        close(*a, *b, &format!("{what}[{k}]"));
    }
}

fn fx() -> Value {
    stewie_oracle::load("worksite_native").unwrap().payload
}

fn regolith() -> Regolith {
    let (reg, base) = bundled();
    Regolith::new(reg["moon"].bulk_density.unwrap(), &base)
}

#[allow(clippy::cast_possible_truncation)]
fn python_setup(fx: &Value) -> Setup {
    let s = &fx["soil"];
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
        regolith: regolith(),
        gravity_ms2: f(&fx["g"]),
        v_max: f(&fx["v_max"]),
        tile_base_cells: fx["tile_base_cells"].as_u64().unwrap() as usize,
        fine_cell_m: None,
    }
}

fn open(fx: &Value) -> WorkSite {
    WorkSite::from_bundle(
        &stewie_oracle::repo_root().join(fx["bundle"].as_str().unwrap()),
        python_setup(fx),
    )
    .unwrap()
}

fn xy(v: &Value) -> (f64, f64) {
    (f(&v[0]), f(&v[1]))
}

#[track_caller]
fn check_window(ws: &WorkSite, want: &Value, tag: &str) {
    let cs = ws.fine().unwrap();
    assert_eq!(
        cs.width() as u64,
        want["width"].as_u64().unwrap(),
        "{tag} width"
    );
    assert_eq!(
        cs.height() as u64,
        want["height"].as_u64().unwrap(),
        "{tag} height"
    );
    let region: Vec<u64> = want["region"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_u64().unwrap())
        .collect();
    assert_eq!(
        ws.window_region_rc().unwrap().map(|v| v as u64).to_vec(),
        region,
        "{tag} region"
    );
    let (ox, oy) = ws.window_origin().unwrap();
    close(ox, f(&want["origin"][0]), &format!("{tag} origin x"));
    close(oy, f(&want["origin"][1]), &format!("{tag} origin y"));
    let fl = cs.fields();
    close_all(
        &fl.mass_areal,
        &vf(&want["mass_areal"]),
        &format!("{tag} mass_areal"),
    );
    close_all(
        &fl.density,
        &vf(&want["density"]),
        &format!("{tag} density"),
    );
    close_all(&fl.datum, &vf(&want["datum"]), &format!("{tag} datum"));
    close_all(
        &fl.disturbance,
        &vf(&want["disturbance"]),
        &format!("{tag} disturbance"),
    );
    let labels: Vec<u8> = want["state_label"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| u8::try_from(v.as_u64().unwrap()).unwrap())
        .collect();
    assert_eq!(fl.state_label, labels, "{tag} state_label");
    for (got, key) in [
        (ws.inventory_kg(), "inventory_kg"),
        (ws.peak_inventory_kg(), "peak_inventory_kg"),
        (ws.cut_total_kg(), "cut_total_kg"),
        (ws.placed_total_kg(), "placed_total_kg"),
        (ws.total_mass(), "total_mass"),
    ] {
        close(got, f(&want[key]), &format!("{tag} {key}"));
    }
    assert!(
        ws.conservation_residual() <= 1e-9 * ws.total_mass(),
        "{tag}: residual {} (Python {})",
        ws.conservation_residual(),
        f(&want["residual"])
    );
    assert_eq!(
        ws.recenters() as u64,
        want["recenters"].as_u64().unwrap(),
        "{tag} recenters"
    );
    let store = want["store"].as_array().unwrap();
    let got = ws.worked_tiles();
    assert_eq!(got.len(), store.len(), "{tag} store tiles");
    for (((tr, tc), sum), w) in got.iter().zip(store) {
        assert_eq!(
            (*tr, *tc),
            (w[0].as_i64().unwrap(), w[1].as_i64().unwrap()),
            "{tag} store key"
        );
        close(*sum, f(&w[2]), &format!("{tag} store ({tr},{tc})"));
    }
}

#[track_caller]
fn check_tick(r: &StepReport, ws: &WorkSite, want: &Value, tag: &str) {
    assert_eq!(
        r.drive.entrapped,
        want["entrapped"].as_bool().unwrap(),
        "{tag}"
    );
    assert_eq!(
        r.bounds_clamped,
        want["bounds_clamped"].as_bool().unwrap(),
        "{tag} clamp"
    );
    assert_eq!(
        r.recentered,
        want["recentered"].as_bool().unwrap(),
        "{tag} recentered"
    );
    for (got, key) in [
        (r.drive.v_achieved, "v_achieved"),
        (r.drive.omega_achieved, "omega_achieved"),
        (r.drive.slip, "slip"),
        (r.drive.sinkage_m, "sinkage_m"),
        (r.pose_xy.0, "x"),
        (r.pose_xy.1, "y"),
        (ws.yaw(), "yaw"),
    ] {
        let w = match key {
            "x" => &want["pose_xy"][0],
            "y" => &want["pose_xy"][1],
            k => &want[k],
        };
        close(got, f(w), &format!("{tag} {key}"));
    }
    let dirty: Vec<u64> = want["dirty"][0]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_u64().unwrap())
        .collect();
    assert_eq!(r.dirty.map(|v| v as u64).to_vec(), dirty, "{tag} dirty");
}

fn mask(ws: &WorkSite, rows: std::ops::Range<usize>, cols: std::ops::Range<usize>) -> Vec<bool> {
    let cs = ws.fine().unwrap();
    (0..cs.width() * cs.height())
        .map(|i| rows.contains(&(i / cs.width())) && cols.contains(&(i % cs.width())))
        .collect()
}

#[test]
#[allow(clippy::cast_possible_truncation)]
fn the_streaming_session_matches_the_oracle() {
    let fx = fx();
    let ck = &fx["checkpoints"];
    let mut ws = open(&fx);
    let (tf, theta) = (f(&fx["transfer_fraction"]), f(&fx["theta_r"]));
    close(ws.v_max, f(&fx["v_max"]), "v_max");
    close(ws.omega_max, f(&fx["omega_max"]), "omega_max");
    for (got, w) in ws.world().iter().zip(fx["world"].as_array().unwrap()) {
        close(*got, f(w), "world");
    }
    let start = xy(&fx["start_xy"]);
    assert!(ws.recenter(start, 1).unwrap());
    check_window(&ws, &ck["first"], "first");
    let cmd = xy(&fx["tick_cmd"]);
    let ticks = fx["ticks"].as_array().unwrap();
    for (i, want) in ticks.iter().enumerate() {
        let r = ws.step(cmd.0, cmd.1, f(&fx["dt"]), 0.0).unwrap();
        check_tick(&r, &ws, want, &format!("tick {i}"));
    }
    let moved = ws
        .flatten(&mask(&ws, 4..8, 4..8), f(&fx["cut_target_m"]), true)
        .unwrap();
    close(moved, f(&fx["moved_kg"]), "moved");
    check_window(&ws, &ck["flattened"], "flattened");
    assert!(ws.recenter(xy(&fx["far_xy"]), 1).unwrap());
    check_window(&ws, &ck["paged_out"], "paged_out");
    let half = 0.5 * ws.inventory_kg();
    let placed = ws.dump(&mask(&ws, 5..7, 5..7), Some(half)).unwrap();
    close(placed, f(&fx["placed_kg"]), "placed");
    let steps = ws.relax(400, theta, tf).unwrap();
    assert_eq!(
        steps as u64,
        fx["relax_steps"].as_u64().unwrap(),
        "relax steps"
    );
    check_window(&ws, &ck["dumped"], "dumped");
    assert!(ws.recenter(start, 1).unwrap());
    check_window(&ws, &ck["returned"], "returned");
    close_all(
        &ws.window_virgin_height().unwrap(),
        &vf(&fx["virgin_height"]),
        "virgin",
    );
    close_all(&ws.diff_field().unwrap(), &vf(&fx["diff"]), "diff");
    let e = &fx["edge_pose"];
    ws.set_pose(Some((f(&e[0]), f(&e[1]))), f(&e[2])).unwrap();
    for (i, want) in fx["edge_ticks"].as_array().unwrap().iter().enumerate() {
        let r = ws.step(0.25, 0.0, f(&fx["dt"]), 0.0).unwrap();
        check_tick(&r, &ws, want, &format!("edge tick {i}"));
    }
    check_window(&ws, &ck["edge"], "edge");
    // vacuity: the run cut, placed, paged out and clamped
    assert!(moved > 0.0 && placed > 0.0 && ws.recenters() >= 4 && !ws.worked_tiles().is_empty());
}

#[test]
fn the_single_window_session_matches_the_oracle() {
    let fx = fx();
    let s = &fx["single"];
    let mut ws = open(&fx);
    ws.open_window(xy(&s["base_rc"]), 8.0).unwrap();
    let twists: Vec<(f64, f64)> = s["twists"].as_array().unwrap().iter().map(xy).collect();
    let run = ws
        .drive(&twists, xy(&s["start_rc"]), 0.0, f(&fx["dt"]), None)
        .unwrap();
    let d = &s["drive"];
    close(run.commanded_dist_m, f(&d["commanded_dist_m"]), "commanded");
    close(run.achieved_dist_m, f(&d["achieved_dist_m"]), "achieved");
    close(run.final_rc.0, f(&d["final_rc"][0]), "final row");
    close(run.final_rc.1, f(&d["final_rc"][1]), "final col");
    close(run.final_yaw, f(&d["final_yaw"]), "final yaw");
    assert_eq!(run.any_entrapped, d["any_entrapped"].as_bool().unwrap());
    let n = ws.fine().unwrap().width() * ws.fine().unwrap().height();
    let moved = ws.flatten(&vec![true; n], f(&s["target_m"]), true).unwrap();
    close(moved, f(&s["moved_kg"]), "moved");
    let mut corner = vec![false; n];
    corner[0] = true;
    close(
        ws.dump(&corner, None).unwrap(),
        f(&s["placed_kg"]),
        "placed",
    );
    let steps = ws
        .relax(400, f(&fx["theta_r"]), f(&fx["transfer_fraction"]))
        .unwrap();
    assert_eq!(steps as u64, s["relax_steps"].as_u64().unwrap());
    check_window(&ws, &s["window"], "single");
    // the entry paths are mutually exclusive, and refusing changes nothing
    let before = ws.clone();
    assert!(matches!(
        ws.recenter(xy(&fx["start_xy"]), 1),
        Err(WorkSiteError::Path(_))
    ));
    assert!(matches!(
        ws.step(0.1, 0.0, 0.1, 0.0),
        Err(WorkSiteError::Path(_))
    ));
    assert!(matches!(
        ws.window_virgin_height(),
        Err(WorkSiteError::Path(_))
    ));
    assert_eq!(ws, before);
}

#[test]
fn every_refusal_leaves_the_session_unchanged() {
    let fx = fx();
    let mut ws = open(&fx);
    let start = xy(&fx["start_xy"]);
    assert!(
        matches!(ws.step(0.1, 0.0, 0.1, 0.0), Err(WorkSiteError::Path(_))),
        "no window yet"
    );
    ws.recenter(start, 1).unwrap();
    ws.step(0.2, 0.0, 0.1, 0.0).unwrap();
    let before = ws.clone();
    let (v, w) = (ws.v_max, ws.omega_max);
    for (cmd, what) in [
        ((f64::NAN, 0.0, 0.1), "non-finite v"),
        ((0.0, f64::INFINITY, 0.1), "non-finite omega"),
        ((0.1, 0.0, 0.0), "zero dt"),
        ((v * 1.01, 0.0, 0.1), "v over v_max"),
        ((0.0, -w * 1.01, 0.1), "omega over omega_max"),
    ] {
        assert!(
            matches!(
                ws.step(cmd.0, cmd.1, cmd.2, 0.0),
                Err(WorkSiteError::Command(_))
            ),
            "{what}"
        );
        assert_eq!(ws, before, "{what} changed the session");
    }
    let [x0, y0, ..] = ws.world();
    assert!(matches!(
        ws.recenter((x0 - 1.0e5, y0 - 1.0e5), 1),
        Err(WorkSiteError::Bounds(_))
    ));
    assert!(matches!(
        ws.open_window((10.0, 10.0), 8.0),
        Err(WorkSiteError::Path(_))
    ));
    assert!(matches!(
        ws.dump(&mask(&ws, 0..1, 0..1), Some(f64::NAN)),
        Err(WorkSiteError::Command(_))
    ));
    assert_eq!(
        ws, before,
        "a refused recenter, open_window or dump changed the session"
    );
}

#[test]
fn terrain_never_datum_verified_cannot_be_stepped() {
    let fx = fx();
    let setup = python_setup(&fx);
    let (base, origin) = stewie_physics::worksite::coarse_base_from_bundle(
        &stewie_oracle::repo_root().join(fx["bundle"].as_str().unwrap()),
        &setup.regolith,
    )
    .unwrap();
    let mut ws = WorkSite::new(base, origin, setup, false).unwrap();
    ws.recenter(xy(&fx["start_xy"]), 1).unwrap();
    let before = ws.clone();
    assert!(matches!(
        ws.step(0.1, 0.0, 0.1, 0.0),
        Err(WorkSiteError::Datum(_))
    ));
    assert_eq!(ws, before);
}

#[test]
fn a_bundle_with_a_wrong_sized_field_is_refused() {
    let src = stewie_oracle::repo_root().join("samples/lunar_dem/haworth_sfs_2km_1m");
    let dir = std::env::temp_dir().join(format!("stewie_worksite_bundle_{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    for name in [
        "metadata.json",
        "heightmap.rf32",
        "mass_areal.rf32",
        "density.rf32",
        "disturbance.rf32",
    ] {
        std::fs::copy(src.join(name), dir.join(name)).unwrap();
    }
    std::fs::write(dir.join("state_label.r8"), [0u8; 7]).unwrap();
    let err = stewie_physics::worksite::coarse_base_from_bundle(&dir, &regolith());
    std::fs::remove_dir_all(&dir).unwrap();
    assert!(matches!(err, Err(WorkSiteError::Bundle(_))), "{err:?}");
    // the real 1 m SFS bundle itself loads and passes the datum round-trip
    let (cs, _) = stewie_physics::worksite::coarse_base_from_bundle(&src, &regolith()).unwrap();
    assert!((cs.cell_m() - 1.0).abs() < 1e-12 && cs.width() > 1000);
}

#[test]
fn the_production_setup_takes_its_limits_from_the_rover_profile() {
    let profile: stewie_contracts::rover_profile::RoverProfile = serde_json::from_str(
        include_str!("../../stewie-contracts/fixtures/rover_ipex.json"),
    )
    .unwrap();
    let vehicle = Vehicle::from_profile(&profile);
    assert!(
        (vehicle.wheel_radius_m - 0.1525).abs() < 1e-12,
        "published wheel (D-R54)"
    );
    let fx = fx();
    let setup = Setup {
        vehicle,
        v_max: profile.drive_speed_ms.value,
        ..python_setup(&fx)
    };
    let ws = WorkSite::from_bundle(
        &stewie_oracle::repo_root().join(fx["bundle"].as_str().unwrap()),
        setup,
    )
    .unwrap();
    assert!((ws.v_max - 0.3).abs() < 1e-12);
    assert!((ws.omega_max - 2.0 * 0.3 / profile.track_gauge_m.value).abs() < 1e-12);
}

/// `worksite_native` carries the Python soil and vehicle; the refined oracle runs the same Python defaults.
fn refined() -> (Value, WorkSite) {
    let rf = stewie_oracle::load("worksite_refined").unwrap().payload;
    let setup = Setup {
        fine_cell_m: Some(f(&rf["fine_cell_m"])),
        ..python_setup(&fx())
    };
    let ws = WorkSite::from_bundle(
        &stewie_oracle::repo_root().join(rf["bundle"].as_str().unwrap()),
        setup,
    )
    .unwrap();
    (rf, ws)
}

fn fields(v: &Value) -> Fields {
    Fields {
        mass_areal: vf(&v["mass_areal"]),
        density: vf(&v["density"]),
        state_label: v["state_label"]
            .as_array()
            .unwrap()
            .iter()
            .map(|x| u8::try_from(x.as_u64().unwrap()).unwrap())
            .collect(),
        disturbance: vf(&v["disturbance"]),
        datum: vf(&v["datum"]),
        ice: None,
    }
}

/// Mean of base cell `(r, c)`'s `k x k` block in a refined field `w k` wide.
#[allow(clippy::cast_precision_loss)]
fn block_mean(fine: &[f64], (r, c): (usize, usize), w: usize, k: usize) -> f64 {
    (0..k * k)
        .map(|j| fine[(r * k + j / k) * w * k + c * k + j % k])
        .sum::<f64>()
        / (k * k) as f64
}

#[test]
#[allow(clippy::cast_possible_truncation)]
fn refinement_matches_the_python_overlay_where_it_conserves_and_never_creates_mass() {
    let rf = stewie_oracle::load("worksite_refined").unwrap().payload;
    let (mut matched, mut corrected) = (0, 0);
    for b in rf["blocks"].as_array().unwrap() {
        let (k, h, w) = (
            b["k"].as_u64().unwrap() as usize,
            b["height"].as_u64().unwrap() as usize,
            b["width"].as_u64().unwrap() as usize,
        );
        let base = fields(&b["base"]);
        let got = refine_block(&base, h, w, k);
        let want = fields(&b["fine"]);
        let tag = format!("k={k}");
        close_all(&got.density, &want.density, &format!("{tag} density"));
        close_all(&got.datum, &want.datum, &format!("{tag} datum"));
        close_all(
            &got.disturbance,
            &want.disturbance,
            &format!("{tag} disturbance"),
        );
        assert_eq!(got.state_label, want.state_label, "{tag} state_label");
        assert!(
            got.mass_areal.iter().all(|&m| m >= 0.0),
            "{tag}: negative mass"
        );
        for (cell, &m) in base.mass_areal.iter().enumerate() {
            let rc = (cell / w, cell % w);
            // coarsen(refine(base)) == base: no base cell gains or loses mass
            close(
                block_mean(&got.mass_areal, rc, w, k),
                m,
                &format!("{tag} block mean {rc:?}"),
            );
            let python_mean = block_mean(&want.mass_areal, rc, w, k);
            if (python_mean - m).abs() <= 1e-9 * m.abs().max(1.0) {
                for j in 0..k * k {
                    let i = (rc.0 * k + j / k) * w * k + rc.1 * k + j % k;
                    close(
                        got.mass_areal[i],
                        want.mass_areal[i],
                        &format!("{tag} mass {rc:?}[{j}]"),
                    );
                }
                matched += 1;
            } else {
                corrected += 1; // the Python's clamp created mass here (D-R77)
            }
        }
    }
    assert!(
        matched > 20 && corrected >= 2,
        "matched {matched}, corrected {corrected}"
    );
}

#[test]
fn the_refined_streaming_session_matches_the_oracle() {
    let (rf, mut ws) = refined();
    let base = fx();
    let ck = &rf["checkpoints"];
    let (tf, theta) = (f(&base["transfer_fraction"]), f(&base["theta_r"]));
    // on real terrain the thickness is uniform, so bicubic and bilinear refinement agree exactly
    assert!(
        f(&rf["bicubic_gap"]) == 0.0,
        "bicubic gap {}",
        rf["bicubic_gap"]
    );
    let start = xy(&rf["start_xy"]);
    assert!(ws.recenter(start, 1).unwrap());
    check_window(&ws, &ck["first"], "first");
    let cmd = xy(&rf["tick_cmd"]);
    for (i, want) in rf["ticks"].as_array().unwrap().iter().enumerate() {
        let r = ws.step(cmd.0, cmd.1, f(&base["dt"]), 0.0).unwrap();
        check_tick(&r, &ws, want, &format!("tick {i}"));
    }
    let moved = ws
        .flatten(&mask(&ws, 8..16, 8..16), f(&rf["cut_target_m"]), true)
        .unwrap();
    close(moved, f(&rf["moved_kg"]), "moved");
    assert!(ws.recenter(xy(&rf["far_xy"]), 1).unwrap());
    let half = 0.5 * ws.inventory_kg();
    close(
        ws.dump(&mask(&ws, 10..14, 10..14), Some(half)).unwrap(),
        f(&rf["placed_kg"]),
        "placed",
    );
    let steps = ws.relax(400, theta, tf).unwrap();
    assert_eq!(
        steps as u64,
        rf["relax_steps"].as_u64().unwrap(),
        "relax steps"
    );
    check_window(&ws, &ck["dumped"], "dumped");
    assert!(ws.recenter(start, 1).unwrap());
    check_window(&ws, &ck["returned"], "returned");
    close_all(
        &ws.window_virgin_height().unwrap(),
        &vf(&rf["virgin_height"]),
        "virgin",
    );
    close_all(&ws.diff_field().unwrap(), &vf(&rf["diff"]), "diff");
}

#[test]
fn the_refined_single_window_matches_the_oracle_and_a_non_integer_k_is_refused() {
    let (rf, mut ws) = refined();
    ws.open_window(xy(&rf["single"]["base_rc"]), 8.0).unwrap();
    check_window(&ws, &rf["single"]["window"], "single");
    let setup = Setup {
        fine_cell_m: Some(2.0),
        ..python_setup(&fx())
    };
    let err = WorkSite::from_bundle(
        &stewie_oracle::repo_root().join(rf["bundle"].as_str().unwrap()),
        setup,
    );
    assert!(
        matches!(err, Err(WorkSiteError::Command(_))),
        "5 m / 2 m is not an integer k"
    );
}
