//! Contract tests over REAL repository data: every committed DEM bundle and the exported body/site
//! registries must validate against the JSON Schemas and deserialize into the generated Rust types.
//! Malformed copies (labelled synthetic mutations of real files) must be rejected by both.

use std::fs;
use std::path::{Path, PathBuf};

use serde_json::Value;
use stewie_contracts::{
    astronaut_profile, body, dem_bundle, package_manifest, rover_profile, site, soil_baseline,
};

fn crate_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

fn repo() -> PathBuf {
    crate_dir().join("../..")
}

fn load(path: &Path) -> Value {
    serde_json::from_str(&fs::read_to_string(path).unwrap()).unwrap()
}

fn validator(schema: &str) -> jsonschema::Validator {
    jsonschema::validator_for(&load(&crate_dir().join("schema").join(schema))).unwrap()
}

fn bundle_metadata() -> Vec<PathBuf> {
    let mut out = Vec::new();
    for dir in [repo().join("samples"), repo().join("samples/lunar_dem")] {
        for e in fs::read_dir(dir).unwrap().flatten() {
            let m = e.path().join("metadata.json");
            if m.is_file() {
                out.push(m);
            }
        }
    }
    out.sort();
    out
}

#[test]
fn every_real_bundle_validates_and_deserializes() {
    let v = validator("dem_bundle.schema.json");
    let paths = bundle_metadata();
    assert_eq!(paths.len(), 23, "the repo carries 23 real bundles");
    for p in paths {
        let doc = load(&p);
        let errs: Vec<String> = v.iter_errors(&doc).map(|e| e.to_string()).collect();
        assert!(errs.is_empty(), "{}: {errs:?}", p.display());
        let b: dem_bundle::DemBundle = serde_json::from_value(doc).unwrap();
        dem_bundle::check(&b).unwrap_or_else(|e| panic!("{}: {e}", p.display()));
    }
}

#[test]
fn bundle_missing_grid_or_with_unknown_key_is_rejected() {
    let v = validator("dem_bundle.schema.json");
    let real = load(&repo().join("samples/lunar_dem/haworth_10km_5m/metadata.json"));
    // synthetic mutation 1: drop a required field
    let mut no_grid = real.clone();
    no_grid.as_object_mut().unwrap().remove("grid");
    assert!(!v.is_valid(&no_grid));
    assert!(serde_json::from_value::<dem_bundle::DemBundle>(no_grid).is_err());
    // synthetic mutation 2: an undeclared key
    let mut extra = real.clone();
    extra
        .as_object_mut()
        .unwrap()
        .insert("surprise".into(), Value::Bool(true));
    assert!(!v.is_valid(&extra));
    assert!(serde_json::from_value::<dem_bundle::DemBundle>(extra).is_err());
}

#[test]
fn bundle_semantic_check_rejects_inverted_bounds_and_grid_mismatch() {
    let real = load(&repo().join("samples/lunar_dem/haworth_10km_5m/metadata.json"));
    // synthetic mutation: swap x0/x1
    let mut swapped = real.clone();
    let wb = swapped["world_bounds_m"].as_object_mut().unwrap();
    let (x0, x1) = (wb["x0"].clone(), wb["x1"].clone());
    wb.insert("x0".into(), x1);
    wb.insert("x1".into(), x0);
    let b: dem_bundle::DemBundle = serde_json::from_value(swapped).unwrap();
    assert!(dem_bundle::check(&b).is_err());
    // synthetic mutation: grid width that disagrees with the bounds
    let mut wide = real;
    wide["grid"]["width"] = Value::from(1999);
    let b: dem_bundle::DemBundle = serde_json::from_value(wide).unwrap();
    assert!(dem_bundle::check(&b).is_err());
}

