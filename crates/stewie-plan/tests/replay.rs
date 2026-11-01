//! Ordered replay acceptance against the Python oracle `replay_cases`: each mission over the REAL Haworth route
//! window is planned (by the Rust planner, whose trips match the Python's) and its trips replayed in order through
//! the capacity-bounded drum; the report and every changed as-built cell match the Python run with its column at
//! bank density (D-R98). Layouts are SYNTHETIC placements (labelled in the oracle).

use serde_json::Value;
use stewie_contracts::fleet::Fleet;
use stewie_physics::column::Regolith;
use stewie_physics::soil::{SoilParams, bundled};
use stewie_plan::acceptance::{AcceptanceInputs, AcceptanceParams, execute_plan_acceptance};
use stewie_plan::assemble::{PlanConfig, plan_and_simulate};
use stewie_plan::balance::Profile;
use stewie_plan::mission::{Registries, mission_from_value};
use stewie_plan::trips::{BuildInputs, PlannerParams, SlipModel, context};
use stewie_traverse::route::Dem;

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

#[test]
#[allow(clippy::too_many_lines)] // setup shared by every case
fn ordered_replay_matches_the_python_at_bank_density() {
    let fx = stewie_oracle::load("replay_cases").unwrap().payload;
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
    let profile = Profile {
        rho_surface: rho,
        rho_deep: base.rho_deep.value,
        z_t_m: base.z_t_m.value,
    };
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
    let sl = &tc["slip"];
    let slip = SlipModel {
        n_wheels: u32::try_from(sl["n_wheels"].as_u64().unwrap()).unwrap(),
        contact_len_m: f(&sl["contact_len_m"]),
        contact_width_m: f(&sl["contact_width_m"]),
        z_entrap_m: f(&sl["z_entrap_m"]),
    };
    // validate_plan's defaults, as the Python replay uses them (recorded by acceptance_cases)
    let k = &stewie_oracle::load("acceptance_cases").unwrap().payload["cases"][0]["params"];
    let p = AcceptanceParams {
        cell_m: f(&k["cell_m"]),
        max_cells: usize::try_from(k["max_cells"].as_u64().unwrap()).unwrap(),
        regolith_depth_m: f(&k["regolith_depth_m"]),
        max_slope_deg: f(&k["max_slope_deg"]),
        accept_flatness_tol_m: f(&k["accept_flatness_tol_m"]),
        bearing_load_pa: None,
        bearing_fs: f(&k["bearing_fs"]),
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
    let mut verdicts = [false; 2];
    for c in fx["cases"].as_array().unwrap() {
        let name = c["name"].as_str().unwrap();
        let m = mission_from_value(&c["payload"], &reg).unwrap();
        let sp = soil_of(name);
        let inp = BuildInputs {
            dem,
            max_traverse_slope_deg: 25.0,
            body_density: rho,
            profile: &profile,
            soil: &sp,
            slip: &slip,
            params: &params,
        };
        let cfg = PlanConfig {
            algorithm: "nearest",
            objective: "time",
            vehicles: usize::try_from(c["vehicles"].as_u64().unwrap()).unwrap(),
            idle_power_w: 0.0,
            reallocate_stranded: true,
        };
        let plan = plan_and_simulate(&m, &fleet, &inp, &cfg).unwrap();
        let ctx = context(&m, &fleet, &params).unwrap();
        let ai = AcceptanceInputs {
            body_density: rho,
            regolith: &regolith,
            soil: &sp,
            gravity_ms2: params.gravity_ms2,
            drum_kg: ctx.drum_kg,
            dig_j_per_kg: ctx.dig_j_per_kg,
        };
        let (got, surface) = execute_plan_acceptance(&m, &plan.trips, dem, &ai, &p).unwrap();
        let (_, untouched) = execute_plan_acceptance(&m, &[], dem, &ai, &p).unwrap();
        let want = &c["result"];
        for key in ["feasible", "mass_conserved", "executes_ordered_ir"] {
            assert_eq!(got[key], want[key], "{name} {key}");
        }
        assert_eq!(got["grid"]["rows"], want["grid"]["rows"], "{name} rows");
        assert_eq!(got["grid"]["cols"], want["grid"]["cols"], "{name} cols");
        close(
            f(&got["grid"]["cell_m"]),
            f(&want["grid"]["cell_m"]),
            &format!("{name} cell"),
        );
        assert_eq!(
            got["shuttle_cycles"], want["shuttle_cycles"],
            "{name} shuttle cycles"
        );
        for key in [
            "drum_capacity_kg",
            "max_simultaneous_drum_kg",
            "running_drum_min_kg",
            "placed_kg",
        ] {
            close(f(&got[key]), f(&want[key]), &format!("{name} {key}"));
        }
        // summation noise on a ~1e9 kg column: 1 g
        assert!(
            (f(&got["mass_drift_kg"]) - f(&want["mass_drift_kg"])).abs() <= 1e-3,
            "{name} drift"
        );
        let changed: Vec<(usize, f64)> = surface
            .iter()
            .zip(&untouched)
            .map(|(a, b)| a - b)
            .enumerate()
            .filter(|(_, d)| d.abs() > 1e-12)
            .collect();
        let want_changed = want["changed"].as_array().unwrap();
        assert_eq!(changed.len(), want_changed.len(), "{name} changed cells");
        for ((i, d), w) in changed.iter().zip(want_changed) {
            assert_eq!(*i as u64, w[0].as_u64().unwrap(), "{name} changed index");
            assert!(
                (d - f(&w[1])).abs() <= 1e-9,
                "{name} cell {i}: {d} vs {}",
                w[1]
            );
        }
        verdicts[usize::from(want["feasible"].as_bool().unwrap())] = true;
    }
    assert_eq!(
        verdicts, [true; 2],
        "vacuity: feasible and infeasible replays both occur"
    );
}
