//! Cut-fill balance against the Python oracle `balance_cases`. The transport solver on the P-03 docstring
//! example and SYNTHETIC matrices (labelled): the flows where the optimum is unique, and the cost and throughput
//! everywhere. `balance` on missions routed over the REAL Haworth route window (the heights `route_cases`
//! carries): the routed cost matrix, every cut's and fill's total, the routed, imported and spoil masses and the
//! total haul cost. Where two routings cost the same (the `surplus` mission has a tie) the flows themselves may
//! differ from the Python's; nothing those flows determine does.

use serde_json::Value;
use stewie_contracts::fleet::Fleet;
use stewie_plan::balance::{Flow, Profile, Routes, balance, mincost_transport};
use stewie_plan::mission::{Registries, mission_from_value};
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

fn matrix(v: &Value) -> Vec<Vec<f64>> {
    v.as_array()
        .unwrap()
        .iter()
        .map(|r| {
            r.as_array()
                .unwrap()
                .iter()
                .map(|c| c.as_f64().unwrap_or(f64::INFINITY))
                .collect()
        })
        .collect()
}

fn haul_cost(flow: &[Vec<f64>], cost: &[Vec<f64>]) -> f64 {
    flow.iter()
        .zip(cost)
        .flat_map(|(fr, cr)| {
            fr.iter()
                .zip(cr)
                .filter(|(m, _)| **m > 0.0)
                .map(|(m, c)| m * c)
        })
        .sum()
}

#[test]
fn the_transport_solver_finds_the_pythons_optimum() {
    let fx = stewie_oracle::load("balance_cases").unwrap().payload;
    for t in fx["transport"].as_array().unwrap() {
        let name = t["name"].as_str().unwrap();
        let (sup, dem, cost) = (
            t["supplies"]
                .as_array()
                .unwrap()
                .iter()
                .map(f)
                .collect::<Vec<_>>(),
            t["demands"]
                .as_array()
                .unwrap()
                .iter()
                .map(f)
                .collect::<Vec<_>>(),
            matrix(&t["cost"]),
        );
        let (flow, unmet, left) = mincost_transport(&sup, &dem, &cost);
        let want = matrix(&t["flow"]);
        close(
            haul_cost(&flow, &cost),
            haul_cost(&want, &cost),
            &format!("{name} cost"),
        );
        let moved = |fl: &[Vec<f64>]| fl.iter().flatten().sum::<f64>();
        close(moved(&flow), moved(&want), &format!("{name} throughput"));
        close(
            unmet.iter().sum(),
            t["unmet"].as_array().unwrap().iter().map(f).sum(),
            &format!("{name} unmet"),
        );
        close(
            left.iter().sum(),
            t["leftover"].as_array().unwrap().iter().map(f).sum(),
            &format!("{name} leftover"),
        );
        if name != "cost_tie" {
            for (a, b) in flow.iter().flatten().zip(want.iter().flatten()) {
                close(*a, *b, &format!("{name} flow (unique optimum)"));
            }
        }
    }
}

fn registries() -> Registries {
    let bodies: stewie_contracts::body::BodyRegistry =
        serde_json::from_str(include_str!("../../stewie-contracts/fixtures/bodies.json")).unwrap();
    let fleet: Fleet =
        serde_json::from_str(include_str!("../../stewie-contracts/fixtures/fleet.json")).unwrap();
    Registries::new(&bodies, &fleet)
}

fn profile() -> (f64, Profile) {
    let bodies: Value =
        serde_json::from_str(include_str!("../../stewie-contracts/fixtures/bodies.json")).unwrap();
    let soil: Value = serde_json::from_str(include_str!(
        "../../stewie-contracts/fixtures/soil_baseline.json"
    ))
    .unwrap();
    let moon = f(&bodies["moon"]["bulk_density"]);
    (
        moon,
        Profile {
            rho_surface: moon,
            rho_deep: f(&soil["rho_deep"]["value"]),
            z_t_m: f(&soil["z_t_m"]["value"]),
        },
    )
}

