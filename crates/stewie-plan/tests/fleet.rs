//! Fleet allocation and deconfliction against the Python oracle `fleet_cases`. Fleets planned over the REAL
//! Haworth route window: each rover's allocation and visit order, its timeline and trip windows, then every
//! resolver's waits, the conflict counts and the health rollups. The resource, observation and multi-site
//! placements, and the per-vehicle timeline cases, are SYNTHETIC (labelled in the oracle).

use serde_json::Value;
use stewie_contracts::fleet::Fleet;
use stewie_physics::soil::SoilParams;
use stewie_plan::balance::{Profile, Routes};
use stewie_plan::fleet::{
    VehiclePlan, allocate_trips, charger_conflicts, haul_path_conflicts,
    resolve_cross_vehicle_precedence, resolve_joint_resources, resolve_observation_vantages,
    resolve_spacetime_crowding, rover_health, seg_seg_min_dist, temporal_conflicts,
    vehicle_conflicts,
};
use stewie_plan::mission::{Observation, Registries, SharedResource, mission_from_value};
use stewie_plan::optimize::{Sequencing, optimize_sequence, parse_objective};
use stewie_plan::sim::{Core, Span, SpanKind, TripTimes, simulate};
use stewie_plan::trips::{
    BuildInputs, PlannerParams, SlipModel, Trip, TripKind, build_trips, context, trip_precedence,
};
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

