//! The mission-link model against the Python's (`oracle/build_fixtures.py::telemetry_link_cases`): every packaged
//! profile, call by call (delivered at the same instant, or not at all), and the final counters.

use stewie_server::telemetry_link::{TelemetryLink, load_profile};

#[test]
fn each_profile_delivers_as_the_pythons() {
    let fx = stewie_oracle::load("telemetry_link_cases").unwrap().payload;
    for c in fx["cases"].as_array().unwrap() {
        let name = c["profile"].as_str().unwrap();
        let mut link = TelemetryLink::new(load_profile(name).unwrap(), 0);
        for (k, (call, want)) in c["calls"]
            .as_array()
            .unwrap()
            .iter()
            .zip(c["visible_at"].as_array().unwrap())
            .enumerate()
        {
            let got = link.deliver_at(call[0].as_i64().unwrap(), call[1].as_f64().unwrap(), "");
            assert_eq!(
                got.map(f64::to_bits),
                want.as_f64().map(f64::to_bits),
                "{name} call {k}"
            );
        }
        assert_eq!(link.stats(), c["stats"], "{name}");
    }
}

#[test]
fn only_the_packaged_profiles_load() {
    // D-R173: the Python opens any profiles/<name>.json path it is given; this server serves the packaged three
    assert!(load_profile("../../../etc/passwd").is_err());
    assert_eq!(
        load_profile("ideal").unwrap().drop_prob.to_bits(),
        0.0_f64.to_bits()
    );
}
