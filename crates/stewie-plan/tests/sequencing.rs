//! Sequencing against the Python oracle `sequencing_cases`: every algorithm and several objectives on missions
//! routed over the REAL Haworth route window (extra placements SYNTHETIC, labelled in the oracle), including
//! auto's Held-Karp + LK path, the brute-force-past-its-cap fallback and a budget penalty. The same order must
//! come out of every case, with the same resolved solver and optimality label; objective parsing must accept and
//! refuse the same specs.

use serde_json::Value;
use stewie_contracts::fleet::Fleet;
use stewie_physics::soil::SoilParams;
use stewie_plan::balance::{Profile, Routes};
use stewie_plan::mission::{Registries, mission_from_value};
use stewie_plan::optimize::{
    Sequencing, effective_algorithm, objective_optimality, optimize_sequence, parse_objective,
};
use stewie_plan::trips::{
    BuildInputs, PlannerParams, SlipModel, build_trips, context, trip_precedence,
};
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

#[test]
#[allow(clippy::too_many_lines)] // setup shared by every case
fn every_solver_picks_the_pythons_order() {
    let fx = stewie_oracle::load("sequencing_cases").unwrap().payload;
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
    let bv: Value =
        serde_json::from_str(include_str!("../../stewie-contracts/fixtures/bodies.json")).unwrap();
    let base: Value = serde_json::from_str(include_str!(
        "../../stewie-contracts/fixtures/soil_baseline.json"
    ))
    .unwrap();
    let rho = f(&bv["moon"]["bulk_density"]);
    let profile = Profile {
        rho_surface: rho,
        rho_deep: f(&base["rho_deep"]["value"]),
        z_t_m: f(&base["z_t_m"]["value"]),
    };
    let p = &tc["params"];
    let params = PlannerParams {
        reserve_frac: f(&p["reserve_frac"]),
        charge_w: f(&p["charge_w"]),
        dig_rate_kg_s: f(&p["dig_rate_kg_s"]),
        drive_speed_ms: f(&p["drive_speed_ms"]),
        rolling_resistance: f(&p["rolling_resistance"]),
        drivetrain_efficiency: f(&p["drivetrain_efficiency"]),
        gravity_ms2: f(&p["gravity_ms2"]),
    };
    let s = &tc["slip"];
    let slip = SlipModel {
        n_wheels: u32::try_from(s["n_wheels"].as_u64().unwrap()).unwrap(),
        contact_len_m: f(&s["contact_len_m"]),
        contact_width_m: f(&s["contact_width_m"]),
        z_entrap_m: f(&s["z_entrap_m"]),
    };
    let soil_of = |name: &str| {
        let key = if name == "heavy_rassor" {
            "heavy_rassor"
        } else {
            "haul_two_pairs"
        };
        let mc = tc["missions"]
            .as_array()
            .unwrap()
            .iter()
            .find(|m| m["name"] == key)
            .unwrap();
        soil(&mc["soil"])
    };
    let mut resolved_seen = std::collections::BTreeSet::new();
    for c in fx["cases"].as_array().unwrap() {
        let (name, algo, obj) = (
            c["mission"].as_str().unwrap(),
            c["algorithm"].as_str().unwrap(),
            c["objective"].as_str().unwrap(),
        );
        let tag = format!("{name} {algo} {obj}");
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
        let (trips, ..) = build_trips(&m, &fleet, &inp).unwrap();
        assert_eq!(
            trips.len() as u64,
            c["n_trips"].as_u64().unwrap(),
            "{tag} trips"
        );
        let prec = trip_precedence(&trips, &m);
        let cx = context(&m, &fleet, &params).unwrap();
        let mut routes = Routes::new(dem, 25.0, &m.keepouts);
        let weights = parse_objective(obj).unwrap();
        let mut seq = Sequencing {
            mission: &m,
            trips: &trips,
            ctx: &cx,
            routes: &mut routes,
            precedence: &prec,
        };
        let order = optimize_sequence(&mut seq, algo, &weights).unwrap();
        let want: Vec<usize> = c["order"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| usize::try_from(v.as_u64().unwrap()).unwrap())
            .collect();
        assert_eq!(order, want, "{tag} order");
        let resolved = effective_algorithm(algo, trips.len());
        assert_eq!(resolved, c["resolved"].as_str().unwrap(), "{tag} resolved");
        resolved_seen.insert(resolved.to_owned());
        let (label, exact) = objective_optimality(resolved, &weights);
        assert_eq!(label, c["label"][0].as_str().unwrap(), "{tag} label");
        assert_eq!(exact, c["label"][1].as_bool().unwrap(), "{tag} exact");
    }
    assert!(
        resolved_seen.contains("held_karp_lk") && resolved_seen.len() >= 7,
        "vacuity: {resolved_seen:?}"
    );
}

#[test]
fn objective_specs_parse_or_are_refused_as_the_python_does() {
    let fx = stewie_oracle::load("sequencing_cases").unwrap().payload;
    for c in fx["parses"].as_array().unwrap() {
        let spec = c["spec"].as_str().unwrap();
        match (parse_objective(spec), c.get("weights")) {
            (Ok(got), Some(want)) => {
                let want: Vec<(String, f64)> = want
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(|p| (p[0].as_str().unwrap().to_owned(), f(&p[1])))
                    .collect();
                assert_eq!(got, want, "{spec}");
            }
            (Err(_), None) => {}
            (got, _) => panic!("{spec}: {got:?} but the Python gave {c}"),
        }
    }
}
