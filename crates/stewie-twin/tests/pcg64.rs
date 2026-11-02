//! numpy's default generator against numpy (`oracle/build_fixtures.py::numpy_rng_cases`): every raw output and
//! every `random()` double, bit for bit.

use stewie_twin::pcg64::Pcg64;

#[test]
fn default_rng_draws_as_numpys() {
    let fx = stewie_oracle::load("numpy_rng_cases").unwrap().payload;
    let cases = fx["cases"].as_array().unwrap();
    assert!(cases.len() >= 6, "vacuity: single- and multi-word seeds");
    for c in cases {
        let seed: u128 = c["seed"].as_str().unwrap().parse().unwrap();
        let mut g = Pcg64::new(seed);
        for (k, r) in c["raw"].as_array().unwrap().iter().enumerate() {
            let want: u64 = r.as_str().unwrap().parse().unwrap();
            assert_eq!(g.next_u64(), want, "seed {seed} raw {k}");
        }
        let mut g = Pcg64::new(seed);
        for (k, r) in c["random"].as_array().unwrap().iter().enumerate() {
            assert_eq!(
                g.random().to_bits(),
                r.as_f64().unwrap().to_bits(),
                "seed {seed} random {k}"
            );
        }
    }
}
