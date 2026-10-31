//! R10: the WASM build reproduces the native golden scenario within 1e-9 (run with
//! `wasm-pack test --node crates/stewie-wasm`). Inputs are the same real files, embedded at build time.
#![cfg(target_arch = "wasm32")]

use stewie_wasm::scenario;
use wasm_bindgen_test::wasm_bindgen_test;

#[wasm_bindgen_test]
fn wasm_matches_native_golden_within_r10() {
    let golden: serde_json::Value =
        serde_json::from_str(include_str!("../golden/scenario.json")).unwrap();
    let inputs = scenario::Inputs::embedded();
    let now = serde_json::to_value(scenario::run(&inputs).unwrap()).unwrap();
    let diff = scenario::max_abs_diff(&golden, &now);
    assert!(diff <= 1e-9, "native vs wasm max difference {diff}");
}
