//! The route profile (N23): a SYNTHETIC 10 deg ramp (labelled) gives the analytic along-track slope in
//! every direction; segment times are contiguous and sum to the total; an unusable speed or an off-DEM
//! waypoint is refused; and on the REAL Haworth window a routed leg, timed at the rover profile's sourced
//! drive speed, places every node at its georeferenced cell with the Sun and Earth at its arrival time, and
//! gives each node the same Sun and Earth verdict as the visibility windows over that node's horizon.

use lunar_dem::{DemTile, GlobalGrid, TerrainSource, TerrainStack};
use lunar_ephem::{Body, Ephemeris, Utc, az_el};
use lunar_frames::{Sphere, body_fixed};
use lunar_horizon::{HorizonConfig, horizon};
use lunar_intervals::{Verdict, VisibilityConfig, visibility_windows};
use serde_json::Value;
use stewie_traverse::costmap::CostmapOptions;
use stewie_traverse::profile::{NodeSky, ProfileError, SkyFrame, profile};
use stewie_traverse::route::{Dem, route_leg};

#[track_caller]
fn close(got: f64, want: f64, tol: f64, what: &str) {
    assert!((got - want).abs() <= tol, "{what}: {got} vs {want}");
}

#[allow(clippy::cast_precision_loss)]
fn ramp() -> Vec<f64> {
    // SYNTHETIC: z rises 10 deg along +x, flat along y (50 x 50 at 2 m)
    (0..2500)
        .map(|i| f64::from(i % 50) * 2.0 * 10f64.to_radians().tan())
        .collect()
}

#[test]
#[allow(clippy::cast_precision_loss)]
fn a_ramp_gives_the_analytic_slope_and_times_add_up() {
    let z = ramp();
    let dem = Dem {
        z: &z,
        width: 50,
        height: 50,
        cell_m: 2.0,
        origin: (0.0, 0.0),
    };
    let up: Vec<(f64, f64)> = (0..20).map(|k| (f64::from(k) * 2.0, 10.0)).collect();
    let p = profile(dem, &up, &|_| 0.3, None).unwrap();
    for s in &p.segments {
        close(s.slope_deg, 10.0, 1e-9, "uphill");
    }
    let down: Vec<(f64, f64)> = up.iter().rev().copied().collect();
    assert!(
        profile(dem, &down, &|_| 0.3, None)
            .unwrap()
            .segments
            .iter()
            .all(|s| (s.slope_deg + 10.0).abs() < 1e-9)
    );
    let across: Vec<(f64, f64)> = (0..20).map(|k| (20.0, f64::from(k) * 2.0)).collect();
    assert!(
        profile(dem, &across, &|_| 0.3, None)
            .unwrap()
            .segments
            .iter()
            .all(|s| s.slope_deg.abs() < 1e-12)
    );
    let diag: Vec<(f64, f64)> = (0..20)
        .map(|k| (f64::from(k) * 2.0, f64::from(k) * 2.0))
        .collect();
    let want = (10f64.to_radians().tan() / 2f64.sqrt()).atan().to_degrees();
    assert!(
        profile(dem, &diag, &|_| 0.3, None)
            .unwrap()
            .segments
            .iter()
            .all(|s| (s.slope_deg - want).abs() < 1e-9)
    );
    let mut t = 0.0;
    for s in &p.segments {
        close(s.t_start_s, t, 1e-12, "contiguous");
        close(
            s.t_end_s - s.t_start_s,
            s.length_m / 0.3,
            1e-9,
            "segment time",
        );
        t = s.t_end_s;
    }
    close(p.total_s, t, 1e-12, "times sum to the total");
    close(
        p.total_m,
        19.0 * 2.0 / 10f64.to_radians().cos(),
        1e-9,
        "surface length",
    );
}

