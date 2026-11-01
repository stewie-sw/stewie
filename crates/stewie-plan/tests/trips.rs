//! Trip construction against the Python oracle `trips_cases`: five missions routed over the REAL Haworth route
//! window (each free of cost ties, so the balance is unique), the planning context, every trip's energies, the
//! flows, the routing summary and geometry, trip precedence, and SYNTHETIC window gates (labelled). The
//! Python's own parameters and soil are passed for parity.

use std::collections::BTreeMap;

use serde_json::Value;
use stewie_contracts::fleet::Fleet;
use stewie_physics::soil::SoilParams;
use stewie_plan::balance::Profile;
use stewie_plan::mission::{Registries, mission_from_value};
use stewie_plan::trips::{
    BuildInputs, PlannerParams, SlipModel, TripKind, build_trips, context, precedence_is_feasible,
    trip_precedence, window_gate,
};
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

fn fleet() -> Fleet {
    serde_json::from_str(include_str!("../../stewie-contracts/fixtures/fleet.json")).unwrap()
}

fn registries() -> Registries {
    let bodies: stewie_contracts::body::BodyRegistry =
        serde_json::from_str(include_str!("../../stewie-contracts/fixtures/bodies.json")).unwrap();
    Registries::new(&bodies, &fleet())
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

fn params(p: &Value) -> PlannerParams {
    PlannerParams {
        reserve_frac: f(&p["reserve_frac"]),
        charge_w: f(&p["charge_w"]),
        dig_rate_kg_s: f(&p["dig_rate_kg_s"]),
        drive_speed_ms: f(&p["drive_speed_ms"]),
        rolling_resistance: f(&p["rolling_resistance"]),
        drivetrain_efficiency: f(&p["drivetrain_efficiency"]),
        gravity_ms2: f(&p["gravity_ms2"]),
    }
}

fn kind_name(k: TripKind) -> &'static str {
    match k {
        TripKind::Goto => "goto",
        TripKind::Import => "import",
        TripKind::Dig => "dig",
        TripKind::CutFill => "cutfill",
    }
}

fn pair(v: &Value) -> (f64, f64) {
    (f(&v[0]), f(&v[1]))
}

