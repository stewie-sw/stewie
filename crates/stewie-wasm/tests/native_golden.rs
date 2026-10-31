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
