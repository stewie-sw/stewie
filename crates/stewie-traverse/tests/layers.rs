//! The AS-11 layered costmap against the Python oracle (`costmap_layers_cases`): on the real Haworth route
//! window, every context's composite cost (1e-9 relative), passable mask and first blocking layer per cell, each
//! layer's total and blocked count, and, for the defaults, every layer's block mask and the local-horizon lit
//! mask. The rover figures come from the IPEx rover profile and fleet registry, the soil from the body registry;
//! the masks, rocks and context settings are the oracle's SYNTHETIC ones.

use serde_json::Value;
use stewie_physics::soil::{SoilParams, bundled};
use stewie_traverse::layers::{Clast, Context, LAYER_NAMES, Rover, compose, horizon_clip};

fn f(v: &Value) -> f64 {
    v.as_f64().unwrap()
}

#[allow(clippy::cast_possible_truncation)] // the profile's wheel count, a small whole number
fn rover() -> Rover {
    let r: Value = serde_json::from_str(include_str!(
        "../../stewie-contracts/fixtures/rover_ipex.json"
    ))
    .unwrap();
    let fleet: Value =
        serde_json::from_str(include_str!("../../stewie-contracts/fixtures/fleet.json")).unwrap();
    let v = |k: &str| f(&r[k]["value"]);
    let ipex = &fleet["vehicles"]["ipex"];
    Rover {
        gauge_m: f(&ipex["gauge_m"]),
        wheelbase_m: f(&ipex["wheelbase_m"]),
        cg_height_m: v("cg_height_m"),
        mass_dry_kg: v("mass_dry_kg"),
        n_wheels: u32::try_from(r["n_wheels"]["value"].as_f64().unwrap() as i64).unwrap(),
        contact_len_m: v("contact_len_m"),
        contact_width_m: v("contact_width_m"),
        obstacle_height_m: v("obstacle_height_m"),
        rolling_resistance: v("rolling_resistance_coeff"),
        drive_speed_ms: v("drive_speed_ms"),
        drivetrain_efficiency: v("drivetrain_efficiency"),
    }
}

fn mask(v: &Value) -> Vec<bool> {
    v.as_array()
        .unwrap()
        .iter()
        .map(|x| x.as_i64().unwrap() != 0)
        .collect()
}

