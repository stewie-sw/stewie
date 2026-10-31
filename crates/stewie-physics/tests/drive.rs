//! `drive_step` loops and `stability` against the Python oracle `drive_runs`: a plain drive on the REAL
//! Haworth crop, a SYNTHETIC ramp to entrapment (material, skid-steer, dig reaction) and a SYNTHETIC rock
//! field (labelled in the fixture). The Python's own soil set and material endpoints are passed for parity
//! (production takes them from the registry, D-R50).

use serde_json::Value;
use stewie_physics::column::{ColumnState, Fields, Regolith};
use stewie_physics::drive::{StepCommand, Telemetry, Vehicle, drive_step};
use stewie_physics::material::MaterialModel;
use stewie_physics::rover::Clast;
use stewie_physics::soil::{SoilParams, bundled};
use stewie_physics::stability::{Risk, stability, tip_tilt_limit_deg};

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

fn regolith() -> Regolith {
    let (reg, base) = bundled();
    Regolith::new(reg["moon"].bulk_density.unwrap(), &base)
}

#[allow(clippy::cast_possible_truncation)]
fn start(run: &Value) -> ColumnState {
    let rg = regolith();
    let (w, h) = (
        run["width"].as_u64().unwrap() as usize,
        run["height"].as_u64().unwrap() as usize,
    );
    let cell = f(&run["cell_m"]);
    match run["start"].as_str().unwrap() {
        "real" => {
            let p = stewie_oracle::load("column_ops").unwrap().payload;
            let i = &p["initial"];
            let fields = Fields {
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
            };
            ColumnState::new(w, h, cell, fields, 0.0, &rg).unwrap()
        }
        "ramp" => {
            let prof = vf(&run["ramp_profile"]);
            let mut fields = ColumnState::uniform(w, h, cell, &rg)
                .unwrap()
                .fields()
                .clone();
            fields.datum = (0..w * h).map(|i| prof[i % w]).collect();
            ColumnState::new(w, h, cell, fields, 0.0, &rg).unwrap()
        }
        _ => {
            let mut fields = ColumnState::uniform(w, h, cell, &rg)
                .unwrap()
                .fields()
                .clone();
            fields.datum = vf(&run["tilt_datum"]);
            ColumnState::new(w, h, cell, fields, 0.0, &rg).unwrap()
        }
    }
}

fn python_soil(fx: &Value) -> SoilParams {
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
        rho_surface: f(&s["rho_surface"]),
        rho_deep: f(&s["rho_deep"]),
        analog: false,
    }
}

fn python_material() -> MaterialModel {
    let m = stewie_oracle::load("excavation_cases").unwrap().payload["material"].clone();
    MaterialModel {
        rho_surface: f(&m["rho_surface"]),
        rho_deep: f(&m["rho_deep"]),
        phi_loose_deg: f(&m["phi_loose_deg"]),
        phi_dense_deg: f(&m["phi_dense_deg"]),
        cohesion_loose_pa: f(&m["cohesion_loose_pa"]),
        cohesion_dense_pa: f(&m["cohesion_dense_pa"]),
    }
}

fn check_step(t: &Telemetry, want: &Value, tag: &str) {
    assert_eq!(t.entrapped, want["entrapped"].as_bool().unwrap(), "{tag}");
    for (got, w, key) in [
        (t.rc.0, f(&want["rc"][0]), "rc row"),
        (t.rc.1, f(&want["rc"][1]), "rc col"),
        (t.yaw, f(&want["yaw"]), "yaw"),
        (t.v_achieved, f(&want["v_achieved"]), "v_achieved"),
        (
            t.omega_achieved,
            f(&want["omega_achieved"]),
            "omega_achieved",
        ),
        (t.slip, f(&want["slip"]), "slip"),
        (t.slope_rad, f(&want["slope_rad"]), "slope_rad"),
        (t.sinkage_m, f(&want["sinkage_m"]), "sinkage_m"),
        (t.contact_len_m, f(&want["contact_len_m"]), "contact_len_m"),
    ] {
        close(got, w, &format!("{tag} {key}"));
    }
    if let Some(sd) = t.sides {
        close(sd.slip_left, f(&want["slip_left"]), tag);
        close(sd.slip_right, f(&want["slip_right"]), tag);
        close(sd.scrub_factor, f(&want["scrub_factor"]), tag);
    }
}

