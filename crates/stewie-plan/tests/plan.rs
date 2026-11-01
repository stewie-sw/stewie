//! Plan assembly against the Python oracle `plan_cases`: one rover and fleets planned over the REAL Haworth
//! route window -- visit order, rover tags, trip windows, warnings, the core totals and labels, and every fleet
//! figure. Layouts, declared resources and observations, the closing recharge window and the idle draw are
//! SYNTHETIC settings (labelled in the oracle). A fleet's verdict is the D-R94 rule, not the Python's.

use serde_json::Value;
use stewie_contracts::fleet::Fleet;
use stewie_physics::soil::SoilParams;
use stewie_plan::assemble::{PlanConfig, plan_and_simulate};
use stewie_plan::balance::Profile;
use stewie_plan::mission::{Registries, mission_from_value};
use stewie_plan::report::{ReportParams, energy_ledger, report_totals};
use stewie_plan::trips::{BuildInputs, PlannerParams, SlipModel, context};
use stewie_traverse::route::Dem;

fn f(v: &Value) -> f64 {
    v.as_f64().unwrap()
}

fn u(v: &Value) -> usize {
    usize::try_from(v.as_u64().unwrap()).unwrap()
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

fn strs(v: &Value) -> Vec<String> {
    v.as_array()
        .unwrap()
        .iter()
        .map(|s| s.as_str().unwrap().to_owned())
        .collect()
}

#[test]
#[allow(clippy::too_many_lines)] // setup shared by every case, then every reported figure
fn plans_match_the_python_planner() {
    let fx = stewie_oracle::load("plan_cases").unwrap().payload;
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
        } else if name.starts_with("heavy") {
            "heavy_rassor"
        } else {
            "haul_two_pairs"
        };
        soil(&missions.iter().find(|m| m["name"] == key).unwrap()["soil"])
    };
    let mut d_r94_differs = false;
    let mut report_regimes = [false; 3]; // IPEx exact, operator factor, other vehicle
    let rp = &fx["report_params"];
    let ipex_mass = f(&rp["ipex_rover_mass_kg"]);
    let report_params = ReportParams {
        drum_rate_ratio: f(&rp["drum_rate_ratio"]),
        max_cut_per_pass_m: f(&rp["max_cut_per_pass_m"]),
        fill_mpe_frac: f(&rp["fill_mpe_frac"]),
        localization_margin_m: f(&rp["localization_margin_m"]),
        // the Python writes this sigma inline in its uncertainty block
        dem_cell_sigma_m: f(
            &fx["cases"][0]["report"]["plan_uncertainty"]["sources"]["dem"]["cell_sigma_m"],
        ),
        relocalize_drift_tol_m: f(&rp["relocalize_drift_tol_m"]),
        drift_frac: f(&rp["drift_frac"]),
        fix_maneuver_s: f(&rp["fix_maneuver_s"]),
        arm_lift_height_m: f(&rp["arm_lift_height_m"]),
        arm_lift_efficiency: f(&rp["arm_lift_efficiency"]),
        gravity_ms2: params.gravity_ms2,
        default_return_buffer_frac: f(&rp["default_return_buffer_frac"]),
    };
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
            idle_power_w: f(&c["idle_power_w"]),
            reallocate_stranded: true,
        };
        let plan = plan_and_simulate(&m, &fleet, &inp, &cfg).unwrap();
        let ctx = context(&m, &fleet, &params).unwrap();
        check_report(
            c,
            &m,
            &plan,
            &ctx,
            (rho, &profile),
            (&report_params, ipex_mass),
        );
        report_regimes[usize::from(m.dig_energy_factor.is_some())] = true;
        report_regimes[2] |= m.vehicle != "ipex";
        let sites: Vec<(f64, f64)> = c["sites"]
            .as_array()
            .unwrap()
            .iter()
            .map(|s| (f(&s[0]), f(&s[1])))
            .collect();
        assert_eq!(
            plan.trips.iter().map(|t| t.site).collect::<Vec<_>>(),
            sites,
            "{name} visit order"
        );
        assert_eq!(
            plan.vehicle,
            c["vehicle"]
                .as_array()
                .unwrap()
                .iter()
                .map(u)
                .collect::<Vec<_>>(),
            "{name} rover tags"
        );
        assert_eq!(
            plan.times.len(),
            c["times"].as_array().unwrap().len(),
            "{name} windows"
        );
        for (k, w) in plan.times.iter().enumerate() {
            assert_eq!(plan.trips[w.trip].site, sites[k], "{name} window {k} trip");
            close(
                w.t_start,
                f(&c["times"][k][0]),
                &format!("{name} window {k} start"),
            );
            close(
                w.t_end,
                f(&c["times"][k][1]),
                &format!("{name} window {k} end"),
            );
        }
        assert_eq!(plan.warnings, strs(&c["warnings"]), "{name} warnings");
        let t = &plan.totals;
        let w = &c["totals"];
        for (got, key) in [
            (t.time_s, "time_s"),
            (t.mass_kg, "mass_kg"),
            (t.energy_j, "energy_J"),
            (t.distance_m, "distance_m"),
            (t.avg_power_w, "avg_power_w"),
            (t.survival_energy_j, "survival_energy_J"),
            (t.makespan_s, "makespan_s"),
        ] {
            close(got, f(&w[key]), &format!("{name} {key}"));
        }
        assert_eq!(t.charges, w["charges"].as_u64().unwrap(), "{name} charges");
        assert_eq!(
            t.resolved_algorithm,
            w["resolved_algorithm"].as_str().unwrap(),
            "{name} resolved"
        );
        assert_eq!(
            t.optimality,
            w["optimality"].as_str().unwrap(),
            "{name} optimality"
        );
        assert_eq!(
            t.objective_exact,
            w["objective_exact"].as_bool().unwrap(),
            "{name} exact"
        );
        assert_eq!(
            t.solved_metric,
            w["solved_metric"].as_str().unwrap(),
            "{name} metric"
        );
        assert_eq!(t.n_precedence, u(&w["n_precedence"]), "{name} precedence");
        assert_eq!(
            t.vehicle_conflicts,
            u(&w["vehicle_conflicts"]),
            "{name} site conflicts"
        );
        assert_eq!(
            t.charger_conflicts,
            u(&w["charger_conflicts"]),
            "{name} charger conflicts"
        );
        assert_eq!(
            plan.meta.blocked_legs,
            u(&w["blocked_legs"]),
            "{name} blocked legs"
        );
        let py_reasons = strs(&w["infeasible_reasons"]);
        let Some(ft) = &t.fleet else {
            assert_eq!(
                t.feasible,
                w["feasible"].as_bool().unwrap(),
                "{name} feasible"
            );
            assert_eq!(t.infeasible_reasons, py_reasons, "{name} reasons");
            continue;
        };
        let fw = &c["fleet"];
        for (got, key) in [
            (ft.makespan_parallel_s, "makespan_parallel_s"),
            (ft.charger_wait_s, "charger_wait_s"),
            (ft.crowd_wait_s, "crowd_wait_s"),
            (ft.precedence_wait_s, "precedence_wait_s"),
            (ft.resource_wait_s, "resource_wait_s"),
            (ft.observation_wait_s, "observation_wait_s"),
        ] {
            close(got, f(&fw[key]), &format!("{name} {key}"));
        }
        let want_rw: Vec<(String, f64)> = fw["resource_waits"]
            .as_array()
            .unwrap()
            .iter()
            .map(|e| (e[0].as_str().unwrap().to_owned(), f(&e[1])))
            .collect();
        assert_eq!(
            ft.resource_waits.len(),
            want_rw.len(),
            "{name} resource waits"
        );
        for ((a, x), (b, y)) in ft.resource_waits.iter().zip(&want_rw) {
            assert_eq!(a, b, "{name} resource id");
            close(*x, *y, &format!("{name} resource {a}"));
        }
        assert_eq!(
            ft.temporal_conflicts,
            u(&fw["temporal_conflicts"]),
            "{name} temporal"
        );
        assert_eq!(
            ft.haul_path_conflicts,
            u(&fw["haul_path_conflicts"]),
            "{name} haul paths"
        );
        assert_eq!(
            ft.fleet_needs_replan,
            fw["fleet_needs_replan"].as_bool().unwrap(),
            "{name} needs replan"
        );
        assert_eq!(
            ft.fleet_replanned,
            fw["fleet_replanned"].as_bool().unwrap(),
            "{name} replanned"
        );
        assert_eq!(
            ft.unreallocatable_trips,
            u(&fw["unreallocatable_trips"]),
            "{name} dropped"
        );
        let detail = fw["detail"].as_array().unwrap();
        assert_eq!(ft.detail.len(), detail.len(), "{name} rovers");
        for (d, e) in ft.detail.iter().zip(detail) {
            let v = d.vehicle;
            assert_eq!(v, u(&e["vehicle"]), "{name} rover index");
            assert_eq!(d.n_trips, u(&e["n_trips"]), "{name} rover {v} trips");
            assert_eq!(
                d.charges,
                e["charges"].as_u64().unwrap(),
                "{name} rover {v} charges"
            );
            for (got, key) in [
                (d.time_s, "time_s"),
                (d.energy_j, "energy_J"),
                (d.distance_m, "distance_m"),
                (d.charger_wait_s, "charger_wait_s"),
                (d.crowd_wait_s, "crowd_wait_s"),
                (d.precedence_wait_s, "precedence_wait_s"),
            ] {
                close(got, f(&e[key]), &format!("{name} rover {v} {key}"));
            }
            let track: Vec<(f64, f64)> = e["track"]
                .as_array()
                .unwrap()
                .iter()
                .map(|p| (f(&p[0]), f(&p[1])))
                .collect();
            assert_eq!(d.track, track, "{name} rover {v} track");
            assert_eq!(
                d.health.health,
                e["health"]["health"].as_str().unwrap(),
                "{name} rover {v} health"
            );
            close(
                d.health.min_batt_frac,
                f(&e["health"]["min_batt_frac"]),
                &format!("{name} rover {v} margin"),
            );
        }
        // D-R94: infeasible when the routes are blocked, any rover is infeasible, or work was dropped
        let all_rovers_ok = detail
            .iter()
            .all(|e| e["health"]["feasible"].as_bool().unwrap());
        let want = w["feasible"].as_bool().unwrap()
            && all_rovers_ok
            && u(&fw["unreallocatable_trips"]) == 0;
        assert_eq!(t.feasible, want, "{name} fleet verdict (D-R94)");
        assert!(
            t.infeasible_reasons.starts_with(&py_reasons),
            "{name} route reasons first"
        );
        assert_eq!(
            t.feasible,
            t.infeasible_reasons.is_empty(),
            "{name} a verdict carries its reasons"
        );
        d_r94_differs |= t.feasible != w["feasible"].as_bool().unwrap();
    }
    assert!(
        d_r94_differs,
        "vacuity: some fleet the Python calls feasible strands a rover"
    );
    assert_eq!(
        report_regimes, [true; 3],
        "vacuity: exact, factored and non-IPEx reports all occur"
    );
    for r in fx["refusals"].as_array().unwrap() {
        let m = mission_from_value(&r["payload"], &reg).unwrap();
        let sp = soil_of("haul_two_pairs");
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
            vehicles: u(&r["vehicles"]),
            idle_power_w: 0.0,
            reallocate_stranded: true,
        };
        let err = plan_and_simulate(&m, &fleet, &inp, &cfg).unwrap_err();
        assert_eq!(
            err,
            r["error"].as_str().unwrap(),
            "refusal with {} rovers",
            cfg.vehicles
        );
    }
}