#[test]
fn no_speed_and_off_dem_are_refused() {
    let z = ramp();
    let dem = Dem {
        z: &z,
        width: 50,
        height: 50,
        cell_m: 2.0,
        origin: (0.0, 0.0),
    };
    let up = [(0.0, 10.0), (2.0, 10.0), (4.0, 10.0)];
    let slow_on_slopes = |s: f64| if s > 5.0 { 0.0 } else { 0.3 };
    assert!(matches!(
        profile(dem, &up, &slow_on_slopes, None),
        Err(ProfileError::NoSpeed { segment: 0, .. })
    ));
    assert!(matches!(
        profile(dem, &up, &|_| f64::NAN, None),
        Err(ProfileError::NoSpeed { .. })
    ));
    assert!(matches!(
        profile(dem, &[(0.0, 0.0), (500.0, 0.0)], &|_| 0.3, None),
        Err(ProfileError::OffDem(_))
    ));
}

/// 2-degree azimuth bins out to 20 km at 50 m steps, eye 1 m (the frame's eye height overrides it).
fn horizon_cfg() -> HorizonConfig {
    HorizonConfig {
        n_az: 180,
        max_range_m: 20_000.0,
        step_m: 50.0,
        eye_height_m: 1.0,
        start_m: 0.0,
    }
}

/// The REAL Haworth 5 m tile over `LDEM_16`, so 20 km horizon rays complete.
fn haworth_over_ldem16(moon: Sphere) -> TerrainStack {
    let root = stewie_oracle::repo_root();
    let cache = root.join(".cache/terrain");
    let tile = DemTile::open(&root.join("samples/lunar_dem/haworth_10km_5m"), moon).unwrap();
    let global =
        GlobalGrid::open(&cache.join("ldem_16.img"), &cache.join("ldem_16.lbl"), moon).unwrap();
    TerrainStack::new(vec![
        (1, Box::new(tile) as Box<dyn TerrainSource>),
        (9, Box::new(global)),
    ])
}

/// A node's Sun and Earth verdicts equal the visibility windows over the same horizon at its arrival.
fn window_verdicts_agree(
    eph: &Ephemeris,
    terrain: &TerrainStack,
    hcfg: &HorizonConfig,
    node: &NodeSky,
    ground_m: f64,
    moon: Sphere,
) {
    let h = horizon(terrain, node.site, hcfg).unwrap();
    let cfg = VisibilityConfig {
        sample_s: 60.0,
        tolerance_s: 1.0,
        eye_height_m: hcfg.eye_height_m,
        ground_height_m: ground_m,
        moon,
    };
    for (body, got) in [
        (Body::Sun, node.sun_verdict),
        (Body::Earth, node.earth_verdict),
    ] {
        let ws = visibility_windows(
            eph,
            &h,
            node.site,
            body,
            node.tdb - 600.0,
            node.tdb + 600.0,
            &cfg,
        )
        .unwrap();
        let w = ws
            .iter()
            .find(|w| w.start_tdb <= node.tdb && node.tdb <= w.end_tdb)
            .unwrap();
        assert_eq!(got, w.verdict, "{body:?} at {:?}", node.site);
    }
}

