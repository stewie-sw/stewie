//! The `lola_base` package (built by `pipeline/build_package.py` from real LOLA tiers and the bundled
//! ephemeris) against navigator N11 and N12 (requirement R6). Sampled points come from a seeded generator
//! (synthetic locations, labelled) plus deliberate edge points, because uniform sampling almost never lands
//! in a pole cap or on a tier boundary. Integrity refusals use mutated copies (synthetic, labelled).

use std::fs;
use std::path::PathBuf;

use lunar_frames::{LatLon, Sphere};
use stewie_package::{CannotAssess, Package, PackageError};

fn moon() -> Sphere {
    let reg: serde_json::Value =
        serde_json::from_str(include_str!("../../stewie-contracts/fixtures/bodies.json")).unwrap();
    Sphere::new(reg["moon"]["ellipsoid_radius_m"].as_f64().unwrap()).unwrap()
}

fn dir() -> PathBuf {
    stewie_oracle::repo_root().join(".cache/package/lola_base")
}

fn package() -> Package {
    Package::open(&dir(), moon()).unwrap()
}

/// splitmix64: synthetic sample locations only.
struct Rng(u64);

impl Rng {
    #[allow(clippy::cast_precision_loss)]
    fn unit(&mut self) -> f64 {
        self.0 = self.0.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        (z ^ (z >> 31)) as f64 / u64::MAX as f64
    }
}

/// 20,000 points uniform on the sphere plus the edges: both poles and their caps, the longitude seam,
/// and both sides of every tier boundary.
fn points() -> Vec<LatLon> {
    let ll = |lat_deg, lon_deg| LatLon { lat_deg, lon_deg };
    let mut out = Vec::new();
    for lat in [
        -90.0, -89.9999, -89.99, -89.97, -85.0, -84.9999, -75.0, -74.9999, 0.0, 74.9999, 75.0,
        89.97, 89.99, 89.9999, 90.0,
    ] {
        for lon in [-180.0, -90.0, 0.0, 45.0, 180.0, 359.999, 360.0] {
            out.push(ll(lat, lon));
        }
    }
    let mut r = Rng(20_261_031);
    for _ in 0..20_000 {
        let lat = (2.0 * r.unit() - 1.0).asin().to_degrees();
        out.push(ll(lat, 360.0 * r.unit() - 180.0));
    }
    out
}

fn mid_span(p: &Package) -> (f64, f64) {
    let (s, e) = p.ephemeris().span_tdb();
    (s + 0.25 * (e - s), s + 0.75 * (e - s))
}

#[test]
fn every_layer_is_pinned_sourced_versioned_licensed_and_sized() {
    let p = package();
    let m = p.manifest();
    assert_eq!(m.layers.len(), 4);
    for l in &m.layers {
        assert!(
            l.source
                .as_str()
                .starts_with("https://pds-geosciences.wustl.edu/")
        );
        assert!(!l.version.is_empty() && !l.license.statement.is_empty());
        assert!(l.license.url.as_str().starts_with("https://"));
    }
    let committed: serde_json::Value = serde_json::from_str(
        &fs::read_to_string(stewie_oracle::repo_root().join("pipeline/packages/lola_base.json"))
            .unwrap(),
    )
    .unwrap();
    let installed: serde_json::Value =
        serde_json::from_str(&fs::read_to_string(dir().join("manifest.json")).unwrap()).unwrap();
    assert_eq!(
        committed, installed,
        "installed package is the committed manifest"
    );
}

#[test]
fn a_changed_byte_or_an_escaping_path_refuses_the_whole_package() {
    let tmp = std::env::temp_dir().join(format!("stewie-package-{}", std::process::id()));
    let _ = fs::remove_dir_all(&tmp);
    fs::create_dir_all(&tmp).unwrap();
    for e in fs::read_dir(dir()).unwrap().flatten() {
        let to = tmp.join(e.file_name());
        if fs::hard_link(e.path(), &to).is_err() {
            fs::copy(e.path(), &to).unwrap();
        }
    }
    let lbl = tmp.join("ldem_16.lbl");
    let mut bytes = fs::read(&lbl).unwrap();
    fs::remove_file(&lbl).unwrap(); // break the hard link before mutating
    bytes[10] ^= 0x01;
    fs::write(&lbl, &bytes).unwrap();
    assert!(matches!(
        Package::open(&tmp, moon()),
        Err(PackageError::Integrity { .. })
    ));
    let manifest = fs::read_to_string(dir().join("manifest.json")).unwrap();
    fs::remove_file(tmp.join("manifest.json")).unwrap();
    fs::write(
        tmp.join("manifest.json"),
        manifest.replacen("\"ldem_16.lbl\"", "\"../ldem_16.lbl\"", 1),
    )
    .unwrap();
    assert!(matches!(
        Package::open(&tmp, moon()),
        Err(PackageError::Manifest(_))
    ));
    fs::remove_file(tmp.join("manifest.json")).unwrap();
    fs::write(
        tmp.join("manifest.json"),
        manifest.replacen("\"stewie-package-v1\"", "\"stewie-package-v0\"", 1),
    )
    .unwrap();
    assert!(
        matches!(Package::open(&tmp, moon()), Err(PackageError::Manifest(m)) if m.contains("format")),
        "another manifest format is refused"
    );
    fs::remove_dir_all(&tmp).unwrap();
}

