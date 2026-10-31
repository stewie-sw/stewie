//! The committed golden scenario (written natively by `cargo run -p xtask -- wasm-golden`) must still match
//! a native run: it is the reference the WASM build is held to (R10).
#![cfg(not(target_arch = "wasm32"))]

use stewie_wasm::scenario;

#[test]
fn native_run_reproduces_the_committed_golden() {
    let golden: serde_json::Value =
        serde_json::from_str(include_str!("../golden/scenario.json")).unwrap();
    let now = scenario::run(&scenario::Inputs::from_repo().unwrap()).unwrap();
    let now = serde_json::to_value(now).unwrap();
    let diff = scenario::max_abs_diff(&golden, &now);
    assert!(
        diff <= 0.0,
        "native output drifted from the golden by {diff}"
    );
}

#[test]
fn engine_refuses_an_unknown_body_and_a_bad_instant() {
    let e = scenario::Inputs::from_repo().unwrap().engine().unwrap();
    assert!(
        e.az_el("MARS", "2027-01-01T00:00:00Z", -86.0, -25.0, 1.5)
            .is_err()
    );
    assert!(
        e.az_el("SUN", "2027-02-30T00:00:00Z", -86.0, -25.0, 1.5)
            .is_err()
    );
}

#[test]
fn horizon_json_round_trips_and_rejects_ragged_arrays() {
    let e = scenario::Inputs::from_repo().unwrap().engine().unwrap();
    let h = e
        .horizon(
            -86.318_398_660_548_35,
            -25.414_052_740_154_946,
            72,
            20_000.0,
            50.0,
            1.5,
        )
        .unwrap();
    let json = serde_json::json!({"az_deg": h.az_deg, "elev_deg": h.elev_deg, "reach_m": h.reach_m, "complete": h.complete, "sources": h.sources}).to_string();
    assert_eq!(stewie_wasm::horizon_from_json(&json).unwrap(), h);
    let ragged = json.replacen("\"reach_m\":[", "\"reach_m\":[1.0,", 1);
    assert!(stewie_wasm::horizon_from_json(&ragged).is_err());
}

/// The device-package stack the browser now uses (D-R47): the 5 m tile, the 40 m site crop, the 240 m polar
/// tier and `LDEM_16`. The horizon draws on every tier and completes every ray near the pole.
#[test]
fn the_device_package_stack_loads_and_completes_the_horizon() {
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let pkg = root.join(".cache/package/south_polar_sites");
    let text = |p: &std::path::Path| std::fs::read_to_string(p).unwrap();
    let bytes = |p: &std::path::Path| std::fs::read(p).unwrap();
    let mut e = stewie_wasm::Engine::new(&text(
        &root.join("crates/stewie-contracts/fixtures/bodies.json"),
    ))
    .unwrap();
    let tile = root.join("samples/lunar_dem/shackleton_rim_10km_5m");
    e.add_tile(
        0,
        "shackleton_rim_10km_5m",
        &text(&tile.join("metadata.json")),
        &bytes(&tile.join("heightmap.rf32")),
    )
    .unwrap();
    for (prio, id) in [(1, "ldem_85s_40m_shackleton_rim"), (2, "ldem_75s_240m")] {
        e.add_polar(
            prio,
            id,
            &text(&pkg.join(format!("{id}.lbl"))),
            &bytes(&pkg.join(format!("{id}.img"))),
        )
        .unwrap();
    }
    e.add_global(
        9,
        "ldem_16",
        &text(&pkg.join("ldem_16.lbl")),
        &bytes(&pkg.join("ldem_16.img")),
    )
    .unwrap();
    assert_eq!(
        e.stack_signature(),
        "regional@5.0m > regional@40.0m > regional@240.0m > ldem_16@1895.2m"
    );
    let h = e
        .horizon(-89.823, 158.213, 360, 200_000.0, 50.0, 1.5)
        .unwrap();
    assert!(
        h.complete.iter().all(|&c| c),
        "no ray stops at the pole hole"
    );
    let sources: Vec<&str> = h.sources.iter().map(String::as_str).collect();
    for id in [
        "shackleton_rim_10km_5m",
        "ldem_85s_40m_shackleton_rim",
        "ldem_75s_240m",
    ] {
        assert!(sources.contains(&id), "{id} used: {sources:?}");
    }
}
