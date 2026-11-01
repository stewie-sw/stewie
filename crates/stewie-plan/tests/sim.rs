//! The trip simulation against the Python oracle `sim_cases`: the `trips_cases` missions on the REAL Haworth route
//! window simulated in build order, one reversed, and two under SYNTHETIC mission-clock windows (labelled). Every
//! timeline span, every trip's times, the totals and the infeasibility messages must match.

use serde_json::Value;
use stewie_contracts::fleet::Fleet;
use stewie_physics::soil::SoilParams;
use stewie_plan::balance::{Profile, Routes};
use stewie_plan::mission::{Registries, mission_from_value};
use stewie_plan::sim::{SpanKind, simulate};
use stewie_plan::trips::{BuildInputs, PlannerParams, SlipModel, build_trips, context};
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

fn kind(k: SpanKind) -> &'static str {
    match k {
        SpanKind::Drive => "drive",
        SpanKind::Wait => "wait",
        SpanKind::Charge => "charge",
        SpanKind::Dig => "dig",
        SpanKind::Offload => "offload",
    }
}

#[test]
#[allow(clippy::too_many_lines)] // one run end to end: trips, timeline, trip times, totals
fn every_run_simulates_as_the_python_does() {
    let fx = stewie_oracle::load("sim_cases").unwrap().payload;
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
        let base_name = if name.starts_with("haul_two_pairs") || name.contains("window_closes") {
            "haul_two_pairs"
        } else {
            name
        };
        let mc = tc["missions"]
            .as_array()
            .unwrap()
            .iter()
            .find(|m| m["name"] == base_name)
            .unwrap();
        soil(&mc["soil"])
    };
    let mut kinds = std::collections::BTreeSet::new();
    for r in fx["runs"].as_array().unwrap() {
        let name = r["name"].as_str().unwrap();
        let m = mission_from_value(&r["payload"], &reg).unwrap();
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
        let order: Vec<usize> = r["order"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| usize::try_from(v.as_u64().unwrap()).unwrap())
            .collect();
        let cx = context(&m, &fleet, &params).unwrap();
        let mut routes = Routes::new(dem, 25.0, &m.keepouts);
        let (tl, times, core) = simulate(&m, &trips, &order, &cx, &mut routes).unwrap();
        let want_tl = r["timeline"].as_array().unwrap();
        assert_eq!(tl.len(), want_tl.len(), "{name} timeline length");
        for (k, (a, w)) in tl.iter().zip(want_tl).enumerate() {
            let tag = format!("{name} span {k}");
            assert_eq!(kind(a.kind), w["kind"].as_str().unwrap(), "{tag} kind");
            kinds.insert(kind(a.kind));
            for (got, key) in [
                (a.t0, "t0"),
                (a.t1, "t1"),
                (a.batt0, "batt0"),
                (a.batt1, "batt1"),
                (a.mass_kg, "mass"),
                (a.speed, "speed"),
                (a.from.0, "x0"),
                (a.from.1, "y0"),
                (a.to.0, "x1"),
                (a.to.1, "y1"),
            ] {
                close(got, f(&w[key]), &format!("{tag} {key}"));
            }
        }
        for (k, (a, w)) in times
            .iter()
            .zip(r["per_trip"].as_array().unwrap())
            .enumerate()
        {
            close(
                a.t_start,
                f(&w["t_start"]),
                &format!("{name} trip {k} start"),
            );
            close(a.t_end, f(&w["t_end"]), &format!("{name} trip {k} end"));
        }
        let c = &r["core"];
        for (got, key) in [
            (core.time_s, "time_s"),
            (core.mass_kg, "mass_kg"),
            (core.energy_j, "energy_J"),
            (core.distance_m, "distance_m"),
            (core.avg_power_w, "avg_power_w"),
        ] {
            close(got, f(&c[key]), &format!("{name} {key}"));
        }
        assert_eq!(
            core.charges,
            c["charges"].as_u64().unwrap(),
            "{name} charges"
        );
        assert_eq!(
            core.feasible,
            c["feasible"].as_bool().unwrap(),
            "{name} feasible"
        );
        let reasons: Vec<&str> = c["infeasible_reasons"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_str().unwrap())
            .collect();
        assert_eq!(core.infeasible_reasons, reasons, "{name} reasons");
    }
    assert_eq!(kinds.len(), 5, "vacuity: every span kind ran");
}
