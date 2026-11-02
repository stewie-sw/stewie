//! NV-11: the plan-IR lowering against the Python's (`oracle/build_fixtures.py::plan_lowering_cases`: the sample
//! missions' plan IRs and a SYNTHETIC IR covering every op, posture route and replan event), message for message.

use stewie_plan::lowering::lower_plan_ir;

#[test]
fn the_plan_ir_lowers_as_the_pythons() {
    let fx = stewie_oracle::load("plan_lowering_cases").unwrap().payload;
    let cases = fx["cases"].as_array().unwrap();
    assert!(
        cases.len() >= 4,
        "vacuity: the sample missions and the coverage IR"
    );
    for c in cases {
        assert_eq!(
            lower_plan_ir(&c["ir"], "map"),
            c["lowered"],
            "{}",
            c["name"]
        );
    }
}