#[test]
#[allow(clippy::too_many_lines)] // one mission end to end: context, trips, flows, routes, precedence
fn trips_are_built_as_the_python_builds_them() {
    let fx = stewie_oracle::load("trips_cases").unwrap().payload;
    let heights: Vec<f64> = stewie_oracle::load("route_cases").unwrap().payload["z"]
        .as_array()
        .unwrap()
        .iter()
        .map(f)
        .collect();
    let side = usize::try_from(fx["window"][2].as_u64().unwrap()).unwrap();
    let dem = Dem {
        z: &heights,
        width: side,
        height: side,
        cell_m: f(&fx["cell_m"]),
        origin: pair(&fx["origin"]),
    };
    let bodies: Value =
        serde_json::from_str(include_str!("../../stewie-contracts/fixtures/bodies.json")).unwrap();
    let base: Value = serde_json::from_str(include_str!(
        "../../stewie-contracts/fixtures/soil_baseline.json"
    ))
    .unwrap();
    let rho = f(&bodies["moon"]["bulk_density"]);
    let profile = Profile {
        rho_surface: rho,
        rho_deep: f(&base["rho_deep"]["value"]),
        z_t_m: f(&base["z_t_m"]["value"]),
    };
    let p = params(&fx["params"]);
    let s = &fx["slip"];
    let slip = SlipModel {
        n_wheels: u32::try_from(s["n_wheels"].as_u64().unwrap()).unwrap(),
        contact_len_m: f(&s["contact_len_m"]),
        contact_width_m: f(&s["contact_width_m"]),
        z_entrap_m: f(&s["z_entrap_m"]),
    };
    let (reg, fl) = (registries(), fleet());
    let mut kinds = std::collections::BTreeSet::new();
    for c in fx["missions"].as_array().unwrap() {
        let name = c["name"].as_str().unwrap();
        let m = mission_from_value(&c["payload"], &reg).unwrap();
        let cx = context(&m, &fl, &p).unwrap();
        let w = &c["context"];
        for (got, key) in [
            (cx.dig_j_per_kg, "dig_j_per_kg"),
            (cx.drive_j_per_m, "drive_j_per_m"),
            (cx.battery_j, "battery_j"),
            (cx.drum_kg, "drum_kg"),
            (cx.rover_mass_kg, "rover_mass_kg"),
            (cx.drive_power_w, "drive_power_w"),
            (cx.reserve_frac, "reserve_frac"),
            (cx.charge_w, "charge_w"),
        ] {
            close(got, f(&w[key]), &format!("{name} context {key}"));
        }
        let sp = soil(&c["soil"]);
        let inp = BuildInputs {
            dem,
            max_traverse_slope_deg: 25.0,
            body_density: rho,
            profile: &profile,
            soil: &sp,
            slip: &slip,
            params: &p,
        };
        let (trips, flows, surplus, meta) = build_trips(&m, &fl, &inp).unwrap();
        let want = c["trips"].as_array().unwrap();
        assert_eq!(trips.len(), want.len(), "{name} trips");
        for (k, (t, wt)) in trips.iter().zip(want).enumerate() {
            let tag = format!("{name} trip {k}");
            assert_eq!(
                kind_name(t.kind),
                wt["kind"].as_str().unwrap(),
                "{tag} kind"
            );
            kinds.insert(kind_name(t.kind));
            assert_eq!(t.label, wt["label"].as_str().unwrap(), "{tag} label");
            assert_eq!(t.site, pair(&wt["site"]), "{tag} site");
            assert_eq!(t.dest, pair(&wt["dest"]), "{tag} dest");
            let actions: Vec<&str> = wt["actions"]
                .as_array()
                .unwrap()
                .iter()
                .map(|a| a.as_str().unwrap())
                .collect();
            assert_eq!(
                t.actions.iter().map(String::as_str).collect::<Vec<_>>(),
                actions,
                "{tag} actions"
            );
            for (got, key) in [
                (t.mass_kg, "mass"),
                (t.dig_e, "dig_e"),
                (t.dig_t, "dig_t"),
                (t.haul_m, "haul_m"),
                (t.haul_e, "haul_e"),
                (t.drive_e, "drive_e"),
                (t.slip_e, "slip_e"),
                (t.lift_e, "lift_e"),
                (t.offload_e, "offload_e"),
                (t.offload_t, "offload_t"),
            ] {
                close(got, f(&wt[key]), &format!("{tag} {key}"));
            }
        }
        let wf = c["flows"].as_array().unwrap();
        assert_eq!(flows.len(), wf.len(), "{name} flows");
        for (a, b) in flows.iter().zip(wf) {
            assert_eq!(
                a.cut.map(|v| v as u64),
                b["cut"].as_u64(),
                "{name} flow cut"
            );
            assert_eq!(
                a.fill.map(|v| v as u64),
                b["fill"].as_u64(),
                "{name} flow fill"
            );
            close(a.mass_kg, f(&b["mass_kg"]), &format!("{name} flow mass"));
        }
        close(surplus, f(&c["surplus_kg"]), &format!("{name} surplus"));
        let mm = &c["meta"];
        close(
            meta.straight_haul_m,
            f(&mm["straight_haul_m"]),
            &format!("{name} straight"),
        );
        close(
            meta.routed_haul_m,
            f(&mm["routed_haul_m"]),
            &format!("{name} routed"),
        );
        assert_eq!(
            meta.blocked_legs as u64,
            mm["blocked_legs"].as_u64().unwrap(),
            "{name} blocked"
        );
        assert_eq!(
            meta.feasible,
            mm["feasible"].as_bool().unwrap(),
            "{name} feasible"
        );
        let wr = c["routes"].as_array().unwrap();
        assert_eq!(meta.routes.len(), wr.len(), "{name} routes");
        for (r, w) in meta.routes.iter().zip(wr) {
            assert_eq!(r.reached, w["reached"].as_bool().unwrap());
            let wp: Vec<(f64, f64)> = w["waypoints"]
                .as_array()
                .unwrap()
                .iter()
                .map(pair)
                .collect();
            assert_eq!(r.waypoints, wp, "{name} route waypoints");
        }
        let prec = trip_precedence(&trips, &m);
        let want_prec: Vec<(usize, usize)> = c["precedence"]
            .as_array()
            .unwrap()
            .iter()
            .map(|p| {
                (
                    usize::try_from(p[0].as_u64().unwrap()).unwrap(),
                    usize::try_from(p[1].as_u64().unwrap()).unwrap(),
                )
            })
            .collect();
        assert_eq!(prec, want_prec, "{name} precedence");
        assert_eq!(
            precedence_is_feasible(trips.len(), &prec),
            c["precedence_feasible"].as_bool().unwrap()
        );
    }
    assert_eq!(kinds.len(), 4, "vacuity: every trip kind built");
    assert!(
        !precedence_is_feasible(2, &[(0, 1), (1, 0)]),
        "a cycle admits no order"
    );
}

#[test]
fn window_gates_open_idle_and_close_as_the_python_does() {
    let fx = stewie_oracle::load("trips_cases").unwrap().payload;
    let windows: BTreeMap<String, Vec<(f64, f64)>> = fx["windows"]
        .as_object()
        .unwrap()
        .iter()
        .map(|(k, v)| (k.clone(), v.as_array().unwrap().iter().map(pair).collect()))
        .collect();
    let none = BTreeMap::new();
    for g in fx["gates"].as_array().unwrap() {
        let w = if g.get("no_windows").is_some() {
            &none
        } else {
            &windows
        };
        let (start, wait, reason) = window_gate(w, g["class"].as_str().unwrap(), f(&g["t"]));
        let r = &g["result"];
        assert_eq!((start, wait), (f(&r[0]), f(&r[1])), "{g}");
        assert_eq!(reason.as_deref(), r[2].as_str(), "{g}");
    }
}
