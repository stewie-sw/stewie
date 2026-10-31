//! Rover ground effects against the Python oracle `rover_ops` (a SYNTHETIC 64x64 5 cm grid with a spoil
//! patch, labelled in the fixture): pose integration, four-wheel passes (constant and physical with slip),
//! a single rut, a drum cut with dump, `straight_path` (numpy half-to-even) and the yaw wrap.

use serde_json::Value;
use stewie_physics::column::{ColumnState, Regolith};
use stewie_physics::rover::{
    Compaction, drum_pass, four_wheel_pass, step_pose, straight_path, wheel_pass,
};
use stewie_physics::soil::{SoilParams, bundled};
use stewie_physics::terra::compaction_target_density;

fn f(v: &Value) -> f64 {
    v.as_f64().unwrap()
}

#[track_caller]
fn close(got: f64, want: f64, what: &str) {
    assert!(
        (got - want).abs() <= 1e-9 * want.abs().max(1.0),
        "{what}: {got} vs {want}"
    );
}

fn pairs(v: &Value) -> Vec<(f64, f64)> {
    v.as_array()
        .unwrap()
        .iter()
        .map(|p| (f(&p[0]), f(&p[1])))
        .collect()
}

/// The synthetic start: a uniform layer with the fixture's spoil patch.
#[allow(clippy::cast_possible_truncation)]
fn initial(fx: &Value) -> (ColumnState, Regolith, SoilParams) {
    let (reg, base) = bundled();
    let soil = SoilParams::for_body(&reg, &base, "moon", false).unwrap();
    let rg = Regolith::new(soil.rho_surface, &base);
    let cell = f(&fx["cell_m"]);
    let mut fields = ColumnState::uniform(64, 64, cell, &rg)
        .unwrap()
        .fields()
        .clone();
    fields.state_label = fx["initial_labels"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_u64().unwrap() as u8)
        .collect();
    (
        ColumnState::new(64, 64, cell, fields, 0.0, &rg).unwrap(),
        rg,
        soil,
    )
}

fn same_lines(got: &[Vec<(f64, f64)>; 4], want: &Value) {
    for (k, w) in ["LF", "RF", "LB", "RB"].iter().enumerate() {
        for (a, b) in got[k].iter().zip(pairs(&want[w])) {
            close(a.0, b.0, w);
            close(a.1, b.1, w);
        }
    }
}

#[test]
#[allow(clippy::cast_possible_truncation, clippy::cast_precision_loss)]
fn the_synthetic_drive_matches_the_oracle() {
    let fx = stewie_oracle::load("rover_ops").unwrap().payload;
    assert!(fx["synthetic"].as_bool().unwrap());
    let (mut cs, rg, soil) = initial(&fx);
    let cell = cs.cell_m();

    let (mut pose, mut yaw) = ((20.0, 10.0), 0.3);
    let mut poses = Vec::new();
    for (k, want) in fx["poses"].as_array().unwrap().iter().enumerate() {
        let omega = [0.0, 0.2, -0.4][k / 10];
        (pose, yaw) = step_pose(pose, yaw, 0.3, omega, 0.1, cell);
        close(pose.0, f(&want[0][0]), "pose row");
        close(pose.1, f(&want[0][1]), "pose col");
        close(yaw, f(&want[1]), "yaw");
        poses.push((pose, yaw));
    }
    let (gauge, base_m, ww) = (
        f(&fx["gauge_m"]),
        f(&fx["wheelbase_m"]),
        f(&fx["wheel_width_m"]),
    );
    let first = four_wheel_pass(
        &mut cs,
        &poses[..15],
        gauge,
        base_m,
        ww,
        rg.rho_deep,
        &Compaction::Constant(f(&fx["compaction"])),
    );
    let load = f(&fx["physical_load_n"]);
    let slip: Vec<f64> = fx["slip"].as_array().unwrap().iter().map(f).collect();
    let physical = Compaction::Physical {
        loads_n: [load; 4],
        slip: [slip[0], slip[1], slip[2], slip[3]],
        contact_len_m: f(&fx["contact_len_m"]),
        soil,
    };
    let second = four_wheel_pass(
        &mut cs,
        &poses[15..],
        gauge,
        base_m,
        ww,
        rg.rho_deep,
        &physical,
    );
    same_lines(&first, &fx["first_lines"]);
    same_lines(&second, &fx["second_lines"]);
    let path: Vec<(f64, f64)> = straight_path(5, 5, 40, 50, 1)
        .iter()
        .map(|&(r, c)| (r as f64, c as f64))
        .collect();
    assert_eq!(path, pairs(&fx["path"]));
    wheel_pass(&mut cs, &path, ww, f(&fx["compaction"]), rg.rho_deep);
    let before = cs.total_mass();
    close(before, f(&fx["total_kg_before_drum"]), "mass before drum");
    let moved = drum_pass(
        &mut cs,
        &pairs(&fx["swath"]),
        f(&fx["drum_depth_m"]),
        f(&fx["drum_width_m"]),
        Some(&pairs(&fx["dump"])),
        rg.rho_spoil,
    )
    .unwrap();
    assert!(moved > 0.0);
    close(moved, f(&fx["drum_moved_kg"]), "drum kg");
    close(cs.total_mass(), before, "drum pass conserves mass");
    let got = cs.fields();
    for (g, key) in [
        (&got.mass_areal, "mass_areal"),
        (&got.density, "density"),
        (&got.disturbance, "disturbance"),
    ] {
        for (a, b) in g.iter().zip(fx[key].as_array().unwrap()) {
            close(*a, f(b), key);
        }
    }
    let labels: Vec<u8> = fx["state_label"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_u64().unwrap() as u8)
        .collect();
    assert_eq!(got.state_label, labels);
    for code in 1..=4u8 {
        assert!(labels.contains(&code), "label {code} exercised");
    }
}

#[test]
#[allow(clippy::cast_possible_truncation)]
fn paths_wraps_and_compaction_targets_match() {
    let fx = stewie_oracle::load("rover_ops").unwrap().payload;
    for (k, want) in fx["paths"].as_object().unwrap() {
        let a: Vec<i64> = k.split(',').map(|x| x.parse().unwrap()).collect();
        let got = straight_path(a[0], a[1], a[2], a[3], a[4]);
        let w: Vec<(i64, i64)> = want
            .as_array()
            .unwrap()
            .iter()
            .map(|p| (p[0].as_i64().unwrap(), p[1].as_i64().unwrap()))
            .collect();
        assert_eq!(got, w, "{k}");
    }
    for w in fx["wraps"].as_array().unwrap() {
        let ((r, c), y) = step_pose((0.0, 0.0), f(&w[0]), 0.3, f(&w[1]), 0.5, 0.05);
        close(r, f(&w[2][0]), "wrap row");
        close(c, f(&w[2][1]), "wrap col");
        close(y, f(&w[3]), "wrapped yaw");
    }
    let (reg, base) = bundled();
    let soil = SoilParams::for_body(&reg, &base, "moon", false).unwrap();
    for t in fx["targets"].as_array().unwrap() {
        let got = compaction_target_density(f(&t[0]), f(&t[1]), 0.10, 0.18, f(&t[2]), &soil);
        close(got, f(&t[3]), "compaction target");
    }
}