#[test]
#[allow(
    clippy::cast_possible_truncation,
    clippy::cast_precision_loss,
    clippy::cast_sign_loss
)]
fn a_real_route_is_timed_and_its_sky_placed_at_each_georeferenced_node() {
    let fx = stewie_oracle::load("route_cases").unwrap().payload;
    let num = |v: &Value| v.as_f64().unwrap();
    let (cols, rows) = (
        fx["width"].as_u64().unwrap() as usize,
        fx["height"].as_u64().unwrap() as usize,
    );
    let z: Vec<f64> = fx["z"].as_array().unwrap().iter().map(num).collect();
    let dem = Dem {
        z: &z,
        width: cols,
        height: rows,
        cell_m: num(&fx["cell_m"]),
        origin: (num(&fx["origin"][0]), num(&fx["origin"][1])),
    };
    let leg = &fx["legs"][0];
    let opts = CostmapOptions {
        max_slope_deg: 25.0,
        slip_alpha: 2.0,
        max_drop_m: None,
        illumination: None,
        map_uncertainty: None,
    };
    let route = route_leg(
        dem,
        (num(&leg["a"][0]), num(&leg["a"][1])),
        (num(&leg["b"][0]), num(&leg["b"][1])),
        &opts,
        20.0,
        &[],
    )
    .unwrap();
    assert!(route.reached);

    let rover: Value = serde_json::from_str(include_str!(
        "../../stewie-contracts/fixtures/rover_ipex.json"
    ))
    .unwrap();
    let speed = num(&rover["drive_speed_ms"]["value"]);
    assert_eq!(rover["drive_speed_ms"]["tag"], "SOURCED");
    let bodies: Value =
        serde_json::from_str(include_str!("../../stewie-contracts/fixtures/bodies.json")).unwrap();
    let moon = Sphere::new(num(&bodies["moon"]["ellipsoid_radius_m"])).unwrap();
    let tile = DemTile::open(
        &stewie_oracle::repo_root().join("samples/lunar_dem/haworth_10km_5m"),
        moon,
    )
    .unwrap();
    let (wr, wc) = (num(&fx["window"][0]), num(&fx["window"][1]));
    let to_ll = |row: f64, col: f64| tile.grid_latlon(wr + row, wc + col);
    let eph = Ephemeris::bundled().unwrap();
    let depart = eph.tdb(&Utc::parse_iso8601("2027-01-15T00:00:00Z").unwrap());
    let terrain = haworth_over_ldem16(moon);
    let sky = SkyFrame {
        to_latlon: &to_ll,
        moon,
        ephemeris: &eph,
        depart_tdb: depart,
        eye_height_m: 1.0,
        terrain: &terrain,
        horizon: horizon_cfg(),
    };
    let p = profile(dem, &route.waypoints, &|_| speed, Some(&sky)).unwrap();
    assert_eq!(p.sky.len(), route.waypoints.len());
    close(p.total_s, p.total_m / speed, 1e-6, "constant rover speed");
    assert!(
        p.total_m >= route.routed_m,
        "surface length is at least the planar path length"
    );
    for (k, node) in p.sky.iter().enumerate() {
        let (x, y) = route.waypoints[k];
        let (row, col) = (
            (y + dem.origin.1) / dem.cell_m,
            (x + dem.origin.0) / dem.cell_m,
        );
        let cell = tile.cell_center_latlon((wr + row) as usize, (wc + col) as usize);
        close(node.site.lat_deg, cell.lat_deg, 1e-9, "node lat");
        close(node.site.lon_deg, cell.lon_deg, 1e-9, "node lon");
        let arrive = if k == 0 {
            0.0
        } else {
            p.segments[k - 1].t_end_s
        };
        close(node.tdb, depart + arrive, 1e-6, "arrival epoch");
        let ground = z[row as usize * cols + col as usize];
        let pos = body_fixed(moon, node.site, ground + 1.0);
        let sun = az_el(
            eph.apparent_from(Body::Sun, node.tdb, pos).unwrap(),
            node.site,
        );
        close(node.sun.el_deg, sun.el_deg, 1e-12, "sun elevation");
        assert!(
            node.sun.el_deg.abs() < 10.0,
            "near the south pole the Sun grazes the horizon"
        );
        if [0, p.sky.len() / 2, p.sky.len() - 1].contains(&k) {
            window_verdicts_agree(&eph, &terrain, &sky.horizon, node, ground, moon);
        }
    }
    // vacuity: the 5 m tile over LDEM_16 completes the rays, so some node has a definite Sun verdict
    let definite = p.sky.iter().filter(|n| n.sun_verdict != Verdict::Unknown);
    assert!(definite.count() > 0, "every Sun verdict is Unknown");
}