/// Per-order totals and the routed, imported and spoil masses of a set of flows.
fn totals(flows: &[Flow], n_orders: usize) -> (Vec<f64>, [f64; 3]) {
    let mut per = vec![0.0; n_orders];
    let mut kinds = [0.0; 3];
    for fl in flows {
        for i in [fl.cut, fl.fill].into_iter().flatten() {
            per[i] += fl.mass_kg;
        }
        kinds[match (fl.cut, fl.fill) {
            (Some(_), Some(_)) => 0,
            (None, _) => 1,
            (_, None) => 2,
        }] += fl.mass_kg;
    }
    (per, kinds)
}

#[test]
fn routed_missions_balance_as_the_python_does() {
    let fx = stewie_oracle::load("balance_cases").unwrap().payload;
    let route = stewie_oracle::load("route_cases").unwrap().payload;
    let heights: Vec<f64> = route["z"].as_array().unwrap().iter().map(f).collect();
    let side = usize::try_from(fx["window"][2].as_u64().unwrap()).unwrap();
    let dem = Dem {
        z: &heights,
        width: side,
        height: side,
        cell_m: f(&fx["cell_m"]),
        origin: (f(&fx["origin"][0]), f(&fx["origin"][1])),
    };
    let (rho, prof) = profile();
    let reg = registries();
    let mut seen_import = false;
    for c in fx["missions"].as_array().unwrap() {
        let name = c["name"].as_str().unwrap();
        let m = mission_from_value(&c["payload"], &reg).unwrap();
        let mut routes = Routes::new(dem, 25.0, &m.keepouts);
        let (flows, surplus) = balance(&m, rho, &prof, &mut routes).unwrap();
        // the routed cost matrix itself
        let cuts: Vec<usize> = (0..m.orders.len())
            .filter(|&i| m.orders[i].kind == stewie_plan::mission::OrderKind::Cut)
            .collect();
        let fills: Vec<usize> = (0..m.orders.len())
            .filter(|&i| m.orders[i].kind == stewie_plan::mission::OrderKind::Fill)
            .collect();
        let want_cost = matrix(&c["cost"]);
        for (a, &i) in cuts.iter().enumerate() {
            for (b, &j) in fills.iter().enumerate() {
                let at = |k: usize| (m.orders[k].x, m.orders[k].y);
                let got = routes.distance(at(i), at(j)).unwrap();
                let want = want_cost[a][b];
                // an unreachable pair is infinite on both sides
                let same = (got.is_infinite() && want.is_infinite())
                    || (got - want).abs() <= 1e-9 * want.abs().max(1.0);
                assert!(same, "{name} route {a}->{b}: {got} vs {want}");
            }
        }
        let want: Vec<Flow> = c["flows"]
            .as_array()
            .unwrap()
            .iter()
            .map(|w| Flow {
                cut: w["cut"].as_u64().map(|v| usize::try_from(v).unwrap()),
                fill: w["fill"].as_u64().map(|v| usize::try_from(v).unwrap()),
                mass_kg: f(&w["mass_kg"]),
                dist_m: f(&w["dist_m"]),
            })
            .collect();
        let (got_per, got_kind) = totals(&flows, m.orders.len());
        let (want_per, want_kind) = totals(&want, m.orders.len());
        for (k, (a, b)) in got_per.iter().zip(&want_per).enumerate() {
            close(*a, *b, &format!("{name} order {k} total"));
        }
        for (k, label) in ["routed", "imported", "spoil"].iter().enumerate() {
            close(got_kind[k], want_kind[k], &format!("{name} {label}"));
        }
        close(surplus, f(&c["surplus_kg"]), &format!("{name} surplus"));
        let haul = |fl: &[Flow]| -> f64 {
            fl.iter()
                .filter_map(|x| Some((x.cut?, x.fill?, x.mass_kg)))
                .map(|(i, j, mass)| {
                    let (a, b) = (
                        cuts.iter().position(|&k| k == i).unwrap(),
                        fills.iter().position(|&k| k == j).unwrap(),
                    );
                    mass * want_cost[a][b]
                })
                .sum()
        };
        close(haul(&flows), haul(&want), &format!("{name} haul cost"));
        seen_import |= got_kind[1] > 0.0;
    }
    assert!(seen_import, "vacuity: some fill is imported");
}
