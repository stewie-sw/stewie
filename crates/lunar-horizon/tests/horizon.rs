//! lunar-horizon against the NumPy/pyproj oracle (`horizon_profiles`: six observers on three real tiles)
//! and against analytic cases on synthetic in-memory tiles (labelled synthetic).

use lunar_dem::{DemTile, TerrainStack};
use lunar_frames::{LatLon, PolarStereographic, Sphere};
use lunar_horizon::{HorizonConfig, HorizonError, disk_fraction_visible, horizon};

fn moon() -> Sphere {
    let reg: serde_json::Value =
        serde_json::from_str(include_str!("../../stewie-contracts/fixtures/bodies.json")).unwrap();
    Sphere::new(reg["moon"]["ellipsoid_radius_m"].as_f64().unwrap()).unwrap()
}

fn tile(name: &str) -> DemTile {
    DemTile::open(
        &stewie_oracle::repo_root()
            .join("samples/lunar_dem")
            .join(name),
        moon(),
    )
    .unwrap()
}

#[test]
fn real_horizons_match_the_oracle_within_r4() {
    let fx = stewie_oracle::load("horizon_profiles").unwrap().payload;
    let n_az = usize::try_from(fx["n_az"].as_u64().unwrap()).unwrap();
    let mut worst = 0.0f64;
    for p in fx["profiles"].as_array().unwrap() {
        let stack = TerrainStack::new(vec![(1, tile(p["tile"].as_str().unwrap()))]);
        let cfg = HorizonConfig {
            n_az,
            max_range_m: fx["max_range_m"].as_f64().unwrap(),
            step_m: p["step_m"].as_f64().unwrap(),
            eye_height_m: p["eye_m"].as_f64().unwrap(),
        };
        let at = LatLon {
            lat_deg: p["lat_deg"].as_f64().unwrap(),
            lon_deg: p["lon_deg"].as_f64().unwrap(),
        };
        let h = horizon(&stack, at, &cfg).unwrap();
        let want = p["elev_deg"].as_array().unwrap();
        let reach = p["reach_m"].as_array().unwrap();
        let mut errs: Vec<f64> = (0..n_az)
            .map(|k| (h.elev_deg[k].unwrap() - want[k].as_f64().unwrap()).abs())
            .collect();
        for ((got, done), want) in h.reach_m.iter().zip(&h.complete).zip(reach) {
            assert!(
                (got - want.as_f64().unwrap()).abs() <= cfg.step_m,
                "reach {got} vs {want}"
            );
            assert!(!done, "a 10 km tile cannot complete a 200 km ray");
        }
        errs.sort_by(f64::total_cmp);
        let p95 = errs[(errs.len() * 95) / 100];
        assert!(p95 < 0.1, "R4: 95th-percentile error {p95} deg");
        worst = worst.max(errs[errs.len() - 1]);
    }
    assert!(worst < 1e-6, "worst azimuth error {worst} deg");
}

/// Synthetic tile (labelled) centred on a polar point; built in memory for analytic checks.
#[allow(clippy::many_single_char_names)] // grid geometry: w, h, e, n, z
fn synthetic_tile(f: impl Fn(f64, f64) -> f32) -> (DemTile, LatLon) {
    let (w, h, cell) = (2001usize, 2001usize, 5.0f64);
    let (ce, cn) = (0.0f64, 100_000.0f64);
    let x0 = ce - cell * 1000.5;
    let y1 = cn + cell * 1000.5;
    let mut z = Vec::with_capacity(w * h);
    for r in 0..h {
        for c in 0..w {
            #[allow(clippy::cast_precision_loss)]
            let (e, n) = (x0 + cell * (c as f64 + 0.5), y1 - cell * (r as f64 + 0.5));
            z.push(f(e - ce, n - cn));
        }
    }
    let t = DemTile::from_grid(
        "synthetic",
        z,
        w,
        h,
        cell,
        [x0, y1 - cell * 2001.0, x0 + cell * 2001.0, y1],
        moon(),
    )
    .unwrap();
    let centre = PolarStereographic::south(moon()).inverse(ce, cn);
    (t, centre)
}

#[test]
fn flat_sphere_gives_the_analytic_curvature_dip() {
    let (t, centre) = synthetic_tile(|_, _| 0.0);
    let stack = TerrainStack::new(vec![(1, t)]);
    let cfg = HorizonConfig {
        n_az: 8,
        max_range_m: 4000.0,
        step_m: 1.0,
        eye_height_m: 1.5,
    };
    let h = horizon(&stack, centre, &cfg).unwrap();
    let r = moon().radius_m();
    let dip = -(r / (r + 1.5)).acos().to_degrees();
    for k in 0..8 {
        assert!(
            (h.elev_deg[k].unwrap() - dip).abs() < 1e-4,
            "{} vs {dip}",
            h.elev_deg[k].unwrap()
        );
        assert!(h.complete[k]);
    }
}

#[test]
fn a_cone_apex_gives_its_exact_spherical_elevation() {
    // apex 400 m high, 3000 m grid-north of the centre, base radius 1500 m (synthetic)
    let (t, centre) = synthetic_tile(|dx, dy| {
        let d = dx.hypot(dy - 3000.0);
        #[allow(clippy::cast_possible_truncation)]
        let z = (400.0 * (1.0 - d / 1500.0)).max(0.0) as f32;
        z
    });
    let stack = TerrainStack::new(vec![(1, t)]);
    let cfg = HorizonConfig {
        n_az: 720,
        max_range_m: 5000.0,
        step_m: 1.0,
        eye_height_m: 0.0,
    };
    let h = horizon(&stack, centre, &cfg).unwrap();
    let r = moon().radius_m();
    let theta = 3000.0 / r;
    let want = ((r + 400.0) * theta.cos() - r)
        .atan2((r + 400.0) * theta.sin())
        .to_degrees();
    let best = h
        .elev_deg
        .iter()
        .map(|e| e.unwrap())
        .fold(f64::MIN, f64::max);
    assert!((best - want).abs() < 0.05, "{best} vs {want}");
}

#[test]
fn an_observer_outside_coverage_cannot_be_assessed() {
    let stack = TerrainStack::new(vec![(1, tile("haworth_10km_5m"))]);
    let cfg = HorizonConfig {
        n_az: 8,
        max_range_m: 1000.0,
        step_m: 5.0,
        eye_height_m: 1.5,
    };
    assert!(matches!(
        horizon(
            &stack,
            LatLon {
                lat_deg: -45.0,
                lon_deg: 0.0
            },
            &cfg
        ),
        Err(HorizonError::NotCovered)
    ));
}

#[test]
fn disk_fraction_is_bounded_monotone_and_half_at_the_line() {
    let r = 0.27;
    assert!((disk_fraction_visible(5.0, r, 5.0) - 0.5).abs() < 1e-12);
    assert!((disk_fraction_visible(5.0 + r, r, 5.0) - 1.0).abs() < 1e-12);
    assert!(disk_fraction_visible(5.0 - r, r, 5.0).abs() < 1e-12);
    let mut prev = -1.0;
    for i in 0..=100 {
        let f = disk_fraction_visible(5.0 - r + 2.0 * r * f64::from(i) / 100.0, r, 5.0);
        assert!((0.0..=1.0).contains(&f) && f >= prev);
        prev = f;
    }
}
