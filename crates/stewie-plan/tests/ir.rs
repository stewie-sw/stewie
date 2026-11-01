//! The executable plan IR against the Python oracle `plan_ir_cases`, planned over the REAL Haworth route window
//! (layouts and the footprint shape are SYNTHETIC placements, labelled in the oracle). Where no action needs more
//! than one charge the Rust IR is the Python's, `plan_id` included. Where one does, Rust splits it into per-charge
//! parts (Aaron, D-R96): every other action is the Python's, the parts add up to the Python's action, and every
//! precondition fits a full battery. On a non-IPEx vehicle the drive legs are priced with that vehicle (D-R95).

use serde_json::Value;
use stewie_contracts::fleet::Fleet;
use stewie_physics::soil::SoilParams;
use stewie_plan::assemble::{PlanConfig, plan_and_simulate};
use stewie_plan::balance::Profile;
use stewie_plan::ir::plan_ir;
use stewie_plan::mission::{Registries, mission_from_value};
use stewie_plan::trips::{BuildInputs, PlannerParams, SlipModel, context};
use stewie_traverse::route::Dem;

fn f(v: &Value) -> f64 {
    v.as_f64().unwrap()
}

fn u(v: &Value) -> usize {
    usize::try_from(v.as_u64().unwrap()).unwrap()
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

/// Structural equality with numbers compared to 1e-9 relative, skipping the `skip` keys at the top level.
#[track_caller]
fn same(got: &Value, want: &Value, skip: &[&str], what: &str) {
    match (got, want) {
        (Value::Number(a), Value::Number(b)) => {
            let (a, b) = (a.as_f64().unwrap(), b.as_f64().unwrap());
            assert!(
                (a - b).abs() <= 1e-9 * b.abs().max(1.0),
                "{what}: {a} vs {b}"
            );
        }
        (Value::Object(a), Value::Object(b)) => {
            let keys = |o: &serde_json::Map<String, Value>| {
                o.keys()
                    .filter(|k| !skip.contains(&k.as_str()))
                    .cloned()
                    .collect::<Vec<_>>()
            };
            assert_eq!(keys(a), keys(b), "{what} keys");
            for k in keys(a) {
                same(&a[&k], &b[&k], &[], &format!("{what}.{k}"));
            }
        }
        (Value::Array(a), Value::Array(b)) => {
            assert_eq!(a.len(), b.len(), "{what} length");
            for (k, (x, y)) in a.iter().zip(b).enumerate() {
                same(x, y, &[], &format!("{what}[{k}]"));
            }
        }
        _ => assert_eq!(got, want, "{what}"),
    }
}

#[test]
#[allow(clippy::too_many_lines)] // setup shared by every case, then the three D-R95/D-R96 regimes
fn the_ir_is_the_pythons_except_for_the_per_charge_split() {
    let fx = stewie_oracle::load("plan_ir_cases").unwrap().payload;
    let tc = stewie_oracle::load("trips_cases").unwrap().payload;
    let heights: Vec<f64> = stewie_oracle::load("route_cases").unwrap().payload["z"]
        .as_array()
        .unwrap()
        .iter()
        .map(f)
        .collect();
    let side = u(&tc["window"][2]);
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
    let missions = tc["missions"].as_array().unwrap();
    let soil_of = |name: &str| {
        let key = if missions.iter().any(|m| m["name"] == name) {
            name
        } else {
            "haul_two_pairs"
        };
        soil(&missions.iter().find(|m| m["name"] == key).unwrap()["soil"])
    };
    let mut seen = [false; 3]; // identical, split, repriced
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
            algorithm: c["algorithm"].as_str().unwrap(),
            objective: c["objective"].as_str().unwrap(),
            vehicles: u(&c["vehicles"]),
            idle_power_w: 0.0,
            reallocate_stranded: true,
        };
        let plan = plan_and_simulate(&m, &fleet, &inp, &cfg).unwrap();
        let ctx = context(&m, &fleet, &params).unwrap();
        let got = plan_ir(&m, &plan, &ctx, dem, 25.0).unwrap();
        let want = &c["ir"];
        let battery = f(&c["ctx"]["battery_j"]);
        close_to(ctx.battery_j, battery, &format!("{name} battery"));
        // the IR verdict is the Python's walk over the D-R94 plan verdict
        let verdict = want["feasible"].as_bool().unwrap() && plan.totals.feasible;
        assert_eq!(got["feasible"], Value::Bool(verdict), "{name} feasible");
        for a in got["actions"].as_array().unwrap() {
            assert!(
                f(&a["pre"]["battery_J_min"]) <= battery + 0.05,
                "{name} action {} needs more than a full battery",
                a["id"]
            );
        }
        let ipex = c["vehicle"] == "ipex";
        let wa = want["actions"].as_array().unwrap();
        let splits = wa.iter().any(|a| f(&a["pre"]["battery_J_min"]) > battery);
        if ipex && !splits {
            same(&got, want, &["feasible"], name);
            seen[0] = true;
            continue;
        }
        assert_eq!(got["plan_id"].as_str().unwrap().len(), 16, "{name} plan_id");
        same(
            &got,
            want,
            &["feasible", "actions", "precedence", "plan_id"],
            name,
        );
        // walk the Python actions; each work action is one or more Rust parts
        let ga = got["actions"].as_array().unwrap();
        let (mut g, mut first_last) = (0, Vec::new());
        for w in wa {
            let tag = format!("{name} python action {}", w["id"]);
            if w["op"] == "GoTo" {
                let a = &ga[g];
                if ipex {
                    same(a, w, &["id"], &tag);
                } else {
                    same(a, w, &["id", "expect"], &tag);
                    let (d, de) = (f(&a["expect"]["distance_m"]), f(&w["expect"]["distance_m"]));
                    close_to(d, de, &format!("{tag} distance"));
                    let priced = d * f(&c["ctx"]["drive_j_per_m"]);
                    assert!(
                        (f(&a["expect"]["energy_J"]) - priced).abs() <= 0.25,
                        "{tag} vehicle-priced energy"
                    );
                    assert!(
                        (f(&a["expect"]["energy_J"]) - f(&w["expect"]["energy_J"])).abs() > 1.0,
                        "{tag} D-R95 differs"
                    );
                    seen[2] = true;
                }
                first_last.push((g, g));
                g += 1;
                continue;
            }
            let start = g;
            let n = ga[g].get("part").map_or(1, |p| u(&p[1]));
            let parts = &ga[g..g + n];
            g += n;
            first_last.push((start, g - 1));
            if n == 1 {
                let ignored: &[&str] = if ipex { &["id"] } else { &["id", "pre"] };
                same(&parts[0], w, ignored, &tag);
                continue;
            }
            seen[1] = true;
            assert!(
                f(&w["pre"]["battery_J_min"]) > battery,
                "{tag} split only when one charge cannot finish it"
            );
            let sum = |key: &str, sub: &str| parts.iter().map(|p| f(&p[key][sub])).sum::<f64>();
            let n_f = f64::from(u32::try_from(n).unwrap());
            for (key, sub) in [("expect", "energy_J"), ("expect", "duration_s")] {
                assert!(
                    (sum(key, sub) - f(&w[key][sub])).abs() <= 0.05 * n_f + 1e-6,
                    "{tag} parts add up to {key}.{sub}"
                );
            }
            let mass: f64 = parts.iter().map(|p| f(&p["mass_kg"])).sum();
            assert!(
                (mass - f(&w["mass_kg"])).abs() <= 0.05 * n_f + 1e-6,
                "{tag} part masses"
            );
            // the fewest equal parts that each fit one charge
            let cap = battery - f(&w["pre"]["reserve_J"]) - f(&w["pre"]["route_to_safe_J"]);
            let e = f(&w["expect"]["energy_J"]);
            assert!(
                e / (n_f - 1.0) > cap - 0.1 && e / n_f <= cap + 0.1,
                "{tag} {n} parts is the fewest"
            );
            for (k, p) in parts.iter().enumerate() {
                assert_eq!(p["part"], serde_json::json!([k + 1, n]), "{tag} part tag");
                same(
                    p,
                    w,
                    &["id", "part", "expect", "pre", "mass_kg", "loads", "haul_m"],
                    &format!("{tag} part {k}"),
                );
            }
        }
        assert_eq!(g, ga.len(), "{name} every Rust action accounted for");
        let want_prec: Vec<(usize, usize)> = want["precedence"]
            .as_array()
            .unwrap()
            .iter()
            .map(|e| (first_last[u(&e[0])].1, first_last[u(&e[1])].0))
            .collect();
        let got_prec: Vec<(usize, usize)> = got["precedence"]
            .as_array()
            .unwrap()
            .iter()
            .map(|e| (u(&e[0]), u(&e[1])))
            .collect();
        assert_eq!(got_prec, want_prec, "{name} precedence");
        for (k, a) in ga.iter().enumerate() {
            assert_eq!(u(&a["id"]), k, "{name} ids are positions");
        }
    }
    assert_eq!(
        seen, [true; 3],
        "vacuity: identical, split and repriced IRs all occur"
    );
}

#[track_caller]
fn close_to(a: f64, b: f64, what: &str) {
    assert!(
        (a - b).abs() <= 1e-9 * b.abs().max(1.0),
        "{what}: {a} vs {b}"
    );
}
