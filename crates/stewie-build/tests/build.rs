//! LEAP construction against the Python oracle `build_cases` (every layout and size SYNTHETIC, labelled in the
//! oracle; densities from the soil baseline contract). Template orders, refusals and site-plan reports match the
//! Python, except D-R101: the cut-only templates refuse a non-positive size, and a clearance under the minimum gap
//! is advised.

use serde_json::{Map, Value};
use stewie_build::{Densities, Placed, analyze_siteplan, decompose};

fn f(v: &Value) -> f64 {
    v.as_f64().unwrap()
}

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

fn densities(fx: &Value) -> Densities {
    let (_, base) = stewie_physics::soil::bundled();
    let d = Densities {
        bank: base.rho_deep.value,
        loose: base.rho_spoil.value,
    };
    assert!(
        (d.bank - f(&fx["rho_bank"])).abs() <= 1e-12,
        "the contract's bank density is the Python's"
    );
    assert!(
        (d.loose - f(&fx["rho_loose"])).abs() <= 1e-12,
        "the contract's loose density is the Python's"
    );
    d
}

#[test]
fn templates_decompose_as_the_python_does() {
    let fx = stewie_oracle::load("build_cases").unwrap().payload;
    let d = densities(&fx);
    for t in fx["templates"].as_array().unwrap() {
        let name = t["name"].as_str().unwrap();
        let got = decompose(
            name,
            f(&t["x"]),
            f(&t["y"]),
            t["params"].as_object().unwrap(),
            &d,
        )
        .unwrap();
        same(&Value::Array(got), &t["orders"], name);
    }
    let mut accepted_by_python = 0;
    for r in fx["refusals"].as_array().unwrap() {
        let name = r["name"].as_str().unwrap();
        let err = decompose(name, 0.0, 0.0, r["params"].as_object().unwrap(), &d).unwrap_err();
        if let Some(want) = r["error"].as_str() {
            assert_eq!(err, want, "{name}");
        } else {
            // D-R101: the Python's cut-only template accepted it; the Rust refuses
            assert!(err.contains("must be > 0"), "{name}: {err}");
            accepted_by_python += 1;
        }
    }
    assert!(
        accepted_by_python > 0,
        "vacuity: a size the Python wrongly accepts"
    );
    let err = decompose(
        "trench",
        0.0,
        0.0,
        &Map::from_iter([("depht_m".into(), 1.0.into())]),
        &d,
    )
    .unwrap_err();
    assert!(
        err.contains("unexpected keyword argument 'depht_m'"),
        "{err}"
    );
}

#[test]
fn site_plans_advise_as_the_python_does() {
    let fx = stewie_oracle::load("build_cases").unwrap().payload;
    let d = densities(&fx);
    let mut sub_minimum = false;
    for p in fx["plans"].as_array().unwrap() {
        let name = p["name"].as_str().unwrap();
        let placed: Vec<Placed> = p["placed"]
            .as_array()
            .unwrap()
            .iter()
            .map(|s| Placed {
                name: s["name"].as_str().unwrap().to_owned(),
                x: f(&s["x"]),
                y: f(&s["y"]),
                params: s["params"].as_object().unwrap().clone(),
            })
            .collect();
        let min_gap = f(&p["min_gap_m"]);
        let got = analyze_siteplan(&placed, min_gap, &d).unwrap();
        let w = &p["report"];
        for (g, key) in [
            (got.total_cut_mass_kg, "total_cut_mass_kg"),
            (got.total_fill_mass_kg, "total_fill_mass_kg"),
            (got.net_mass_kg, "net_mass_kg"),
            (got.total_haul_work_kg_m, "total_haul_work_kg_m"),
        ] {
            same(&g.into(), &w[key], &format!("{name} {key}"));
        }
        let pairs = w["pairings"].as_array().unwrap();
        assert_eq!(got.pairings.len(), pairs.len(), "{name} pairings");
        for (g, e) in got.pairings.iter().zip(pairs) {
            assert_eq!(
                g.source as u64,
                e["source_order_idx"].as_u64().unwrap(),
                "{name} source"
            );
            assert_eq!(
                g.sink as u64,
                e["sink_order_idx"].as_u64().unwrap(),
                "{name} sink"
            );
            same(
                &g.mass_kg.into(),
                &e["mass_kg"],
                &format!("{name} flow mass"),
            );
            same(
                &g.haul_dist_m.into(),
                &e["haul_dist_m"],
                &format!("{name} haul"),
            );
        }
        let clear = w["clearances"].as_array().unwrap();
        assert_eq!(got.clearances.len(), clear.len(), "{name} clearances");
        for (g, e) in got.clearances.iter().zip(clear) {
            same(&g.gap_m.into(), &e["gap_m"], &format!("{name} gap"));
            assert_eq!(g.overlap, e["overlap"].as_bool().unwrap(), "{name} overlap");
        }
        let want_order: Vec<usize> = w["build_order"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| usize::try_from(v.as_u64().unwrap()).unwrap())
            .collect();
        assert_eq!(got.build_order, want_order, "{name} build order");
        // the Python's advisories, then (D-R101) one per sub-minimum clearance
        let python: Vec<&str> = w["advisories"]
            .as_array()
            .unwrap()
            .iter()
            .map(|a| a.as_str().unwrap())
            .collect();
        assert_eq!(
            &got.advisories[..python.len()],
            python.as_slice(),
            "{name} advisories"
        );
        let extra = got
            .clearances
            .iter()
            .filter(|c| !c.overlap && c.gap_m < min_gap)
            .count();
        assert_eq!(
            got.advisories.len(),
            python.len() + extra,
            "{name} sub-minimum advisories"
        );
        sub_minimum |= extra > 0;
    }
    assert!(sub_minimum, "vacuity: a sub-minimum clearance is advised");
}