#[test]
#[allow(
    clippy::too_many_lines,
    clippy::cast_possible_truncation,
    clippy::many_single_char_names
)] // one context per case; the Python's z, w, h, g, s, c
fn the_layered_costmap_composes_as_the_python_does() {
    let fx = stewie_oracle::load("costmap_layers_cases").unwrap().payload;
    assert_eq!(
        fx["layer_names"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_str().unwrap())
            .collect::<Vec<_>>(),
        LAYER_NAMES
    );
    let rc = stewie_oracle::load("route_cases").unwrap().payload;
    let z: Vec<f64> = rc["z"].as_array().unwrap().iter().map(f).collect();
    let (w, h) = (
        rc["width"].as_u64().unwrap() as usize,
        rc["height"].as_u64().unwrap() as usize,
    );
    let (bodies, base) = bundled();
    let moon = SoilParams::for_body(&bodies, &base, "moon", false).unwrap();
    let g = bodies["moon"].g;
    let names: Vec<&str> = fx["reason_names"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_str().unwrap())
        .collect();
    for c in fx["cases"].as_array().unwrap() {
        let name = c["name"].as_str().unwrap();
        let s = &c["settings"];
        let get = |k: &str, d: f64| s.get(k).map_or(d, f);
        let keep = s.get("keepout_mask").map(|m| {
            mask(&Value::Array(
                m.as_array()
                    .unwrap()
                    .iter()
                    .flat_map(|r| r.as_array().unwrap().clone())
                    .collect(),
            ))
        });
        let resv = s.get("reserved_mask").map(|m| {
            mask(&Value::Array(
                m.as_array()
                    .unwrap()
                    .iter()
                    .flat_map(|r| r.as_array().unwrap().clone())
                    .collect(),
            ))
        });
        let clasts: Vec<Clast> = s.get("rock_clasts").map_or_else(Vec::new, |cl| {
            cl.as_array()
                .unwrap()
                .iter()
                .map(|k| Clast {
                    x_m: f(&k["center_m"][0]),
                    z_m: f(&k["center_m"][2]),
                    radius_m: f(&k["radius_m"]),
                    buried_frac: k.get("buried_frac").map_or(0.0, f),
                })
                .collect()
        });
        let mut soil = moon;
        if let Some(kp) = s.get("sinkage_k_phi") {
            soil.k_phi = f(kp);
        }
        // the Python CostmapContext's own settings where the case leaves them
        let ctx = Context {
            z: &z,
            width: w,
            height: h,
            cell_m: get("cell_m", 0.02),
            max_slope_deg: get("max_slope_deg", 25.0),
            slip_alpha: get("slip_alpha", 2.0),
            max_drop_m: get("max_drop_m", 0.15),
            sun_az_deg: get("sun_az_deg", 200.0),
            sun_el_deg: get("sun_el_deg", 12.0),
            payload_kg: get("payload_kg", 0.0),
            max_sinkage_m: get("max_sinkage_m", 0.10),
            gravity_ms2: g,
            soil,
            rover: rover(),
            keepout: keep.as_deref(),
            reserved: resv.as_deref(),
            clasts: &clasts,
        };
        let cm = compose(&ctx).unwrap();
        let want_cost: Vec<f64> = c["cost"].as_array().unwrap().iter().map(f).collect();
        for (i, (a, b)) in cm.cost.iter().zip(&want_cost).enumerate() {
            assert!(
                (a - b).abs() <= 1e-9 * b.abs().max(1.0),
                "{name} cost[{i}]: {a} vs {b}"
            );
        }
        assert_eq!(cm.passable, mask(&c["passable"]), "{name} passable");
        let want_reason: Vec<Option<&str>> = c["reason"]
            .as_array()
            .unwrap()
            .iter()
            .map(|r| usize::try_from(r.as_i64().unwrap()).ok().map(|k| names[k]))
            .collect();
        assert_eq!(cm.reason, want_reason, "{name} reasons");
        for (layer, total, blocked) in &cm.per_layer {
            let want = f(&c["per_layer_cost"][*layer]);
            assert!(
                (total - want).abs() <= 1e-9 * want.abs().max(1.0),
                "{name} {layer} total {total} vs {want}"
            );
            assert_eq!(
                *blocked as u64,
                c["per_layer_block"][*layer].as_u64().unwrap(),
                "{name} {layer} blocked"
            );
        }
        assert_eq!(
            cm.per_layer.len(),
            c["per_layer_block"].as_object().unwrap().len(),
            "{name} layer count"
        );
        if name == "defaults" {
            let lit = horizon_clip(&z, w, h, ctx.cell_m, ctx.sun_az_deg, ctx.sun_el_deg);
            assert_eq!(lit, mask(&c["lit"]), "the local-horizon lit mask");
        }
    }
}

#[test]
#[allow(clippy::cast_precision_loss)] // a fraction of a 10,000-cell window
fn the_local_horizon_march_is_the_bilinear_one() {
    // real sun positions where the window is partly lit: a nearest-cell march would light different cells
    let fx = stewie_oracle::load("costmap_layers_cases").unwrap().payload;
    let rc = stewie_oracle::load("route_cases").unwrap().payload;
    let z: Vec<f64> = rc["z"].as_array().unwrap().iter().map(f).collect();
    let (w, h) = (
        usize::try_from(rc["width"].as_u64().unwrap()).unwrap(),
        usize::try_from(rc["height"].as_u64().unwrap()).unwrap(),
    );
    let mut partly = false;
    for p in fx["horizon"].as_array().unwrap() {
        let (az, el) = (f(&p["sun_az_deg"]), f(&p["sun_el_deg"]));
        let want = mask(&p["lit"]);
        assert_eq!(horizon_clip(&z, w, h, 5.0, az, el), want, "sun {az}/{el}");
        let frac = want.iter().filter(|l| **l).count() as f64 / want.len() as f64;
        partly |= frac > 0.1 && frac < 0.9;
    }
    assert!(partly, "vacuity: a partly-lit sun position");
}
