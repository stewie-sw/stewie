//! Footprint-inflated legs, haul gains and coverage spirals against the Python oracle `route_extras` on the
//! REAL `route_cases` window. Off-DEM haul sites are the one intended difference: Python reads 0 m, Rust
//! reports `None` (an unknown gain is not flat).

use serde_json::Value;
use stewie_traverse::costmap::{CostmapOptions, Keepout};
use stewie_traverse::haul::{
    coverage_feasible, coverage_spiral, cumulative_ascent_m, elevation_gain_m,
};
use stewie_traverse::route::{Dem, route_leg_inflated};

fn f(v: &Value) -> f64 {
    v.as_f64().unwrap()
}

fn pt(v: &Value) -> (f64, f64) {
    (f(&v[0]), f(&v[1]))
}

#[track_caller]
fn close(got: f64, want: f64, what: &str) {
    assert!(
        (got - want).abs() <= 1e-9 * want.abs().max(1.0),
        "{what}: {got} vs {want}"
    );
}

#[test]
#[allow(clippy::cast_possible_truncation)]
fn extras_match_the_oracle() {
    let cases = stewie_oracle::load("route_cases").unwrap().payload;
    let fx = stewie_oracle::load("route_extras").unwrap().payload;
    let z: Vec<f64> = cases["z"].as_array().unwrap().iter().map(f).collect();
    let n = cases["width"].as_u64().unwrap() as usize;
    let dem = Dem {
        z: &z,
        width: n,
        height: n,
        cell_m: f(&fx["cell_m"]),
        origin: pt(&fx["origin"]),
    };
    let opts = CostmapOptions {
        max_slope_deg: 25.0,
        slip_alpha: 2.0,
        max_drop_m: None,
        illumination: None,
        map_uncertainty: None,
    };
    let mut lengths = Vec::new();
    for l in fx["inflated"].as_array().unwrap() {
        let keep: Vec<Keepout> = l["keepouts"]
            .as_array()
            .unwrap()
            .iter()
            .map(|k| Keepout::Rect {
                x0: f(&k["x0"]),
                y0: f(&k["y0"]),
                x1: f(&k["x1"]),
                y1: f(&k["y1"]),
            })
            .collect();
        let got = route_leg_inflated(
            dem,
            pt(&l["a"]),
            pt(&l["b"]),
            &opts,
            20.0,
            &keep,
            f(&l["radius_m"]),
        )
        .unwrap();
        let name = l["name"].as_str().unwrap();
        assert_eq!(got.reached, l["reached"].as_bool().unwrap(), "{name}");
        close(got.routed_m, f(&l["routed_m"]), name);
        let want: Vec<(f64, f64)> = l["waypoints"].as_array().unwrap().iter().map(pt).collect();
        assert_eq!(got.waypoints.len(), want.len(), "{name}");
        for (a, b) in got.waypoints.iter().zip(&want) {
            close(a.0, b.0, name);
            close(a.1, b.1, name);
        }
        lengths.push((name.to_owned(), got.reached, got.routed_m));
    }
    assert!(
        lengths[1].2 > lengths[0].2 && !lengths[2].1 && lengths[4].2 > lengths[1].2,
        "inflation and keep-out both bite: {lengths:?}"
    );
    for g in fx["gains"].as_array().unwrap() {
        let got = elevation_gain_m(&dem, pt(&g["a"]), pt(&g["b"]));
        let (b, n_cells) = (
            pt(&g["b"]),
            f64::from(u32::try_from(n).unwrap()) * dem.cell_m,
        );
        if b.0 + dem.origin.0 > n_cells {
            assert!(got.is_none(), "off-DEM is unknown, not the Python's 0 m");
        } else {
            close(got.unwrap(), f(&g["gain"]), "gain");
        }
    }
    for a in fx["ascents"].as_array().unwrap() {
        let w: Vec<(f64, f64)> = a["waypoints"].as_array().unwrap().iter().map(pt).collect();
        close(
            cumulative_ascent_m(&dem, &w).unwrap(),
            f(&a["ascent"]),
            "ascent",
        );
    }
}

#[test]
#[allow(clippy::cast_possible_truncation)]
fn coverage_spirals_and_their_feasibility_match_the_oracle() {
    let cases = stewie_oracle::load("route_cases").unwrap().payload;
    let fx = stewie_oracle::load("route_extras").unwrap().payload;
    let z: Vec<f64> = cases["z"].as_array().unwrap().iter().map(f).collect();
    let n = cases["width"].as_u64().unwrap() as usize;
    let dem = Dem {
        z: &z,
        width: n,
        height: n,
        cell_m: f(&fx["cell_m"]),
        origin: pt(&fx["origin"]),
    };
    for s in fx["spirals"].as_array().unwrap() {
        let b = s["bbox"].as_array().unwrap();
        let route = coverage_spiral(
            (f(&b[0]), f(&b[1]), f(&b[2]), f(&b[3])),
            f(&s["swath_m"]),
            s["spacing_m"].as_f64(),
            s["close_loops"].as_bool().unwrap(),
        )
        .unwrap();
        let want: Vec<(f64, f64)> = s["route"].as_array().unwrap().iter().map(pt).collect();
        assert_eq!(route.len(), want.len());
        for (a, b) in route.iter().zip(&want) {
            close(a.0, b.0, "spiral");
            close(a.1, b.1, "spiral");
        }
        let (frac, flags) = coverage_feasible(&dem, &route, 25.0, 2.0).unwrap();
        close(frac, f(&s["feasible_frac"]), "feasible fraction");
        let wf: Vec<bool> = s["flags"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_bool().unwrap())
            .collect();
        assert_eq!(flags, wf);
    }
    assert!(coverage_spiral((0.0, 0.0, 0.0, 5.0), 5.0, None, true).is_err());
    assert!(coverage_spiral((0.0, 0.0, 5.0, 5.0), 0.0, None, true).is_err());
}