#[test]
fn body_registry_validates_and_moon_constants_are_the_sourced_values() {
    let doc = load(&crate_dir().join("fixtures/bodies.json"));
    assert!(validator("body.schema.json").is_valid(&doc));
    let reg: body::BodyRegistry = serde_json::from_value(doc).unwrap();
    let moon = &reg["moon"];
    assert!((moon.g - 1.62).abs() < 1e-12);
    assert_eq!(moon.ellipsoid_radius_m, Some(1_737_400.0));
    let k = moon.bekker.as_ref().unwrap();
    assert_eq!((k.k_c, k.k_phi, k.n), (1400.0, 820_000.0, 1.0));
}

#[test]
fn body_with_nonpositive_gravity_is_rejected() {
    let mut doc = load(&crate_dir().join("fixtures/bodies.json"));
    doc["moon"]["g"] = Value::from(0.0); // synthetic mutation
    assert!(!validator("body.schema.json").is_valid(&doc));
}

#[test]
fn site_catalog_validates_and_every_named_bundle_exists() {
    let doc = load(&crate_dir().join("fixtures/sites.json"));
    assert!(validator("site.schema.json").is_valid(&doc));
    let cat: site::SiteCatalog = serde_json::from_value(doc).unwrap();
    assert!(!cat.is_empty());
    for (name, s) in cat.iter() {
        if let Some(b) = &s.bundle {
            let m = repo()
                .join("samples/lunar_dem")
                .join(b)
                .join("metadata.json");
            assert!(m.is_file(), "site {name} names missing bundle {b}");
        }
    }
}

#[test]
fn soil_baseline_validates_and_an_untagged_value_is_rejected() {
    let doc = load(&crate_dir().join("fixtures/soil_baseline.json"));
    let v = validator("soil_baseline.schema.json");
    assert!(v.is_valid(&doc));
    let b: soil_baseline::SoilBaseline = serde_json::from_value(doc.clone()).unwrap();
    assert!((b.k_shear_m.value - 0.018).abs() < 1e-15);
    let mut untagged = doc; // synthetic mutation of the real file
    untagged["slip_c1"]["tag"] = Value::from("GUESS");
    assert!(!v.is_valid(&untagged));
    assert!(serde_json::from_value::<soil_baseline::SoilBaseline>(untagged).is_err());
}

#[test]
fn committed_package_manifest_validates_and_an_escaping_path_is_rejected() {
    let doc = load(&repo().join("pipeline/packages/lola_base.json"));
    let v = validator("package_manifest.schema.json");
    assert!(v.is_valid(&doc));
    serde_json::from_value::<package_manifest::PackageManifest>(doc.clone()).unwrap();
    let mut escape = doc; // synthetic mutation of the real manifest
    escape["layers"][0]["image"]["path"] = Value::from("../ldem_16.img");
    assert!(!v.is_valid(&escape));
    assert!(serde_json::from_value::<package_manifest::PackageManifest>(escape).is_err());
}

#[test]
fn rover_profile_validates_and_a_profile_missing_any_field_is_rejected() {
    let doc = load(&crate_dir().join("fixtures/rover_ipex.json"));
    let v = validator("rover_profile.schema.json");
    assert!(v.is_valid(&doc));
    let p: rover_profile::RoverProfile = serde_json::from_value(doc.clone()).unwrap();
    assert!(
        (p.wheel_radius_m.value - 0.1525).abs() < 1e-12,
        "published 30.5 cm wheel"
    );
    let keys: Vec<String> = doc.as_object().unwrap().keys().cloned().collect();
    assert!(keys.len() > 20);
    for k in keys {
        let mut missing = doc.clone(); // synthetic mutation of the real profile
        missing.as_object_mut().unwrap().remove(&k);
        assert!(!v.is_valid(&missing), "{k} is required");
        assert!(
            serde_json::from_value::<rover_profile::RoverProfile>(missing).is_err(),
            "{k}"
        );
    }
    let mut untagged = doc;
    untagged["cg_height_m"]["tag"] = Value::from("GUESS");
    assert!(!v.is_valid(&untagged));
}