#[track_caller]
fn close_all(got: &[f64], want: &Value, what: &str) {
    let want: Vec<f64> = want.as_array().unwrap().iter().map(f).collect();
    assert_eq!(got.len(), want.len(), "{what} length");
    for (k, (a, b)) in got.iter().zip(&want).enumerate() {
        close(*a, *b, &format!("{what}[{k}]"));
    }
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

fn kind(s: &str) -> SpanKind {
    match s {
        "drive" => SpanKind::Drive,
        "wait" => SpanKind::Wait,
        "charge" => SpanKind::Charge,
        "dig" => SpanKind::Dig,
        "offload" => SpanKind::Offload,
        other => panic!("span kind {other}"),
    }
}

fn pt(v: &Value) -> (f64, f64) {
    (f(&v[0]), f(&v[1]))
}

fn spans(v: &Value) -> Vec<Span> {
    v.as_array()
        .unwrap()
        .iter()
        .map(|s| Span {
            t0: f(&s["t0"]),
            t1: f(&s["t1"]),
            kind: kind(s["kind"].as_str().unwrap()),
            batt0: f(&s["batt0"]),
            batt1: f(&s["batt1"]),
            mass_kg: 0.0,
            speed: 0.0,
            from: pt(&s["from"]),
            to: pt(&s["to"]),
        })
        .collect()
}

#[track_caller]
fn same_timeline(got: &[Span], want: &Value, what: &str) {
    let want = spans(want);
    assert_eq!(got.len(), want.len(), "{what} spans");
    for (k, (a, b)) in got.iter().zip(&want).enumerate() {
        assert_eq!(a.kind, b.kind, "{what} span {k} kind");
        for (x, y, l) in [
            (a.t0, b.t0, "t0"),
            (a.t1, b.t1, "t1"),
            (a.batt0, b.batt0, "batt0"),
            (a.batt1, b.batt1, "batt1"),
            (a.from.0, b.from.0, "x0"),
            (a.from.1, b.from.1, "y0"),
            (a.to.0, b.to.0, "x1"),
            (a.to.1, b.to.1, "y1"),
        ] {
            close(x, y, &format!("{what} span {k} {l}"));
        }
    }
}

#[track_caller]
fn same_health(got: &stewie_plan::fleet::Health, want: &Value, what: &str) {
    assert_eq!(
        got.feasible,
        want["feasible"].as_bool().unwrap(),
        "{what} feasible"
    );
    close(
        got.min_batt_frac,
        f(&want["min_batt_frac"]),
        &format!("{what} min_batt_frac"),
    );
    assert_eq!(
        got.charges,
        want["charges"].as_u64().unwrap(),
        "{what} charges"
    );
    assert_eq!(
        got.health,
        want["health"].as_str().unwrap(),
        "{what} health"
    );
    let reasons: Vec<&str> = want["infeasible_reasons"]
        .as_array()
        .unwrap()
        .iter()
        .map(|r| r.as_str().unwrap())
        .collect();
    assert_eq!(got.infeasible_reasons, reasons, "{what} reasons");
}

fn pairs(v: &Value) -> Vec<(usize, usize)> {
    v.as_array()
        .unwrap()
        .iter()
        .map(|p| (u(&p[0]), u(&p[1])))
        .collect()
}

#[test]
#[allow(clippy::too_many_lines)] // setup shared by every case
fn real_fleets_deconflict_as_the_python_does() {
    let fx = stewie_oracle::load("fleet_cases").unwrap().payload;
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
    let soil_of = |key: &str| {
        let mc = tc["missions"]
            .as_array()
            .unwrap()
            .iter()
            .find(|m| m["name"] == key)
            .unwrap();
        soil(&mc["soil"])
    };
    let mut waits_seen = [false; 4];
    for c in fx["cases"].as_array().unwrap() {
        let name = c["name"].as_str().unwrap();
        let m = mission_from_value(&c["payload"], &reg).unwrap();
        let sp = soil_of(if name.starts_with("heavy") {
            "heavy_rassor"
        } else {
            "haul_two_pairs"
        });
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
        let prec = trip_precedence(&trips, &m);
        assert_eq!(prec, pairs(&c["precedence"]), "{name} precedence");
        let cx = context(&m, &fleet, &params).unwrap();
        let mut routes = Routes::new(dem, 25.0, &m.keepouts);
        let weights = parse_objective(c["objective"].as_str().unwrap()).unwrap();
        let alloc = allocate_trips(&trips, u(&c["vehicles"]));
        let want_alloc: Vec<Vec<usize>> = c["alloc"]
            .as_array()
            .unwrap()
            .iter()
            .map(|a| a.as_array().unwrap().iter().map(u).collect())
            .collect();
        assert_eq!(alloc, want_alloc, "{name} allocation");
        let mut per = Vec::new();
        for (v, idxs) in alloc.iter().enumerate() {
            let vtrips: Vec<Trip> = idxs.iter().map(|&i| trips[i].clone()).collect();
            let local: Vec<(usize, usize)> = prec
                .iter()
                .filter_map(|&(i, j)| {
                    Some((
                        idxs.iter().position(|&g| g == i)?,
                        idxs.iter().position(|&g| g == j)?,
                    ))
                })
                .collect();
            let order = {
                let mut seq = Sequencing {
                    mission: &m,
                    trips: &vtrips,
                    ctx: &cx,
                    routes: &mut routes,
                    precedence: &local,
                };
                optimize_sequence(&mut seq, c["algorithm"].as_str().unwrap(), &weights).unwrap()
            };
            let global: Vec<usize> = order.iter().map(|&k| idxs[k]).collect();
            assert_eq!(
                global,
                c["orders"][v]
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(u)
                    .collect::<Vec<_>>(),
                "{name} rover {v} order"
            );
            let (tl, times, core) = simulate(&m, &trips, &global, &cx, &mut routes).unwrap();
            same_timeline(&tl, &c["tl"][v], &format!("{name} rover {v}"));
            for (k, w) in times.iter().enumerate() {
                close(
                    w.t_start,
                    f(&c["times"][v][k][0]),
                    &format!("{name} rover {v} trip {k} start"),
                );
                close(
                    w.t_end,
                    f(&c["times"][v][k][1]),
                    &format!("{name} rover {v} trip {k} end"),
                );
            }
            close(
                core.time_s,
                f(&c["core_time_s"][v]),
                &format!("{name} rover {v} time"),
            );
            per.push(VehiclePlan {
                vehicle: v,
                trips: global,
                tl,
                times,
                core,
            });
        }
        let j = resolve_joint_resources(&per, &trips, m.charger_capacity, &m.shared_resources, 0.5);
        close_all(
            &j.delay,
            &c["joint"]["delay"],
            &format!("{name} joint delay"),
        );
        close_all(
            &j.charger_delay,
            &c["joint"]["charger_delay"],
            &format!("{name} charger delay"),
        );
        close_all(
            &j.resource_delay,
            &c["joint"]["resource_delay"],
            &format!("{name} resource delay"),
        );
        let want_rw = c["joint"]["resource_waits"].as_array().unwrap();
        assert_eq!(
            j.resource_waits.len(),
            want_rw.len(),
            "{name} resource waits"
        );
        for ((id, w), want) in j.resource_waits.iter().zip(want_rw) {
            assert_eq!(id, want[0].as_str().unwrap(), "{name} resource id");
            close(*w, f(&want[1]), &format!("{name} resource {id} wait"));
        }
        let crowd = resolve_spacetime_crowding(&per, 10.0, 64);
        close_all(&crowd, &c["crowd"], &format!("{name} crowding"));
        let pd = resolve_cross_vehicle_precedence(&per, &prec);
        close_all(
            &pd,
            &c["precedence_delay"],
            &format!("{name} precedence delay"),
        );
        let ov = resolve_observation_vantages(per.len(), &m.observations, 10.0).unwrap();
        close_all(
            &ov.delay,
            &c["observation"]["delay"],
            &format!("{name} observation delay"),
        );
        let want_v: Vec<(String, Vec<usize>)> = c["observation"]["vantages"]
            .as_array()
            .unwrap()
            .iter()
            .map(|e| {
                (
                    e[0].as_str().unwrap().to_owned(),
                    e[1].as_array().unwrap().iter().map(u).collect(),
                )
            })
            .collect();
        assert_eq!(ov.vantages, want_v, "{name} vantages");
        assert_eq!(
            vehicle_conflicts(&per, &trips),
            u(&c["vehicle_conflicts"]),
            "{name} site conflicts"
        );
        assert_eq!(
            charger_conflicts(&per),
            u(&c["charger_conflicts"]),
            "{name} charger conflicts"
        );
        assert_eq!(
            temporal_conflicts(&per, 10.0),
            u(&c["temporal_conflicts"]),
            "{name} temporal"
        );
        assert_eq!(
            haul_path_conflicts(&per, 10.0),
            u(&c["haul_path_conflicts"]),
            "{name} haul paths"
        );
        for (v, pv) in per.iter().enumerate() {
            same_health(
                &rover_health(pv),
                &c["health"][v],
                &format!("{name} rover {v}"),
            );
        }
        let pos = |xs: &[f64]| xs.iter().any(|&x| x > 0.0);
        waits_seen[0] |= pos(&j.charger_delay);
        waits_seen[1] |= pos(&j.resource_delay);
        waits_seen[2] |= pos(&crowd);
        waits_seen[3] |= pos(&ov.delay);
    }
    assert_eq!(
        waits_seen, [true; 4],
        "vacuity: charger, resource, crowding and vantage waits all occur"
    );
}

#[test]
#[allow(clippy::too_many_lines)] // one synthetic fleet, every branch it covers
fn synthetic_timelines_cover_the_remaining_branches() {
    let fx = stewie_oracle::load("fleet_cases").unwrap().payload;
    let syn = &fx["synthetic"];
    let sites: Vec<(f64, f64)> = syn["sites"].as_array().unwrap().iter().map(pt).collect();
    // SYNTHETIC trips (labelled): only the site matters to the resolvers
    let trips: Vec<Trip> = sites
        .iter()
        .map(|&s| Trip {
            kind: TripKind::Dig,
            site: s,
            dest: s,
            label: String::new(),
            mass_kg: 0.0,
            dig_e: 1.0,
            dig_t: 0.0,
            haul_m: 0.0,
            haul_e: 0.0,
            drive_e: 0.0,
            slip_e: 0.0,
            lift_e: 0.0,
            offload_e: 0.0,
            offload_t: 0.0,
            actions: std::collections::BTreeSet::new(),
            shape: None,
        })
        .collect();
    let per: Vec<VehiclePlan> = (0..sites.len())
        .map(|v| {
            let core = &syn["core"][v];
            VehiclePlan {
                vehicle: v,
                trips: vec![v],
                tl: spans(&syn["tl"][v]),
                times: vec![TripTimes {
                    trip: v,
                    t_start: f(&syn["times"][v][0][0]),
                    t_end: f(&syn["times"][v][0][1]),
                }],
                core: Core {
                    time_s: 0.0,
                    mass_kg: 0.0,
                    energy_j: 0.0,
                    charges: core["charges"].as_u64().unwrap(),
                    distance_m: 0.0,
                    avg_power_w: 0.0,
                    feasible: core["feasible"].as_bool().unwrap(),
                    infeasible_reasons: core["infeasible_reasons"]
                        .as_array()
                        .unwrap()
                        .iter()
                        .map(|r| r.as_str().unwrap().to_owned())
                        .collect(),
                },
            }
        })
        .collect();
    for case in syn["joint"].as_array().unwrap() {
        let cap = case["charger_capacity"].as_u64().unwrap();
        let res: Vec<SharedResource> = case["resources"]
            .as_array()
            .unwrap()
            .iter()
            .map(|r| SharedResource {
                id: r["id"].as_str().unwrap().to_owned(),
                kind: r["kind"].as_str().unwrap().to_owned(),
                capacity: r["capacity"].as_u64().unwrap(),
                sites: r["sites"].as_array().unwrap().iter().map(pt).collect(),
            })
            .collect();
        let j = resolve_joint_resources(&per, &trips, cap, &res, 0.5);
        close_all(
            &j.delay,
            &case["joint"]["delay"],
            &format!("cap {cap} delay"),
        );
        close_all(
            &j.charger_delay,
            &case["joint"]["charger_delay"],
            &format!("cap {cap} charger"),
        );
        close_all(
            &j.resource_delay,
            &case["joint"]["resource_delay"],
            &format!("cap {cap} resource"),
        );
    }
    let tie = &syn["tie"];
    let tie_per: Vec<VehiclePlan> = (0..2)
        .map(|v| VehiclePlan {
            vehicle: v,
            trips: vec![v],
            tl: spans(&tie["tl"][v]),
            times: vec![TripTimes {
                trip: v,
                t_start: f(&tie["times"][v][0][0]),
                t_end: f(&tie["times"][v][0][1]),
            }],
            core: per[v].core.clone(),
        })
        .collect();
    let tie_res: Vec<SharedResource> = tie["resources"]
        .as_array()
        .unwrap()
        .iter()
        .map(|r| SharedResource {
            id: r["id"].as_str().unwrap().to_owned(),
            kind: r["kind"].as_str().unwrap().to_owned(),
            capacity: r["capacity"].as_u64().unwrap(),
            sites: r["sites"].as_array().unwrap().iter().map(pt).collect(),
        })
        .collect();
    let j = resolve_joint_resources(&tie_per, &trips, 1, &tie_res, 0.5);
    close_all(&j.delay, &tie["delay"], "tie delay");
    close_all(&j.charger_delay, &tie["charger_delay"], "tie charger");
    close_all(&j.resource_delay, &tie["resource_delay"], "tie resource");
    let chain = pairs(&syn["chain"]);
    close_all(
        &resolve_cross_vehicle_precedence(&per, &chain),
        &syn["chain_delay"],
        "chain delay",
    );
    assert!(
        syn["chain_delay"][2].as_f64().unwrap() > 0.0,
        "vacuity: the chain propagates"
    );
    close_all(
        &resolve_spacetime_crowding(&per, 10.0, 64),
        &syn["crowd"],
        "synthetic crowding",
    );
    for (v, pv) in per.iter().enumerate() {
        same_health(
            &rover_health(pv),
            &syn["health"][v],
            &format!("synthetic rover {v}"),
        );
    }
    for r in fx["refusals"].as_array().unwrap() {
        let obs: Vec<Observation> = r["observations"]
            .as_array()
            .unwrap()
            .iter()
            .map(|o| Observation {
                vehicle: o["vehicle"].as_u64().unwrap(),
                x: f(&o["x"]),
                y: f(&o["y"]),
                t_start: f(&o["t_start"]),
                t_end: f(&o["t_end"]),
                kind: o["kind"].as_str().unwrap().to_owned(),
            })
            .collect();
        let err = resolve_observation_vantages(3, &obs, 10.0).unwrap_err();
        assert_eq!(err, r["error"].as_str().unwrap());
    }
    for s in fx["segments"].as_array().unwrap() {
        close(
            seg_seg_min_dist(pt(&s["a0"]), pt(&s["a1"]), pt(&s["b0"]), pt(&s["b1"])),
            f(&s["d"]),
            "segment distance",
        );
    }
}
