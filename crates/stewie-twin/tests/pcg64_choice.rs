//! numpy's `Generator.choice(n, 3, replace=False)`, draw for draw over 200 consecutive calls per stream (the
//! 32-bit spare carried between calls), against `CPython` numpy 2.4.6 references recorded in `choice_cases`.

#[test]
fn choice_matches_numpy() {
    let fx = stewie_oracle::load("choice_cases").unwrap().payload;
    for case in fx["cases"].as_array().unwrap() {
        let (seed, n) = (case["seed"].as_u64().unwrap(), case["n"].as_u64().unwrap());
        let mut g = stewie_twin::pcg64::Pcg64::new(u128::from(seed));
        for (k, want) in case["draws"].as_array().unwrap().iter().enumerate() {
            let want: Vec<usize> = want
                .as_array()
                .unwrap()
                .iter()
                .map(|v| usize::try_from(v.as_u64().unwrap()).unwrap())
                .collect();
            assert_eq!(
                g.choice_without_replacement(usize::try_from(n).unwrap(), 3),
                want,
                "seed {seed} n {n} call {k}"
            );
        }
    }
}
