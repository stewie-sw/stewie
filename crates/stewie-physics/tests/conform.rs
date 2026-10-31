//! `conform_pose` against the Python oracle `conform_cases`: the rest plane, tilt, contacts and per-wheel
//! normal loads on the REAL Haworth crop (5 m cells), with and without SYNTHETIC rocks (labelled), plus the
//! normal-reaction split at SYNTHETIC tilts past wheel lift-off.

use serde_json::Value;
use stewie_physics::rover::{Clast, ConformSetup, WHEELS, conform_pose, wheel_normal_reactions};

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

#[test]
#[allow(clippy::cast_possible_truncation)]
fn rest_poses_on_real_terrain_match_the_oracle() {
    let fx = stewie_oracle::load("conform_cases").unwrap().payload;
    let (w, h) = (
        fx["width"].as_u64().unwrap() as usize,
        fx["height"].as_u64().unwrap() as usize,
    );
    let hm: Vec<f64> = fx["heightmap"].as_array().unwrap().iter().map(f).collect();
    let mut rocks = 0;
    for c in fx["cases"].as_array().unwrap() {
        let clasts: Vec<Clast> = c["clasts"]
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
        rocks += usize::from(!clasts.is_empty());
        let setup = ConformSetup {
            cell_m: f(&fx["cell_m"]),
            world_x0: 0.0,
            world_y0: 0.0,
            climb_limit_m: f(&fx["climb_limit_m"]),
            min_grad_cells: f(&fx["min_grad_cells"]),
            gauge_m: f(&fx["gauge_m"]),
            wheelbase_m: f(&fx["wheelbase_m"]),
            cg_height_m: f(&fx["cg_height_m"]),
            total_weight_n: (f(&fx["mass_dry_kg"]) + f(&c["payload_kg"])) * f(&fx["g"]),
        };
        let p = conform_pose(
            &hm,
            w,
            h,
            (f(&c["center"][0]), f(&c["center"][1])),
            f(&c["heading"]),
            &clasts,
            &setup,
        );
        for k in 0..3 {
            close(p.up[k], f(&c["up"][k]), "up");
        }
        close(p.z_m, f(&c["z_m"]), "z");
        close(p.pitch_rad, f(&c["pitch_rad"]), "pitch");
        close(p.roll_rad, f(&c["roll_rad"]), "roll");
        close(
            p.normal_load_total_n,
            f(&c["normal_load_total_n"]),
            "total load",
        );
        for (k, name) in WHEELS.iter().enumerate() {
            close(p.contacts[k].0, f(&c["contacts"][name][0]), "contact row");
            close(p.contacts[k].1, f(&c["contacts"][name][1]), "contact col");
            close(p.normal_loads_n[k], f(&c["normal_loads"][name]), name);
        }
        let sum: f64 = p.normal_loads_n.iter().sum();
        close(sum, p.normal_load_total_n, "loads sum to the normal force");
    }
    assert!(rocks >= 32, "rock cases exercised: {rocks}");
}

#[test]
fn reactions_clamp_lifted_wheels_and_keep_the_total() {
    let fx = stewie_oracle::load("conform_cases").unwrap().payload;
    let mut lifted = 0;
    for r in fx["reactions"].as_array().unwrap() {
        let got = wheel_normal_reactions(
            f(&r["weight_n"]),
            f(&r["cos_tilt"]),
            f(&r["pitch_rad"]),
            f(&r["roll_rad"]),
            f(&fx["wheelbase_m"]),
            f(&fx["gauge_m"]),
            f(&fx["cg_height_m"]),
        );
        for k in 0..4 {
            close(got[k], f(&r["loads"][k]), "reaction");
            assert!(got[k] >= 0.0, "a wheel never pulls");
        }
        lifted += usize::from(got.contains(&0.0));
    }
    assert!(lifted > 10, "lift-off branch exercised: {lifted}");
}
