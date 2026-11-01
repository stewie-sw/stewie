//! Source descriptors and LOLA alignment at the package boundary (RW-60c, navigator N31/N32, D-R105), on the REAL
//! packages: both open, their alignment records regenerate exactly from the pinned LOLA extracts, and a package is
//! refused when a layer's descriptor is incomplete or its alignment is missing, failed, carried under a weakened
//! policy or inherited from the wrong parent. Each refusal case edits a copy of the real manifest or record
//! (SYNTHETIC edits, labelled); the data files are the real ones, linked.

use std::path::{Path, PathBuf};

use lunar_frames::Sphere;
use serde_json::{Value, json};
use stewie_package::alignment::{ALIGNMENT_FILE, align_package};
use stewie_package::{Package, PackageError};

fn moon() -> Sphere {
    let reg: Value =
        serde_json::from_str(include_str!("../../stewie-contracts/fixtures/bodies.json")).unwrap();
    Sphere::new(reg["moon"]["ellipsoid_radius_m"].as_f64().unwrap()).unwrap()
}

fn root() -> PathBuf {
    stewie_oracle::repo_root()
}

fn read(path: &Path) -> Value {
    serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap()
}

/// A scratch copy of the package `name`: every data file linked, the manifest and record as given.
fn copy(name: &str, tag: &str, manifest: &Value, record: &Value) -> PathBuf {
    let src = root().join(".cache/package").join(name);
    let dir = std::env::temp_dir().join(format!(
        "stewie-descriptor-{}-{name}-{tag}",
        std::process::id()
    ));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    for e in std::fs::read_dir(&src).unwrap().flatten() {
        let f = e.file_name();
        let n = f.to_string_lossy();
        if n != "manifest.json" && n != ALIGNMENT_FILE && e.path().is_file() {
            std::os::unix::fs::symlink(e.path(), dir.join(&f)).unwrap();
        }
    }
    std::fs::write(
        dir.join("manifest.json"),
        serde_json::to_string(manifest).unwrap(),
    )
    .unwrap();
    std::fs::write(
        dir.join(ALIGNMENT_FILE),
        serde_json::to_string(record).unwrap(),
    )
    .unwrap();
    dir
}

#[track_caller]
fn refused(name: &str, tag: &str, manifest: &Value, record: &Value, want: &str) {
    let dir = copy(name, tag, manifest, record);
    let err = Package::open(&dir, moon())
        .err()
        .unwrap_or_else(|| panic!("{tag}: opened"));
    let msg = err.to_string();
    assert!(msg.contains(want), "{tag}: {msg}");
    if tag.starts_with("descriptor") {
        assert!(matches!(err, PackageError::Manifest(_)), "{tag}: {err:?}");
    } else {
        assert!(matches!(err, PackageError::Alignment(_)), "{tag}: {err:?}");
    }
    std::fs::remove_dir_all(&dir).unwrap();
}

fn boxes() -> Vec<(String, PathBuf)> {
    let tracks = read(&root().join("pipeline/lola_tracks.json"));
    tracks["boxes"]
        .as_object()
        .unwrap()
        .keys()
        .map(|k| {
            (
                k.clone(),
                root().join(".cache/lola").join(format!("{k}.csv")),
            )
        })
        .collect()
}

#[test]
fn the_real_packages_open_and_their_records_regenerate() {
    let base_dir = root().join(".cache/package/lola_base");
    let sites_dir = root().join(".cache/package/south_polar_sites");
    Package::open(&base_dir, moon()).unwrap();
    Package::open(&sites_dir, moon()).unwrap();
    let base = align_package(&base_dir, moon(), &boxes(), None).unwrap();
    assert_eq!(
        base,
        read(&root().join("pipeline/packages/lola_base.alignment.json"))
    );
    let sites = align_package(&sites_dir, moon(), &boxes(), Some(&base)).unwrap();
    assert_eq!(
        sites,
        read(&root().join("pipeline/packages/south_polar_sites.alignment.json"))
    );
    let manifest = read(&base_dir.join("manifest.json"));
    for l in manifest["layers"].as_array().unwrap() {
        for k in ["provider", "crs", "role", "quality"] {
            assert!(l.get(k).is_some(), "{} carries {k}", l["id"]);
        }
    }
}

#[test]
fn an_incomplete_or_unaligned_source_is_refused() {
    let base_dir = root().join(".cache/package/lola_base");
    let manifest = read(&base_dir.join("manifest.json"));
    let record = read(&base_dir.join(ALIGNMENT_FILE));
    // N31: every descriptor field is required
    for field in ["provider", "crs", "role", "quality"] {
        let mut m = manifest.clone();
        m["layers"][0].as_object_mut().unwrap().remove(field);
        refused(
            "lola_base",
            &format!("descriptor-{field}"),
            &m,
            &record,
            field,
        );
    }
    // N32: a layer with no alignment
    let mut r = record.clone();
    r["layers"].as_object_mut().unwrap().remove("ldem_75s_240m");
    refused(
        "lola_base",
        "missing",
        &manifest,
        &r,
        "ldem_75s_240m: no LOLA alignment",
    );
    // a residual over the threshold, though the record says admitted
    let mut r = record.clone();
    r["layers"]["ldem_85s_40m"]["residual_rms_m"] = json!(12.5);
    refused("lola_base", "residual", &manifest, &r, "ldem_85s_40m fails");
    // shifted two pixels
    let mut r = record.clone();
    r["layers"]["ldem_85s_40m"]["shift_east_m"] = json!(80.0);
    refused("lola_base", "shift", &manifest, &r, "ldem_85s_40m fails");
    // a record carried under a weaker policy than this build's
    let mut r = record.clone();
    r["policy"]["rms_per_resolution"] = json!(0.5);
    refused("lola_base", "policy", &manifest, &r, "policy");
}

#[test]
fn a_crop_inherits_only_its_own_parents_fit() {
    let sites_dir = root().join(".cache/package/south_polar_sites");
    let manifest = read(&sites_dir.join("manifest.json"));
    let record = read(&sites_dir.join(ALIGNMENT_FILE));
    let crop = manifest["layers"]
        .as_array()
        .unwrap()
        .iter()
        .find(|l| l.get("crop_of").is_some())
        .unwrap()["id"]
        .as_str()
        .unwrap()
        .to_owned();
    let mut r = record.clone();
    r["layers"][&crop] = json!({"inherited_from": "ldem_75s_240m"});
    refused(
        "south_polar_sites",
        "wrong-parent",
        &manifest,
        &r,
        "is not a crop of it",
    );
    let mut r = record.clone();
    r["layers"].as_object_mut().unwrap().remove("ldem_85s_40m");
    refused(
        "south_polar_sites",
        "no-parent-fit",
        &manifest,
        &r,
        "has no direct alignment",
    );
}
