//! Traverse planning against the Python oracle `route_cases`: legs on a REAL Haworth window (5 m) under
//! slope caps, every keep-out shape (each placed on the plain route so it must move it), a keep-out wall
//! that forces the search window to widen, an off-DEM endpoint, and SYNTHETIC illumination and
//! map-uncertainty layers (integer-modulo formulas, labelled in the fixture) regenerated here exactly.

use serde_json::Value;
use stewie_traverse::costmap::{CostmapOptions, Illumination, Keepout, slope_costmap};
use stewie_traverse::route::{Dem, route_leg};

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

/// The fixture's SYNTHETIC layers: the same integer-modulo formulas as `oracle/build_fixtures.py::route_layers`.
#[allow(clippy::cast_precision_loss)]
fn layer(name: &str, w: usize, h: usize) -> Vec<f64> {
    (0..w * h)
        .map(|i| {
            let (y, x) = (i / w, i % w);
            match name {
                "illum_total" => ((x + 2 * y) % 17) as f64 / 17.0,
                "shadow_hazard" => (x % 7) as f64 / 7.0,
                "saturation" => (y % 5) as f64 / 5.0,
                "map_uncertainty" => ((x * y) % 11) as f64 / 11.0,
                "visibility" => ((x + y) % 3) as f64 / 3.0,
                _ => ((3 * x + 5 * y) % 13) as f64 / 13.0,
            }
        })
        .collect()
}

fn terms(w: usize, h: usize, weights: &Value) -> Illumination {
    let wt = |k: &str| weights.get(k).and_then(Value::as_f64).unwrap_or(1.0);
    Illumination::Terms {
        shadow_hazard: layer("shadow_hazard", w, h),
        saturation: layer("saturation", w, h),
        map_uncertainty: layer("map_uncertainty", w, h),
        visibility: layer("visibility", w, h),
        weights: [
            wt("shadow"),
            wt("saturation"),
            wt("map_uncertainty"),
            wt("visibility"),
        ],
    }
}

fn keepout(k: &Value) -> Keepout {
    if let Some(p) = k.get("points") {
        Keepout::Polygon(
            p.as_array()
                .unwrap()
                .iter()
                .map(|q| (f(&q[0]), f(&q[1])))
                .collect(),
        )
    } else if k.get("x0").is_some() {
        Keepout::Rect {
            x0: f(&k["x0"]),
            y0: f(&k["y0"]),
            x1: f(&k["x1"]),
            y1: f(&k["y1"]),
        }
    } else {
        Keepout::Circle {
            x: f(&k["x"]),
            y: f(&k["y"]),
            r: f(&k["r"]),
        }
    }
}