#[test]
fn every_point_on_the_moon_resolves_to_a_named_tier() {
    let p = package();
    let (t0, t1) = mid_span(&p);
    let mut by_tier = std::collections::BTreeMap::<String, usize>::new();
    for at in points() {
        let c = p
            .guard(at, t0, t1, 1e9)
            .unwrap_or_else(|e| panic!("{at:?}: {e}"));
        *by_tier.entry(c.source.id.clone()).or_default() += 1;
        // the manifest's bands are truthful: inside a layer's band, that layer or a higher-priority one answers
        for l in &p.manifest().layers {
            let in_band = matches!((l.lat_min_deg, l.lat_max_deg), (Some(a), Some(b)) if (a..=b).contains(&at.lat_deg));
            if in_band {
                assert!(
                    u64::from(c.source.priority) <= l.priority.get(),
                    "{at:?} is in {}'s band but {} answered",
                    l.id.as_str(),
                    c.source.id
                );
            }
        }
    }
    assert_eq!(
        by_tier.len(),
        4,
        "every tier answers somewhere: {by_tier:?}"
    );
}

#[test]
fn any_time_outside_the_ephemeris_span_cannot_be_assessed() {
    let p = package();
    let (s, e) = p.ephemeris().span_tdb();
    let at = LatLon {
        lat_deg: -89.0,
        lon_deg: 0.0,
    };
    let outside = |t0, t1| {
        matches!(
            p.guard(at, t0, t1, 1e9),
            Err(CannotAssess::OutsideEphemeris { .. })
        )
    };
    assert!(p.guard(at, s, s, 1e9).is_ok());
    assert!(p.guard(at, s, e - 1.0, 1e9).is_ok());
    assert!(outside(s - 1.0, s));
    assert!(outside(e, e), "the span is half-open");
    assert!(outside(e - 10.0, e + 10.0), "no partial answer");
    assert!(outside(s - 86_400.0, e + 86_400.0));
    let mut r = Rng(7);
    for _ in 0..10_000 {
        let span = e - s;
        let t0 = s - span + 3.0 * span * r.unit();
        let t1 = t0 + span * r.unit();
        let inside = t0 >= s && t1 < e;
        assert_eq!(p.guard(at, t0, t1, 1e9).is_ok(), inside, "{t0}..{t1}");
        if !inside {
            assert!(outside(t0, t1));
        }
    }
}

#[test]
fn a_task_needing_finer_terrain_than_answers_here_cannot_be_assessed() {
    let p = package();
    let (t0, t1) = mid_span(&p);
    for at in points() {
        let res = p.guard(at, t0, t1, 1e9).unwrap().source.resolution_m;
        assert!(p.guard(at, t0, t1, res).is_ok(), "{at:?}");
        match p.guard(at, t0, t1, 0.5 * res) {
            Err(CannotAssess::TooCoarse {
                resolution_m,
                required_m,
                ..
            }) => assert!(resolution_m > required_m),
            other => panic!("{at:?}: {other:?}"),
        }
    }
    // 10 km off the south pole the 40 m tier answers; at 80S only the 240 m tier does
    let near = LatLon {
        lat_deg: -89.7,
        lon_deg: 30.0,
    };
    assert!(p.guard(near, t0, t1, 40.0).is_ok());
    let at80 = LatLon {
        lat_deg: -80.0,
        lon_deg: 30.0,
    };
    assert!(matches!(
        p.guard(at80, t0, t1, 40.0),
        Err(CannotAssess::TooCoarse { source, .. }) if source == "ldem_75s_240m"
    ));
}

#[test]
fn malformed_requests_are_refused_not_answered() {
    let p = package();
    let (t0, t1) = mid_span(&p);
    let at = LatLon {
        lat_deg: 0.0,
        lon_deg: 0.0,
    };
    for (a, b, r) in [
        (t1, t0, 1e9),
        (f64::NAN, t1, 1e9),
        (t0, t1, 0.0),
        (t0, t1, -5.0),
    ] {
        assert!(matches!(
            p.guard(at, a, b, r),
            Err(CannotAssess::InvalidRequest(_))
        ));
    }
    let off = LatLon {
        lat_deg: 91.0,
        lon_deg: 0.0,
    };
    assert!(matches!(
        p.guard(off, t0, t1, 1e9),
        Err(CannotAssess::InvalidRequest(_))
    ));
}
