//! lunar-frames against the oracle: pyproj (`IAU_2015:30135`) lat/lon of every sampled cell centre in the
//! ten real DEM bundles. Property tests use random inputs (synthetic, labelled) for invariants.

use lunar_frames::{LatLon, PolarStereographic, Sphere, body_fixed, enu_basis};
use proptest::prelude::*;

fn moon() -> Sphere {
    let reg: serde_json::Value =
        serde_json::from_str(include_str!("../../stewie-contracts/fixtures/bodies.json")).unwrap();
    Sphere::new(reg["moon"]["ellipsoid_radius_m"].as_f64().unwrap()).unwrap()
}

fn south() -> PolarStereographic {
    PolarStereographic::south(moon())
}

/// Every oracle cell as (projected easting, northing, oracle lat, oracle lon), using the bundle georeference
/// (pixel (0,0) centre at (x0 + cell/2, y1 - cell/2), north-up).
fn oracle_cells() -> Vec<(f64, f64, f64, f64)> {
    let fx = stewie_oracle::load("dem_samples").unwrap();
    let root = stewie_oracle::repo_root();
    let mut out = Vec::new();
    for b in fx.payload["bundles"].as_array().unwrap() {
        let name = b["bundle"].as_str().unwrap();
        let meta: serde_json::Value = serde_json::from_str(
            &std::fs::read_to_string(
                root.join("samples/lunar_dem")
                    .join(name)
                    .join("metadata.json"),
            )
            .unwrap(),
        )
        .unwrap();
        let cell = b["cell_m"].as_f64().unwrap();
        let x0 = meta["world_bounds_m"]["x0"].as_f64().unwrap();
        let y1 = meta["world_bounds_m"]["y1"].as_f64().unwrap();
        for c in b["cells"].as_array().unwrap() {
            let row = c["row"].as_f64().unwrap();
            let col = c["col"].as_f64().unwrap();
            out.push((
                x0 + cell / 2.0 + col * cell,
                y1 - cell / 2.0 - row * cell,
                c["lat_deg"].as_f64().unwrap(),
                c["lon_deg"].as_f64().unwrap(),
            ));
        }
    }
    out
}

fn lon_diff(a: f64, b: f64) -> f64 {
    ((a - b + 540.0) % 360.0 - 180.0).abs()
}

#[test]
fn inverse_matches_pyproj_on_all_real_cells() {
    let p = south();
    let cells = oracle_cells();
    assert_eq!(cells.len(), 160);
    for (e, n, lat, lon) in cells {
        let ll = p.inverse(e, n);
        assert!(
            (ll.lat_deg - lat).abs() < 1e-9,
            "lat {} vs {lat}",
            ll.lat_deg
        );
        assert!(
            lon_diff(ll.lon_deg, lon) < 1e-9,
            "lon {} vs {lon}",
            ll.lon_deg
        );
    }
}

#[test]
fn forward_matches_pyproj_on_all_real_cells_within_a_millimetre() {
    let p = south();
    for (e, n, lat, lon) in oracle_cells() {
        let (fe, fn_) = p
            .forward(LatLon {
                lat_deg: lat,
                lon_deg: lon,
            })
            .unwrap();
        assert!(
            (fe - e).abs() < 1e-3 && (fn_ - n).abs() < 1e-3,
            "({fe},{fn_}) vs ({e},{n})"
        );
    }
}

#[test]
fn the_antipodal_pole_cannot_be_projected() {
    assert!(
        south()
            .forward(LatLon {
                lat_deg: 90.0,
                lon_deg: 0.0
            })
            .is_err()
    );
}

#[test]
fn sphere_rejects_nonpositive_radius() {
    assert!(Sphere::new(0.0).is_err());
    assert!(Sphere::new(f64::NAN).is_err());
}

proptest! {
    #[test]
    fn projection_round_trips_within_a_millimetre(lat in -89.999f64..60.0, lon in -180.0f64..180.0) {
        let p = south();
        let (e, n) = p.forward(LatLon { lat_deg: lat, lon_deg: lon }).unwrap();
        let ll = p.inverse(e, n);
        let (e2, n2) = p.forward(ll).unwrap();
        prop_assert!((e - e2).abs() < 1e-3 && (n - n2).abs() < 1e-3);
    }

    #[test]
    fn enu_basis_is_orthonormal_right_handed_and_up_is_radial(lat in -90.0f64..90.0, lon in -180.0f64..180.0) {
        let ll = LatLon { lat_deg: lat, lon_deg: lon };
        let [e, n, u] = enu_basis(ll);
        let dot = |a: [f64; 3], b: [f64; 3]| a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
        for (a, b) in [(e, n), (n, u), (e, u)] { prop_assert!(dot(a, b).abs() < 1e-12); }
        for v in [e, n, u] { prop_assert!((dot(v, v) - 1.0).abs() < 1e-12); }
        let cross = [e[1] * n[2] - e[2] * n[1], e[2] * n[0] - e[0] * n[2], e[0] * n[1] - e[1] * n[0]];
        for i in 0..3 { prop_assert!((cross[i] - u[i]).abs() < 1e-12); }
        let r = body_fixed(moon(), ll, 0.0);
        let norm = dot(r, r).sqrt();
        for i in 0..3 { prop_assert!((r[i] / norm - u[i]).abs() < 1e-12); }
    }

    #[test]
    fn body_fixed_radius_is_sphere_plus_height(lat in -90.0f64..90.0, lon in -180.0f64..180.0, h in -9000.0f64..11000.0) {
        let r = body_fixed(moon(), LatLon { lat_deg: lat, lon_deg: lon }, h);
        let norm = (r[0] * r[0] + r[1] * r[1] + r[2] * r[2]).sqrt();
        prop_assert!((norm - (1_737_400.0 + h)).abs() < 1e-6);
    }
}
