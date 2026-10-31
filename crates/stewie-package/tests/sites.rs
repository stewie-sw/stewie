//! The device package `south_polar_sites` (RW-60d): every 40 m site crop is an exact subset of
//! `LDEM_85S_40M` (the same heights at the same places), each crop's declared box is truthful (inside it
//! the 40 m tier answers), and outside every box the 240 m tier or `LDEM_16` answers. Sample points are
//! SYNTHETIC (a seeded grid over each box, labelled); the heights are LOLA's.

use lunar_dem::{PolarGrid, TerrainSource};
use lunar_frames::{LatLon, PolarStereographic, Sphere};
use stewie_package::Package;

fn moon() -> Sphere {
    let reg: serde_json::Value =
        serde_json::from_str(include_str!("../../stewie-contracts/fixtures/bodies.json")).unwrap();
    Sphere::new(reg["moon"]["ellipsoid_radius_m"].as_f64().unwrap()).unwrap()
}

#[test]
#[allow(clippy::cast_precision_loss)]
fn every_crop_is_an_exact_subset_and_its_box_is_truthful() {
    let root = stewie_oracle::repo_root();
    let pkg = Package::open(&root.join(".cache/package/south_polar_sites"), moon()).unwrap();
    let terrain = root.join(".cache/terrain");
    let full = PolarGrid::open(
        &terrain.join("ldem_85s_40m.img"),
        &terrain.join("ldem_85s_40m.lbl"),
        moon(),
    )
    .unwrap();
    let proj = PolarStereographic::south(moon());
    let (t0, _) = pkg.ephemeris().span_tdb();
    let crops: Vec<_> = pkg
        .manifest()
        .layers
        .iter()
        .filter(|l| l.polar_box_m.is_some())
        .collect();
    assert_eq!(
        crops.len(),
        14,
        "a crop per catalog site inside the 40 m grid"
    );
    let mut checked = 0;
    for l in crops {
        let bx = l.polar_box_m.as_ref().unwrap();
        for i in 1..20 {
            for j in 1..20 {
                let (e, n) = (
                    bx[0] + (bx[2] - bx[0]) * f64::from(i) / 20.0,
                    bx[1] + (bx[3] - bx[1]) * f64::from(j) / 20.0,
                );
                let ll: LatLon = proj.inverse(e, n);
                let c = pkg.guard(ll, t0, t0, 1e9).unwrap();
                assert!(
                    c.source.id.starts_with("ldem_85s_40m_"),
                    "{} box point answered by {}",
                    l.id.as_str(),
                    c.source.id
                );
                let want = full.sample_latlon(ll).unwrap();
                assert!(
                    (c.height_m - want).abs() < 1e-6,
                    "{}: {} vs {want}",
                    l.id.as_str(),
                    c.height_m
                );
                checked += 1;
            }
        }
    }
    assert!(checked > 5000);
    let far = LatLon {
        lat_deg: -80.0,
        lon_deg: 10.0,
    };
    assert_eq!(
        pkg.guard(far, t0, t0, 1e9).unwrap().source.id,
        "ldem_75s_240m"
    );
    let north = LatLon {
        lat_deg: 40.0,
        lon_deg: 10.0,
    };
    assert_eq!(pkg.guard(north, t0, t0, 1e9).unwrap().source.id, "ldem_16");
}