#[test]
fn astronaut_profile_carries_its_cited_values_and_rejects_a_missing_or_untagged_field() {
    let doc = load(&crate_dir().join("fixtures/eva_crew.json"));
    let v = validator("astronaut_profile.schema.json");
    assert!(v.is_valid(&doc));
    let p: astronaut_profile::AstronautProfile = serde_json::from_value(doc.clone()).unwrap();
    astronaut_profile::check(&p).unwrap();
    // the SI values are the printed figures times exact factors (D-R78, EVA_SOURCES.md)
    assert!(
        (p.level_walk_speed_ms.value - 3.9 * 0.447_04).abs() < 1e-12,
        "3.9 mph"
    );
    assert!(
        (p.metabolic_w.all_activities.value - 980.0 / 3.6).abs() < 1e-9,
        "980 kJ/hr"
    );
    assert!(
        (p.level_walk_o2_kg_per_hr.value - 0.4 * 0.453_592_37).abs() < 1e-12,
        "0.4 lb/hr"
    );
    let last = p.grade_vo2.last().unwrap();
    assert!(
        (last.grade_pct - 30.0).abs() < 1e-12 && (last.vo2_ml_min_kg.value - 21.5).abs() < 1e-12
    );
    let keys: Vec<String> = doc.as_object().unwrap().keys().cloned().collect();
    assert_eq!(keys.len(), 11);
    for k in keys {
        let mut missing = doc.clone(); // synthetic mutation of the real profile
        missing.as_object_mut().unwrap().remove(&k);
        assert!(!v.is_valid(&missing), "{k} is required");
    }
    let mut guessed = doc.clone();
    guessed["level_walk_speed_ms"]["tag"] = Value::from("ASSUMPTION");
    assert!(!v.is_valid(&guessed), "only SOURCED or FIGURE_READ");
    let mut unbounded = doc.clone();
    unbounded["grade_vo2"][1]["vo2_ml_min_kg"]
        .as_object_mut()
        .unwrap()
        .remove("uncertainty");
    let p: astronaut_profile::AstronautProfile = serde_json::from_value(unbounded).unwrap();
    assert!(
        astronaut_profile::check(&p).is_err(),
        "FIGURE_READ without uncertainty"
    );
    let mut unordered = doc;
    unordered["grade_vo2"][2]["grade_pct"] = Value::from(5.0);
    let p: astronaut_profile::AstronautProfile = serde_json::from_value(unordered).unwrap();
    assert!(
        astronaut_profile::check(&p).is_err(),
        "grades must increase"
    );
}

/// A source line that compiles a reserve number in (comments and string literals excluded).
fn compiles_a_reserve(line: &str) -> bool {
    let l = line.to_lowercase();
    // a numeric literal starts with a digit not glued to an identifier (so `f64` is not a number)
    let b = l.as_bytes();
    let literal = (0..b.len()).any(|i| {
        b[i].is_ascii_digit() && (i == 0 || !(b[i - 1].is_ascii_alphanumeric() || b[i - 1] == b'_'))
    });
    l.contains("reserve") && literal && !l.trim_start().starts_with("//") && !l.contains('"')
}

/// RW-30: battery reserves come only from mission configuration; no crate compiles one in.
#[test]
fn no_reserve_default_is_compiled_into_any_crate() {
    // vacuity guard: the predicate does catch the pattern it exists for (synthetic lines, labelled)
    assert!(compiles_a_reserve("    let battery_reserve_frac = 0.10;"));
    assert!(
        !compiles_a_reserve("    let terms = |reserve: Input<f64>| {"),
        "a type name is not a number"
    );
    assert!(!compiles_a_reserve("    // reserve 10% before recharge"));
    let mut hits = Vec::new();
    let mut stack = vec![repo().join("crates")];
    while let Some(dir) = stack.pop() {
        for e in fs::read_dir(&dir).unwrap().flatten() {
            let p = e.path();
            if p.is_dir() {
                stack.push(p);
            } else if p.extension().is_some_and(|x| x == "rs") {
                for (n, line) in fs::read_to_string(&p).unwrap().lines().enumerate() {
                    if compiles_a_reserve(line) {
                        hits.push(format!("{}:{}", p.display(), n + 1));
                    }
                }
            }
        }
    }
    assert!(hits.is_empty(), "reserve literals in code: {hits:?}");
}
