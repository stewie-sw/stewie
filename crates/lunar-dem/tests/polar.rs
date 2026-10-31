//! `PolarGrid` (PDS LOLA polar-stereographic LDEM) against the numpy + pyproj oracle `polar_ldem_samples`.
//! The refusal case mutates a copy of the real label (synthetic, labelled).

use std::fs;

use lunar_dem::{DemError, PolarGrid, Resolved, TerrainSource, TerrainStack};
use lunar_frames::{LatLon, Sphere};

fn moon() -> Sphere {
    let reg: serde_json::Value =
        serde_json::from_str(include_str!("../../stewie-contracts/fixtures/bodies.json")).unwrap();
    Sphere::new(reg["moon"]["ellipsoid_radius_m"].as_f64().unwrap()).unwrap()
}

fn grid(name: &str) -> PolarGrid {
    let d = stewie_oracle::repo_root().join(".cache/terrain");
    PolarGrid::open(
        &d.join(format!("{name}.img")),
        &d.join(format!("{name}.lbl")),
        moon(),
    )
    .unwrap()
}

#[test]
fn polar_heights_match_the_numpy_oracle() {
    let fx = stewie_oracle::load("polar_ldem_samples").unwrap().payload;
    for (name, cell_m) in [("ldem_85s_40m", 40.0), ("ldem_75s_240m", 240.0)] {
        let g = grid(name);
        assert!((g.resolution_m() - cell_m).abs() < 1e-12);
        let (mut covered, mut outside) = (0, 0);
        for s in fx["grids"][name].as_array().unwrap() {
            let ll = LatLon {
                lat_deg: s["lat_deg"].as_f64().unwrap(),
                lon_deg: s["lon_deg"].as_f64().unwrap(),
            };
            if let Some(want) = s["height_m"].as_f64() {
                let got = g
                    .sample_latlon(ll)
                    .unwrap_or_else(|| panic!("{name} {ll:?}"));
                assert!((got - want).abs() < 1e-6, "{name} {ll:?}: {got} vs {want}");
                covered += 1;
            } else {
                assert!(g.sample_latlon(ll).is_none(), "{name} {ll:?} is outside");
                outside += 1;
            }
        }
        // both branches are exercised on real points: the pole and sites inside, 60S outside
        assert!(
            covered > 20 && outside > 5,
            "{name}: {covered} in, {outside} out"
        );
    }
}

#[test]
fn the_pole_resolves_on_the_polar_tier() {
    let stack = TerrainStack::new(vec![(
        1,
        Box::new(grid("ldem_85s_40m")) as Box<dyn TerrainSource>,
    )]);
    assert!(matches!(
        stack.resolve(LatLon {
            lat_deg: -90.0,
            lon_deg: 0.0
        }),
        Resolved::Covered { .. }
    ));
    assert_eq!(stack.signature(), "regional@40.0m");
}

#[test]
fn a_label_that_is_not_a_pole_or_not_polar_is_refused() {
    let d = stewie_oracle::repo_root().join(".cache/terrain");
    let tmp = std::env::temp_dir().join(format!("lunar-dem-polar-{}", std::process::id()));
    let _ = fs::remove_dir_all(&tmp);
    fs::create_dir_all(&tmp).unwrap();
    let label = fs::read_to_string(d.join("ldem_75s_240m.lbl")).unwrap();
    let img = d.join("ldem_75s_240m.img");
    for (from, to) in [
        (
            "CENTER_LATITUDE              = -90",
            "CENTER_LATITUDE              = -80",
        ),
        ("\"POLAR STEREOGRAPHIC\"", "\"SIMPLE CYLINDRICAL\""),
        (
            "CENTER_LONGITUDE             = 0",
            "CENTER_LONGITUDE             = 90",
        ),
    ] {
        assert!(label.contains(from), "real label lacks {from}");
        fs::write(tmp.join("bad.lbl"), label.replacen(from, to, 1)).unwrap();
        assert!(
            matches!(
                PolarGrid::open(&img, &tmp.join("bad.lbl"), moon()),
                Err(DemError::Contract { .. })
            ),
            "{to} should be refused"
        );
    }
    fs::remove_dir_all(&tmp).unwrap();
}