#[test]
#[allow(clippy::cast_possible_truncation)]
fn every_leg_matches_the_oracle() {
    let fx = stewie_oracle::load("route_cases").unwrap().payload;
    let (w, h) = (
        fx["width"].as_u64().unwrap() as usize,
        fx["height"].as_u64().unwrap() as usize,
    );
    let z: Vec<f64> = fx["z"].as_array().unwrap().iter().map(f).collect();
    let dem = Dem {
        z: &z,
        width: w,
        height: h,
        cell_m: f(&fx["cell_m"]),
        origin: (f(&fx["origin"][0]), f(&fx["origin"][1])),
    };
    let (total, all_terms, map_unc) = (
        Illumination::Total(layer("illum_total", w, h)),
        terms(w, h, &fx["weights"]),
        layer("map_unc", w, h),
    );
    let (mut reached, mut moved_by_keepout) = (0, 0);
    let plain = fx["legs"][0]["routed_m"].as_f64().unwrap();
    for l in fx["legs"].as_array().unwrap() {
        let name = l["name"].as_str().unwrap();
        let illum = if l["illum_terms"].as_bool().unwrap() {
            Some((&all_terms, f(&l["illum_weight"])))
        } else if l["illum"].as_bool().unwrap() {
            Some((&total, f(&l["illum_weight"])))
        } else {
            None
        };
        let opts = CostmapOptions {
            max_slope_deg: f(&l["max_slope_deg"]),
            slip_alpha: 2.0,
            max_drop_m: None,
            illumination: illum,
            map_uncertainty: l["map_unc"]
                .as_bool()
                .unwrap()
                .then_some((map_unc.as_slice(), f(&l["map_unc_weight"]))),
        };
        let keepouts: Vec<Keepout> = l["keepouts"]
            .as_array()
            .unwrap()
            .iter()
            .map(keepout)
            .collect();
        let got = route_leg(
            dem,
            (f(&l["a"][0]), f(&l["a"][1])),
            (f(&l["b"][0]), f(&l["b"][1])),
            &opts,
            f(&l["margin_m"]),
            &keepouts,
        )
        .unwrap();
        assert_eq!(got.reached, l["reached"].as_bool().unwrap(), "{name}");
        close(got.routed_m, f(&l["routed_m"]), name);
        close(got.grid_straight_m, f(&l["grid_straight_m"]), name);
        let wp = l["waypoints"].as_array().unwrap();
        assert_eq!(got.waypoints.len(), wp.len(), "{name} path length");
        for (g, want) in got.waypoints.iter().zip(wp) {
            close(g.0, f(&want[0]), name);
            close(g.1, f(&want[1]), name);
        }
        for (term, vals) in &got.breakdown {
            let want = l["breakdown"][*term]
                .as_array()
                .unwrap_or_else(|| panic!("{name}: python lacks term {term}"));
            for (a, b) in vals.iter().zip(want) {
                close(*a, f(b), term);
            }
        }
        assert_eq!(
            got.breakdown.len(),
            l["breakdown"].as_object().unwrap().len(),
            "{name} terms"
        );
        reached += usize::from(got.reached);
        moved_by_keepout +=
            usize::from(!keepouts.is_empty() && got.reached && (got.routed_m - plain).abs() > 1e-6);
    }
    assert!(reached >= 8, "routes exercised: {reached}");
    assert_eq!(
        moved_by_keepout, 4,
        "every keep-out leg detours the plain route"
    );
}

#[test]
#[allow(clippy::cast_possible_truncation)]
fn the_full_costmap_and_its_terms_match() {
    let fx = stewie_oracle::load("route_cases").unwrap().payload;
    let (w, k) = (
        fx["width"].as_u64().unwrap() as usize,
        fx["costmap"]["size"].as_u64().unwrap() as usize,
    );
    let z: Vec<f64> = fx["z"].as_array().unwrap().iter().map(f).collect();
    let crop = |full: &[f64]| -> Vec<f64> {
        (0..k)
            .flat_map(|r| full[r * w..r * w + k].iter().copied())
            .collect()
    };
    let full_terms = terms(w, w, &fx["weights"]);
    let Illumination::Terms {
        shadow_hazard,
        saturation,
        map_uncertainty,
        visibility,
        weights,
    } = full_terms
    else {
        unreachable!()
    };
    let il = Illumination::Terms {
        shadow_hazard: crop(&shadow_hazard),
        saturation: crop(&saturation),
        map_uncertainty: crop(&map_uncertainty),
        visibility: crop(&visibility),
        weights,
    };
    let mu = crop(&layer("map_unc", w, w));
    let cm = slope_costmap(
        &crop(&z),
        k,
        k,
        f(&fx["cell_m"]),
        &CostmapOptions {
            max_slope_deg: 25.0,
            slip_alpha: 2.0,
            max_drop_m: Some(f(&fx["max_drop_m"])),
            illumination: Some((&il, 2.0)),
            map_uncertainty: Some((&mu, 4.0)),
        },
    )
    .unwrap();
    let c = &fx["costmap"];
    let passable: Vec<bool> = c["passable"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_bool().unwrap())
        .collect();
    assert_eq!(cm.passable, passable);
    assert!(passable.contains(&false), "hazards present");
    for (a, b) in cm.cost.iter().zip(c["cost"].as_array().unwrap()) {
        close(*a, f(b), "cost");
    }
    for (name, vals) in &cm.terms {
        for (a, b) in vals.iter().zip(c["terms"][*name].as_array().unwrap()) {
            close(*a, f(b), name);
        }
    }
}
