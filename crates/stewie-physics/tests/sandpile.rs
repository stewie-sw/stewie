//! Sandpile relaxation against the Python oracle `sandpile_runs`: a large pile on the real Haworth crop
//! relaxed under four configurations, and a SYNTHETIC flat layer (labelled) that reaches rest. Steps and
//! snapshot counts must match exactly; fields to 1e-9; grid mass must not change during relaxation.

use serde_json::Value;
use stewie_physics::column::{ColumnState, Fields, Regolith};
use stewie_physics::sandpile::{Sandpile, SandpileConfig};
use stewie_physics::soil::bundled;

fn regolith() -> Regolith {
    let (reg, base) = bundled();
    Regolith::new(reg["moon"].bulk_density.unwrap(), &base)
}

fn vf(v: &Value) -> Vec<f64> {
    v.as_array()
        .unwrap()
        .iter()
        .map(|x| x.as_f64().unwrap())
        .collect()
}

#[allow(clippy::cast_possible_truncation)]
fn real_crop() -> ColumnState {
    let p = stewie_oracle::load("column_ops").unwrap().payload;
    let i = &p["initial"];
    ColumnState::new(
        p["width"].as_u64().unwrap() as usize,
        p["height"].as_u64().unwrap() as usize,
        p["cell_m"].as_f64().unwrap(),
        Fields {
            mass_areal: vf(&i["mass_areal"]),
            density: vf(&i["density"]),
            state_label: i["state_label"]
                .as_array()
                .unwrap()
                .iter()
                .map(|x| x.as_u64().unwrap() as u8)
                .collect(),
            disturbance: vf(&i["disturbance"]),
            datum: vf(&i["datum"]),
            ice: None,
        },
        0.0,
        &regolith(),
    )
    .unwrap()
}

#[track_caller]
fn close_all(got: &[f64], want: &[f64], what: &str) {
    assert_eq!(got.len(), want.len());
    for (k, (a, b)) in got.iter().zip(want).enumerate() {
        assert!(
            (a - b).abs() <= 1e-9 * b.abs().max(1.0),
            "{what}[{k}]: {a} vs {b}"
        );
    }
}

#[test]
#[allow(clippy::cast_possible_truncation, clippy::cast_possible_wrap)]
fn every_relaxation_run_matches_the_oracle() {
    let fx = stewie_oracle::load("sandpile_runs").unwrap().payload;
    let r = regolith();
    let dep = &fx["deposit"];
    let mut rested = 0;
    for run in fx["runs"].as_array().unwrap() {
        let name = run["name"].as_str().unwrap();
        let mut cs = if name == "flat_synthetic" {
            ColumnState::uniform(32, 32, 5.0, &r).unwrap()
        } else {
            real_crop()
        };
        if run["sintered_floor"].as_bool().unwrap() {
            let ring: Vec<bool> = (0..1024)
                .map(|i| {
                    let (row, col) = (i / 32, i % 32);
                    let outer = (10..22).contains(&row) && (10..22).contains(&col);
                    let inner = (14..18).contains(&row) && (14..18).contains(&col);
                    outer && !inner
                })
                .collect();
            cs.sinter(&ring, r.rho_sintered).unwrap();
        }
        let cfg = SandpileConfig {
            theta_r: fx["theta_deg"].as_f64().unwrap().to_radians(),
            eight_connected: run["connectivity"].as_u64().unwrap() == 8,
            cohesion_steepening: run["cohesion_deg"].as_f64().unwrap().to_radians(),
            transfer_fraction: run["transfer_fraction"].as_f64().unwrap(),
        };
        let mut sp = Sandpile::new(&mut cs, cfg, r).unwrap();
        sp.deposit(
            dep["r"].as_i64().unwrap() as isize,
            dep["c"].as_i64().unwrap() as isize,
            dep["kg"].as_f64().unwrap(),
            dep["radius"].as_i64().unwrap() as isize,
            dep["spoil"].as_f64().unwrap(),
        )
        .unwrap();
        let (steps, snaps) = sp.relax_to_rest(
            fx["max_steps"].as_u64().unwrap() as usize,
            Some(fx["capture_every"].as_u64().unwrap() as usize),
            fx["eps_deg"].as_f64().unwrap().to_radians(),
        );
        assert_eq!(steps as u64, run["steps"].as_u64().unwrap(), "{name} steps");
        assert_eq!(
            snaps.len() as u64,
            run["n_snapshots"].as_u64().unwrap(),
            "{name} snapshots"
        );
        close_all(&snaps[snaps.len() / 2], &vf(&run["mid_snapshot"]), name);
        let want_kg = run["grid_kg_after_deposit"].as_f64().unwrap();
        assert!(
            (cs.grid_mass() - want_kg).abs() <= 1e-9 * want_kg,
            "{name}: grid mass moved"
        );
        close_all(&cs.fields().mass_areal, &vf(&run["mass_areal"]), name);
        close_all(&cs.fields().density, &vf(&run["density"]), name);
        close_all(&cs.derive_height(), &vf(&run["height"]), name);
        rested += usize::from(steps < 400);
    }
    // D-R52/D-R72: drained cells over steep bedrock no longer hold the pile open, so every run settles
    assert_eq!(
        rested,
        fx["runs"].as_array().unwrap().len(),
        "every run reaches rest"
    );
}

#[test]
fn bad_configs_and_off_grid_deposits_are_refused() {
    let r = regolith();
    let mut cs = ColumnState::uniform(8, 8, 1.0, &r).unwrap();
    let cfg = SandpileConfig {
        theta_r: 35f64.to_radians(),
        eight_connected: true,
        cohesion_steepening: 0.0,
        transfer_fraction: 0.0,
    };
    assert!(Sandpile::new(&mut cs, cfg, r).is_err());
    let mut sp = Sandpile::new(
        &mut cs,
        SandpileConfig {
            transfer_fraction: 0.5,
            ..cfg
        },
        r,
    )
    .unwrap();
    assert!(sp.deposit(-1, 0, 1.0, 0, r.rho_spoil).is_err());
    assert!(sp.deposit(40, 40, 1.0, 2, r.rho_spoil).is_err());
    assert!(sp.deposit(2, 2, -1.0, 0, r.rho_spoil).is_err());
    assert!(!sp.relax_step(), "a flat layer is already at rest");
}
