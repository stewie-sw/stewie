//! Pooled plan acceptance against the Python oracle `acceptance_cases`, on missions over the REAL Haworth route
//! window (layouts, footprint shapes, the edge order and design loads are SYNTHETIC, labelled in the oracle). The
//! Rust result is the Python's run with its column at bank density (D-R98); that run differs from the stock Python
//! only in the repose figures, which the oracle itself asserts.

use serde_json::Value;
use stewie_contracts::fleet::Fleet;
use stewie_physics::column::Regolith;
use stewie_physics::soil::{SoilParams, bundled};
use stewie_plan::acceptance::{AcceptanceInputs, AcceptanceParams, validate_plan};
use stewie_plan::mission::{Registries, mission_from_value};
use stewie_plan::trips::{PlannerParams, context};
use stewie_traverse::route::Dem;

fn f(v: &Value) -> f64 {
    v.as_f64().unwrap()
}

fn soil(s: &Value) -> SoilParams {
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

/// Structural equality with numbers compared to 1e-9 relative.
#[track_caller]
fn same(got: &Value, want: &Value, what: &str) {
    match (got, want) {
        (Value::Number(a), Value::Number(b)) => {
            let (a, b) = (a.as_f64().unwrap(), b.as_f64().unwrap());
            assert!(
                (a - b).abs() <= 1e-9 * b.abs().max(1.0),
                "{what}: {a} vs {b}"
            );
        }
        (Value::Object(a), Value::Object(b)) => {
            assert_eq!(
                a.keys().collect::<Vec<_>>(),
                b.keys().collect::<Vec<_>>(),
                "{what} keys"
            );
            for (k, v) in a {
                same(v, &b[k], &format!("{what}.{k}"));
            }
        }
        (Value::Array(a), Value::Array(b)) => {
            assert_eq!(a.len(), b.len(), "{what} length");
            for (k, (x, y)) in a.iter().zip(b).enumerate() {
                same(x, y, &format!("{what}[{k}]"));
            }
        }
        _ => assert_eq!(got, want, "{what}"),
    }
}

#[test]
#[allow(clippy::too_many_lines)] // setup shared by every case
fn acceptance_matches_the_python_at_bank_density() {
    let fx = stewie_oracle::load("acceptance_cases").unwrap().payload;
    let tc = stewie_oracle::load("trips_cases").unwrap().payload;
    let heights: Vec<f64> = stewie_oracle::load("route_cases").unwrap().payload["z"]
        .as_array()
        .unwrap()
        .iter()
        .map(f)
        .collect();
    let side = usize::try_from(tc["window"][2].as_u64().unwrap()).unwrap();
    let dem = Dem {
        z: &heights,
        width: side,
        height: side,
        cell_m: f(&tc["cell_m"]),
        origin: (f(&tc["origin"][0]), f(&tc["origin"][1])),
    };
    let fleet: Fleet =
        serde_json::from_str(include_str!("../../stewie-contracts/fixtures/fleet.json")).unwrap();
    let bodies: stewie_contracts::body::BodyRegistry =
        serde_json::from_str(include_str!("../../stewie-contracts/fixtures/bodies.json")).unwrap();
    let reg = Registries::new(&bodies, &fleet);
    let (breg, base) = bundled();
    let rho = breg["moon"].bulk_density.unwrap();
    let regolith = Regolith::new(rho, &base);
    let pp = &tc["params"];
    let params = PlannerParams {
        reserve_frac: f(&pp["reserve_frac"]),
        charge_w: f(&pp["charge_w"]),
        dig_rate_kg_s: f(&pp["dig_rate_kg_s"]),
        drive_speed_ms: f(&pp["drive_speed_ms"]),
        rolling_resistance: f(&pp["rolling_resistance"]),
        drivetrain_efficiency: f(&pp["drivetrain_efficiency"]),
        gravity_ms2: f(&pp["gravity_ms2"]),
    };
    let missions = tc["missions"].as_array().unwrap();
    let soil_of = |name: &str| {
        let key = if missions.iter().any(|m| m["name"] == name) {
            name
        } else {
            "haul_two_pairs"
        };
        soil(&missions.iter().find(|m| m["name"] == key).unwrap()["soil"])
    };
    let mut seen_repose_fix = false;
    for c in fx["cases"].as_array().unwrap() {
        let name = c["name"].as_str().unwrap();
        let m = mission_from_value(&c["payload"], &reg).unwrap();
        let ctx = context(&m, &fleet, &params).unwrap();
        let sp = soil_of(name);
        let inp = AcceptanceInputs {
            body_density: rho,
            regolith: &regolith,
            soil: &sp,
            gravity_ms2: params.gravity_ms2,
            drum_kg: ctx.drum_kg,
            dig_j_per_kg: ctx.dig_j_per_kg,
        };
        let k = &c["params"];
        let p = AcceptanceParams {
            cell_m: f(&k["cell_m"]),
            max_cells: usize::try_from(k["max_cells"].as_u64().unwrap()).unwrap(),
            regolith_depth_m: f(&k["regolith_depth_m"]),
            max_slope_deg: f(&k["max_slope_deg"]),
            accept_flatness_tol_m: f(&k["accept_flatness_tol_m"]),
            bearing_load_pa: k["bearing_load_pa"].as_f64(),
            bearing_fs: f(&k["bearing_fs"]),
        };
        let mut got = validate_plan(&m, dem, &inp, &p).unwrap();
        // the drift is summation noise on a ~1e9 kg column (each side sums in its own order); compare it to
        // 1 g, then the rest exactly
        let drift = f(&got["mass_drift_kg"]);
        assert!(
            (drift - f(&c["result"]["mass_drift_kg"])).abs() <= 1e-3,
            "{name} mass drift {drift}"
        );
        got["mass_drift_kg"] = c["result"]["mass_drift_kg"].clone();
        same(&got, &c["result"], name);
        seen_repose_fix |= c["result"]["repose"] != c["stock"]["repose"];
    }
    assert!(seen_repose_fix, "vacuity: D-R98 changes some repose figure");
}
