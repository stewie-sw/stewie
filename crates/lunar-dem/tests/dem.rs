//! lunar-dem against the oracle (stewie-oracle `dem_samples`: Python `read_dem_window`, `slope_deg_map` and
//! pyproj over the ten real bundles). Refusal cases mutate copies of real files in a temp dir (synthetic,
//! labelled).

use std::fs;
use std::path::PathBuf;

use lunar_dem::{DemError, DemTile, Resolved, TerrainStack};
use lunar_frames::{LatLon, Sphere};

fn moon() -> Sphere {
    let reg: serde_json::Value =
        serde_json::from_str(include_str!("../../stewie-contracts/fixtures/bodies.json")).unwrap();
    Sphere::new(reg["moon"]["ellipsoid_radius_m"].as_f64().unwrap()).unwrap()
}

fn bundle(name: &str) -> PathBuf {
    stewie_oracle::repo_root()
        .join("samples/lunar_dem")
        .join(name)
}

fn oracle() -> serde_json::Value {
    stewie_oracle::load("dem_samples").unwrap().payload
}

fn for_each_cell(mut f: impl FnMut(&DemTile, &serde_json::Value)) {
    for b in oracle()["bundles"].as_array().unwrap() {
        let tile = DemTile::open(&bundle(b["bundle"].as_str().unwrap()), moon()).unwrap();
        for c in b["cells"].as_array().unwrap() {
            f(&tile, c);
        }
    }
}

fn rc(c: &serde_json::Value) -> (usize, usize) {
    (
        usize::try_from(c["row"].as_u64().unwrap()).unwrap(),
        usize::try_from(c["col"].as_u64().unwrap()).unwrap(),
    )
}

#[test]
fn heights_equal_the_bundle_bytes_at_every_oracle_cell() {
    let mut n = 0;
    for_each_cell(|t, c| {
        let (r, k) = rc(c);
        assert_eq!(t.height_at(r, k), Some(c["height_m"].as_f64().unwrap()));
        n += 1;
    });
    assert_eq!(n, 160);
}

#[test]
fn slope_matches_numpy_gradient() {
    for_each_cell(|t, c| {
        let (r, k) = rc(c);
        let s = t.slope_deg_at(r, k).unwrap();
        assert!(
            (s - c["slope_deg"].as_f64().unwrap()).abs() < 1e-9,
            "{} {s}",
            t.id()
        );
    });
}

#[test]
fn cell_centres_georeference_to_the_pyproj_latlon() {
    for_each_cell(|t, c| {
        let (r, k) = rc(c);
        let ll = t.cell_center_latlon(r, k);
        assert!((ll.lat_deg - c["lat_deg"].as_f64().unwrap()).abs() < 1e-9);
        let dlon = (ll.lon_deg - c["lon_deg"].as_f64().unwrap() + 540.0) % 360.0 - 180.0;
        assert!(dlon.abs() < 1e-9);
    });
}

#[test]
fn latlon_sampling_at_a_cell_centre_returns_that_cell() {
    for_each_cell(|t, c| {
        let (r, k) = rc(c);
        let ll = LatLon {
            lat_deg: c["lat_deg"].as_f64().unwrap(),
            lon_deg: c["lon_deg"].as_f64().unwrap(),
        };
        let z = t.sample_latlon(ll).unwrap();
        assert!(
            (z - t.height_at(r, k).unwrap()).abs() < 1e-6,
            "{} {z}",
            t.id()
        );
    });
}

#[test]
#[allow(clippy::many_single_char_names)] // bilinear algebra reads clearest with its textbook names
fn bilinear_between_centres_is_the_weighted_mean_of_the_four_neighbours() {
    let t = DemTile::open(&bundle("haworth_10km_5m"), moon()).unwrap();
    let (r, k) = (700usize, 1200usize);
    let (e0, n0) = t.cell_center_projected(r, k);
    let (fx, fy) = (0.25, 0.6); // fraction toward col+1 and row+1 (south)
    let z = t
        .sample_projected(e0 + fx * t.cell_m(), n0 - fy * t.cell_m())
        .unwrap();
    let h = |a, b| t.height_at(a, b).unwrap();
    let want = (1.0 - fy) * ((1.0 - fx) * h(r, k) + fx * h(r, k + 1))
        + fy * ((1.0 - fx) * h(r + 1, k) + fx * h(r + 1, k + 1));
    assert!((z - want).abs() < 1e-9);
}

#[test]
fn sampling_outside_the_tile_is_none_not_extrapolated() {
    let t = DemTile::open(&bundle("haworth_10km_5m"), moon()).unwrap();
    assert!(
        t.sample_latlon(LatLon {
            lat_deg: -60.0,
            lon_deg: 0.0
        })
        .is_none()
    );
    assert!(t.height_at(t.height(), 0).is_none());
}

#[test]
fn stack_resolves_by_priority_falls_through_and_names_the_source() {
    let stack = TerrainStack::new(vec![
        (
            1,
            DemTile::open(&bundle("haworth_sfs_2km_1m"), moon()).unwrap(),
        ),
        (
            2,
            DemTile::open(&bundle("haworth_10km_5m"), moon()).unwrap(),
        ),
        (
            3,
            DemTile::open(&bundle("shackleton_rim_10km_5m"), moon()).unwrap(),
        ),
    ]);
    let haworth = DemTile::open(&bundle("haworth_10km_5m"), moon()).unwrap();
    match stack.resolve(haworth.cell_center_latlon(1000, 1000)) {
        Resolved::Covered { source, height_m } => {
            assert_eq!(source.id, "haworth_10km_5m");
            assert!((source.resolution_m - 5.0).abs() < 1e-12);
            assert_eq!(source.priority, 2);
            assert!((height_m - haworth.height_at(1000, 1000).unwrap()).abs() < 1e-6);
        }
        Resolved::NotCovered => panic!("Haworth point must resolve"),
    }
    let sfs = DemTile::open(&bundle("haworth_sfs_2km_1m"), moon()).unwrap();
    assert!(
        matches!(stack.resolve(sfs.cell_center_latlon(10, 10)), Resolved::Covered { source, .. } if source.id == "haworth_sfs_2km_1m")
    );
    assert!(matches!(
        stack.resolve(LatLon {
            lat_deg: -45.0,
            lon_deg: 30.0
        }),
        Resolved::NotCovered
    ));
}

#[test]
fn a_bundle_on_a_different_datum_is_refused() {
    let wrong = Sphere::new(1_737_000.0).unwrap();
    assert!(matches!(
        DemTile::open(&bundle("haworth_10km_5m"), wrong),
        Err(DemError::DatumMismatch { .. })
    ));
}

#[test]
fn a_truncated_heightmap_is_refused() {
    let dir = std::env::temp_dir().join(format!("lunar-dem-trunc-{}", std::process::id()));
    let _ = fs::remove_dir_all(&dir);
    fs::create_dir_all(&dir).unwrap();
    let src = bundle("haworth_sfs_2km_1m");
    fs::copy(src.join("metadata.json"), dir.join("metadata.json")).unwrap();
    let bytes = fs::read(src.join("heightmap.rf32")).unwrap();
    fs::write(dir.join("heightmap.rf32"), &bytes[..bytes.len() / 2]).unwrap(); // synthetic truncation
    assert!(matches!(
        DemTile::open(&dir, moon()),
        Err(DemError::SizeMismatch { .. })
    ));
}

#[test]
fn a_metadata_only_bundle_is_refused_as_missing_heights() {
    assert!(matches!(
        DemTile::open(&bundle("de_gerlache_kocher_10km_5m"), moon()),
        Err(DemError::Io { .. })
    ));
}