#[test]
#[allow(clippy::cast_possible_truncation)]
fn every_drive_run_matches_the_oracle_step_by_step() {
    let fx = stewie_oracle::load("drive_runs").unwrap().payload;
    let soil = python_soil(&fx);
    let material = python_material();
    let veh = Vehicle {
        mass_kg: f(&fx["mass_kg"]),
        n_wheels: fx["n_wheels"].as_u64().unwrap() as u32,
        gauge_m: f(&fx["gauge_m"]),
        wheelbase_m: f(&fx["wheelbase_m"]),
        wheel_radius_m: f(&fx["wheel_radius_m"]),
        wheel_width_m: f(&fx["wheel_width_m"]),
        nominal_contact_len_m: f(&fx["contact_len_m"]),
        cg_height_m: f(&fx["cg_height_m"]),
        track_m: f(&fx["track_m"]),
    };
    let mut entrapped = 0;
    for run in fx["runs"].as_array().unwrap() {
        let name = run["name"].as_str().unwrap();
        let mut cs = start(run);
        let clasts: Vec<Clast> = run["clasts"]
            .as_array()
            .unwrap()
            .iter()
            .map(|k| Clast {
                center_m: [
                    f(&k["center_m"][0]),
                    f(&k["center_m"][1]),
                    f(&k["center_m"][2]),
                ],
                radius_m: f(&k["radius_m"]),
            })
            .collect();
        let start_kg = cs.total_mass();
        close(start_kg, f(&run["total_kg_start"]), name);
        let (mut rc, mut yaw) = match run["start"].as_str().unwrap() {
            "real" => ((16.0, 16.0), 0.4),
            "ramp" => ((32.0, 4.0), 0.0),
            _ => ((32.0, 10.0), 0.05),
        };
        for (i, (tw, want)) in run["twists"]
            .as_array()
            .unwrap()
            .iter()
            .zip(run["steps"].as_array().unwrap())
            .enumerate()
        {
            let cmd = StepCommand {
                v_cmd: f(&tw[0]),
                omega_cmd: f(&tw[1]),
                dt_s: 0.1,
                payload_kg: f(&run["payload_kg"]),
                gravity_ms2: f(&fx["g"]),
                dig_reaction_n: f(&run["dig_reaction"][i]),
                skid_steer: run["skid"].as_bool().unwrap(),
            };
            let mat = run["material"].as_bool().unwrap().then_some(&material);
            let t = drive_step(&mut cs, rc, yaw, &cmd, &veh, &soil, mat, &clasts).unwrap();
            check_step(&t, want, &format!("{name} step {i}"));
            entrapped += usize::from(t.entrapped);
            (rc, yaw) = (t.rc, t.yaw);
        }
        close(cs.total_mass(), start_kg, &format!("{name} conserves mass"));
        for (g, key) in [
            (&cs.fields().mass_areal, "mass_areal"),
            (&cs.fields().density, "density"),
        ] {
            for (a, b) in g.iter().zip(vf(&run[key])) {
                close(*a, b, &format!("{name} {key}"));
            }
        }
        let labels: Vec<u8> = run["state_label"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_u64().unwrap() as u8)
            .collect();
        assert_eq!(cs.fields().state_label, labels, "{name} labels");
    }
    assert!(entrapped > 10, "entrapment exercised: {entrapped}");
}

#[test]
fn stability_matches_and_fails_closed_on_nan() {
    let fx = stewie_oracle::load("drive_runs").unwrap().payload;
    close(
        tip_tilt_limit_deg(0.57, 0.40, 0.30),
        f(&fx["tip_limit_deg"]),
        "tip limit",
    );
    for s in fx["stability"].as_array().unwrap() {
        let pitch = s["pitch_deg"].as_f64().unwrap_or(f64::NAN);
        let got = stability(
            pitch,
            f(&s["roll_deg"]),
            0.57,
            0.40,
            0.30,
            f(&s["cg_dx_m"]),
            0.7,
        );
        let want = match s["risk"].as_str().unwrap() {
            "ok" => Risk::Ok,
            "warn" => Risk::Warn,
            _ => Risk::Tip,
        };
        assert_eq!(got.risk, want, "{s}");
        if pitch.is_finite() {
            close(got.margin_deg, f(&s["margin_deg"]), "margin");
            close(got.ssa_pitch_deg, f(&s["ssa_pitch_deg"]), "ssa pitch");
        } else {
            assert!(got.margin_deg == f64::NEG_INFINITY);
        }
    }
}