/// Structural equality with numbers compared to 1e-9 relative, skipping the `skip` keys at the top level.
#[track_caller]
fn same(got: &Value, want: &Value, skip: &[&str], what: &str) {
    match (got, want) {
        (Value::Number(a), Value::Number(b)) => {
            close(a.as_f64().unwrap(), b.as_f64().unwrap(), what);
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

/// The report totals and ledger against the Python's: exact for an IPEx plan with no operator factor; D-R97 for
/// the dig band (the plan's own dig energy) and the relocalization fix (the vehicle's own mass, where the Python
/// lifts the IPEx mass `ipex_mass`).
#[track_caller]
fn check_report(
    c: &Value,
    m: &stewie_plan::mission::Mission,
    plan: &stewie_plan::assemble::Plan,
    ctx: &stewie_plan::trips::Context,
    (rho, profile): (f64, &Profile),
    (rp, ipex_mass): (&ReportParams, f64),
) {
    let name = c["name"].as_str().unwrap();
    let got = report_totals(m, plan, ctx, rho, profile, rp);
    let want = &c["report"];
    let ledger = energy_ledger(plan, ctx);
    same(&ledger, &c["ledger"], &[], &format!("{name} ledger"));
    let mut skip = vec![];
    if let Some(factor) = m.dig_energy_factor {
        skip.extend(["dig_energy_bounds_MJ", "plan_uncertainty"]);
        let hi = f(&got["dig_energy_bounds_MJ"][1]);
        // the band's top is the plan's own dig energy
        assert!(
            (hi - f(&ledger["terms_J"]["dig"]) / 1e6).abs() <= 0.05,
            "{name} band holds the plan's dig"
        );
        for k in 0..2 {
            let scaled = f(&want["dig_energy_bounds_MJ"][k]) * factor;
            assert!(
                (f(&got["dig_energy_bounds_MJ"][k]) - scaled).abs() <= 0.1 * factor,
                "{name} band {k} (D-R97)"
            );
        }
        same(
            &got["plan_uncertainty"]["sources"],
            &want["plan_uncertainty"]["sources"],
            &["dig_rate"],
            &format!("{name} uncertainty"),
        );
    }
    if m.vehicle != "ipex" {
        skip.push("relocalization");
        let (g, w) = (&got["relocalization"], &want["relocalization"]);
        same(
            g,
            w,
            &["per_fix_energy_J", "total_energy_J"],
            &format!("{name} relocalization"),
        );
        let ratio = ctx.rover_mass_kg / ipex_mass;
        assert!(ratio > 1.0, "{name} vacuity: a heavier vehicle");
        let scaled = f(&w["per_fix_energy_J"]) * ratio;
        assert!(
            (f(&g["per_fix_energy_J"]) - scaled).abs() <= 0.01,
            "{name} fix energy (D-R97)"
        );
    }
    same(&got, want, &skip, &format!("{name} report"));
}
