//! The loader must accept the real committed fixture, and refuse a tampered payload or a fixture whose
//! real source file has changed since it was generated. Tamper cases copy the real fixture into a temp
//! directory and mutate it there (labelled synthetic mutations).

use std::fs;
use std::path::PathBuf;

use stewie_oracle::{Error, load, load_from};

fn temp_copy(tag: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("stewie-oracle-{tag}-{}", std::process::id()));
    let _ = fs::remove_dir_all(&dir);
    fs::create_dir_all(&dir).unwrap();
    let src = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("fixtures");
    for f in ["dem_samples.payload.json", "dem_samples.meta.json"] {
        fs::copy(src.join(f), dir.join(f)).unwrap();
    }
    dir
}

#[test]
fn real_dem_fixture_loads_and_its_sources_are_current() {
    let fx = load("dem_samples").unwrap();
    assert_eq!(fx.name, "dem_samples");
    let bundles = fx.payload["bundles"].as_array().unwrap();
    assert_eq!(bundles.len(), 10);
    assert!(
        bundles
            .iter()
            .all(|b| b["cells"].as_array().unwrap().len() == 16)
    );
}

#[test]
fn tampered_payload_is_refused() {
    let dir = temp_copy("tamper");
    let p = dir.join("dem_samples.payload.json");
    let text = fs::read_to_string(&p)
        .unwrap()
        .replacen("\"row\": 1", "\"row\": 2", 1);
    fs::write(&p, text).unwrap();
    assert!(matches!(
        load_from(&dir, "dem_samples"),
        Err(Error::PayloadHash { .. })
    ));
}

#[test]
fn stale_source_is_refused() {
    let dir = temp_copy("stale");
    let m = dir.join("dem_samples.meta.json");
    let mut meta: serde_json::Value =
        serde_json::from_str(&fs::read_to_string(&m).unwrap()).unwrap();
    let first = meta["sources"]
        .as_object()
        .unwrap()
        .keys()
        .next()
        .unwrap()
        .clone();
    meta["sources"][&first] = serde_json::Value::from("0".repeat(64));
    fs::write(&m, serde_json::to_string_pretty(&meta).unwrap()).unwrap();
    assert!(matches!(
        load_from(&dir, "dem_samples"),
        Err(Error::StaleSource { .. })
    ));
}

#[test]
fn missing_fixture_is_an_error_not_a_default() {
    assert!(matches!(load("no_such_fixture"), Err(Error::Io { .. })));
}
