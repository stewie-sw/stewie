//! `GlobalGrid` (PDS LOLA LDEM, simple cylindrical) against the numpy oracle `global_ldem_samples`, and
//! mixed-source stacks. Refusal cases mutate copies of the real label (synthetic, labelled).

use std::fs;

use lunar_dem::{DemError, DemTile, GlobalGrid, Resolved, TerrainSource, TerrainStack};
use lunar_frames::{LatLon, Sphere};

fn moon() -> Sphere {
    let reg: serde_json::Value =
        serde_json::from_str(include_str!("../../stewie-contracts/fixtures/bodies.json")).unwrap();
    Sphere::new(reg["moon"]["ellipsoid_radius_m"].as_f64().unwrap()).unwrap()
}

fn ldem16() -> GlobalGrid {
    let d = stewie_oracle::repo_root().join(".cache/terrain");
    GlobalGrid::open(&d.join("ldem_16.img"), &d.join("ldem_16.lbl"), moon()).unwrap()
}

#[test]
fn global_heights_match_the_numpy_oracle() {
    let fx = stewie_oracle::load("global_ldem_samples").unwrap().payload;
    let g = ldem16();
    let mut n = 0;
    for s in fx["samples"].as_array().unwrap() {
        let ll = LatLon {
            lat_deg: s["lat_deg"].as_f64().unwrap(),
            lon_deg: s["lon_deg"].as_f64().unwrap(),
        };
        match s["height_m"].as_f64() {
            Some(want) => {
                let got = g
                    .sample_latlon(ll)
                    .unwrap_or_else(|| panic!("{ll:?} should be covered"));
                assert!((got - want).abs() < 1e-9, "{ll:?}: {got} vs {want}");
                n += 1;
            }
            None => assert!(
                g.sample_latlon(ll).is_none(),
                "{ll:?} is inside a polar cap"
            ),
        }
    }
    assert_eq!(n, 221);
    assert!(
        (g.resolution_m() - 2.0 * std::f64::consts::PI * 1_737_400.0 / 360.0 / 16.0).abs() < 1e-6
    );
}

#[test]
fn a_label_on_another_datum_or_a_short_image_is_refused() {
    let d = stewie_oracle::repo_root().join(".cache/terrain");
    let tmp = std::env::temp_dir().join(format!("lunar-dem-global-{}", std::process::id()));
    let _ = fs::remove_dir_all(&tmp);
    fs::create_dir_all(&tmp).unwrap();
    let label = fs::read_to_string(d.join("ldem_16.lbl")).unwrap();
    fs::write(
        tmp.join("other.lbl"),
        label.replacen(
            "OFFSET                = 1737400.",
            "OFFSET                = 1738000.",
            1,
        ),
    )
    .unwrap();
    assert!(matches!(
        GlobalGrid::open(&d.join("ldem_16.img"), &tmp.join("other.lbl"), moon()),
        Err(DemError::DatumMismatch { .. })
    ));
    fs::write(tmp.join("short.img"), vec![0u8; 1024]).unwrap();
    assert!(matches!(
        GlobalGrid::open(&tmp.join("short.img"), &d.join("ldem_16.lbl"), moon()),
        Err(DemError::SizeMismatch { .. })
    ));
}

#[test]
fn a_mixed_stack_prefers_the_tile_and_falls_back_to_the_global_grid() {
    let tile = DemTile::open(
        &stewie_oracle::repo_root().join("samples/lunar_dem/haworth_10km_5m"),
        moon(),
    )
    .unwrap();
    let inside = tile.cell_center_latlon(1000, 1000);
    let stack = TerrainStack::new(vec![
        (1, Box::new(tile) as Box<dyn TerrainSource>),
        (9, Box::new(ldem16())),
    ]);
    assert!(
        matches!(stack.resolve(inside), Resolved::Covered { source, .. } if source.id == "haworth_10km_5m")
    );
    let far = LatLon {
        lat_deg: -60.0,
        lon_deg: 100.0,
    };
    assert!(
        matches!(stack.resolve(far), Resolved::Covered { source, .. } if source.id == "ldem_16")
    );
    assert!(matches!(
        stack.resolve(LatLon {
            lat_deg: -89.99,
            lon_deg: 0.0
        }),
        Resolved::NotCovered
    ));
}

#[test]
fn stack_signature_names_tiers_by_shape_not_by_tile() {
    let root = stewie_oracle::repo_root().join("samples/lunar_dem");
    let a = TerrainStack::new(vec![
        (
            1,
            Box::new(DemTile::open(&root.join("haworth_10km_5m"), moon()).unwrap())
                as Box<dyn TerrainSource>,
        ),
        (9, Box::new(ldem16())),
    ]);
    let b = TerrainStack::new(vec![
        (
            1,
            Box::new(DemTile::open(&root.join("malapert_massif_10km_5m"), moon()).unwrap())
                as Box<dyn TerrainSource>,
        ),
        (9, Box::new(ldem16())),
    ]);
    let c = TerrainStack::new(vec![(9, Box::new(ldem16()) as Box<dyn TerrainSource>)]);
    assert_eq!(
        a.signature(),
        b.signature(),
        "different sites on the same tier shape are comparable"
    );
    assert_ne!(
        a.signature(),
        c.signature(),
        "dropping the regional tier changes the stack"
    );
    assert!(a.signature().starts_with("regional@5.0m > ldem_16@"));
}
