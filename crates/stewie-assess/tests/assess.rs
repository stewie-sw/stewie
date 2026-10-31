//! The assessment engine: the navigator's table cases (the Station Bravo example among them), the R7
//! property test over seeded random templates (SYNTHETIC inputs, labelled), and the R8 contract: every
//! result's evidence validates against `assessment.schema.json`.

use lunar_intervals::{Verdict, Window};
use serde_json::Value;
use stewie_assess::{Check, Eval, Input, Kind, Sense, State, Template, assess};

const NOW: f64 = 1.0e9;

fn known(v: f64) -> Input<f64> {
    Input::Known {
        value: v,
        version: "test-v1".into(),
        as_of_tdb: NOW,
        max_age_s: None,
        simulated: false,
    }
}

fn schema() -> jsonschema::Validator {
    let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../stewie-contracts/schema/assessment.schema.json");
    jsonschema::validator_for(
        &serde_json::from_str::<Value>(&std::fs::read_to_string(path).unwrap()).unwrap(),
    )
    .unwrap()
}

fn win(a: f64, b: f64, v: Verdict) -> Window {
    Window {
        start_tdb: a,
        end_tdb: b,
        verdict: v,
    }
}

fn cover(ws: Vec<Window>, dur_min: f64, buf_min: f64) -> Eval {
    Eval::WindowCover {
        windows: Input::Known {
            value: ws,
            version: "eph-de440+ldem".into(),
            as_of_tdb: NOW,
            max_age_s: None,
            simulated: false,
        },
        start_tdb: known(NOW),
        duration_s: known(dur_min * 60.0),
        buffer_s: known(buf_min * 60.0),
    }
}

fn template(checks: Vec<Check>) -> Template {
    Template {
        name: "Station Bravo sampling".into(),
        rule_revision: "rules-r1".into(),
        checks,
        not_modeled: vec![
            "radio link".into(),
            "return".into(),
            "life support".into(),
            "thermal".into(),
        ],
        assumptions: vec!["antenna 1.5 m".into()],
    }
}

fn hard(group: &str, eval: Eval) -> Check {
    Check {
        group: group.into(),
        kind: Kind::Hard,
        eval,
    }
}

#[test]
fn the_station_bravo_example_violates_with_thirteen_usable_minutes() {
    // shadow arrives 18 min after the start; buffer 5 min; a 20 min task
    let ws = vec![
        win(NOW - 3600.0, NOW + 18.0 * 60.0, Verdict::Lit),
        win(NOW + 18.0 * 60.0, NOW + 7200.0, Verdict::Shadow),
    ];
    let earth = vec![win(NOW - 3600.0, NOW + 7200.0, Verdict::Lit)];
    let a = assess(
        &template(vec![
            hard("illumination", cover(ws.clone(), 20.0, 5.0)),
            hard("Earth visibility", cover(earth.clone(), 20.0, 0.0)),
        ]),
        NOW,
    );
    assert_eq!(a.state, State::Violates);
    assert_eq!(a.checks[a.binding.unwrap()].group, "illumination");
    assert!(
        (a.checks[0].margin.unwrap() - (-7.0 * 60.0)).abs() < 1e-9,
        "13 usable minutes against a 20 minute task"
    );
    assert!(a.checks[0].detail.contains("780 s meet the rule"));
    assert_eq!(a.checks[1].state, State::Meets);
    assert!(
        a.checks[1]
            .detail
            .starts_with("visible through the computed windows"),
        "{}",
        a.checks[1].detail
    );
    assert_eq!(
        a.not_assessed,
        ["radio link", "return", "life support", "thermal"]
    );
    assert!(schema().is_valid(&a.evidence));
    let short = assess(
        &template(vec![
            hard("illumination", cover(ws, 10.0, 5.0)),
            hard("Earth visibility", cover(earth, 10.0, 0.0)),
        ]),
        NOW,
    );
    assert_eq!(short.state, State::Meets);
    assert_eq!(short.evidence["state"], "meets modeled constraints");
    assert!((short.checks[0].margin.unwrap() - 3.0 * 60.0).abs() < 1e-9);
}

#[test]
fn unknown_or_uncomputed_visibility_cannot_be_assessed() {
    let unknown = vec![
        win(NOW - 60.0, NOW + 300.0, Verdict::Lit),
        win(NOW + 300.0, NOW + 9000.0, Verdict::Unknown),
    ];
    assert_eq!(
        assess(
            &template(vec![hard("illumination", cover(unknown, 20.0, 5.0))]),
            NOW
        )
        .state,
        State::CannotAssess
    );
    let short_range = vec![win(NOW - 60.0, NOW + 600.0, Verdict::Lit)];
    assert_eq!(
        assess(
            &template(vec![hard("illumination", cover(short_range, 20.0, 5.0))]),
            NOW
        )
        .state,
        State::CannotAssess
    );
    let later = vec![win(NOW + 60.0, NOW + 9000.0, Verdict::Lit)];
    assert_eq!(
        assess(
            &template(vec![hard("illumination", cover(later, 20.0, 5.0))]),
            NOW
        )
        .state,
        State::CannotAssess
    );
    let shadow_now = vec![win(NOW - 60.0, NOW + 9000.0, Verdict::Shadow)];
    assert_eq!(
        assess(
            &template(vec![hard("illumination", cover(shadow_now, 20.0, 5.0))]),
            NOW
        )
        .state,
        State::Violates
    );
}

#[test]
fn the_time_budget_needs_every_term_including_the_mission_reserve() {
    let terms = |reserve: Input<f64>| {
        vec![
            ("traverse".to_owned(), known(1800.0)),
            ("task".to_owned(), known(1200.0)),
            ("return".to_owned(), known(1800.0)),
            ("ingress".to_owned(), known(600.0)),
            ("reserve".to_owned(), reserve),
        ]
    };
    let budget = |reserve, avail| {
        hard(
            "traverse timing",
            Eval::Budget {
                terms: terms(reserve),
                available: known(avail),
                unit: "s".into(),
            },
        )
    };
    let ok = assess(&template(vec![budget(known(900.0), 7200.0)]), NOW);
    assert_eq!(ok.state, State::Meets);
    assert!((ok.checks[0].margin.unwrap() - 900.0).abs() < 1e-9);
    assert_eq!(
        assess(&template(vec![budget(known(900.0), 6000.0)]), NOW).state,
        State::Violates
    );
    let no_reserve = assess(
        &template(vec![budget(
            Input::Missing("mission config has no reserve".into()),
            7200.0,
        )]),
        NOW,
    );
    assert_eq!(
        no_reserve.state,
        State::CannotAssess,
        "no reserve default exists anywhere"
    );
    assert!(schema().is_valid(&no_reserve.evidence));
}

#[test]
fn hard_failures_are_never_offset_and_soft_checks_never_decide() {
    let slope = |v: f64, k| Check {
        group: "terrain slope".into(),
        kind: k,
        eval: Eval::Threshold {
            value: known(v),
            limit: known(15.0),
            sense: Sense::AtMost,
            unit: "deg".into(),
        },
    };
    let missing = hard(
        "Earth visibility",
        Eval::Threshold {
            value: Input::Missing("no horizon".into()),
            limit: known(0.0),
            sense: Sense::AtLeast,
            unit: "deg".into(),
        },
    );
    assert_eq!(
        assess(
            &template(vec![
                slope(20.0, Kind::Hard),
                slope(1.0, Kind::Soft),
                missing.clone()
            ]),
            NOW
        )
        .state,
        State::Violates
    );
    assert_eq!(
        assess(
            &template(vec![slope(10.0, Kind::Hard), slope(30.0, Kind::Soft)]),
            NOW
        )
        .state,
        State::Meets
    );
    assert_eq!(
        assess(&template(vec![slope(10.0, Kind::Hard), missing]), NOW).state,
        State::CannotAssess
    );
    let stale = Input::Known {
        value: 5.0,
        version: "v".into(),
        as_of_tdb: NOW - 7200.0,
        max_age_s: Some(3600.0),
        simulated: true,
    };
    let a = assess(
        &template(vec![hard(
            "terrain slope",
            Eval::Threshold {
                value: stale,
                limit: known(15.0),
                sense: Sense::AtMost,
                unit: "deg".into(),
            },
        )]),
        NOW,
    );
    assert_eq!(a.state, State::CannotAssess);
    assert!(a.simulated, "a simulated input raises the SIMULATION label");
    assert_eq!(
        assess(&template(vec![slope(1.0, Kind::Soft)]), NOW).state,
        State::CannotAssess,
        "nothing hard was assessed"
    );
}

/// splitmix64: SYNTHETIC assessment inputs only.
struct Rng(u64);

impl Rng {
    #[allow(clippy::cast_precision_loss)]
    fn unit(&mut self) -> f64 {
        self.0 = self.0.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        (z ^ (z >> 31)) as f64 / u64::MAX as f64
    }
    #[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)]
    fn input(&mut self) -> Input<f64> {
        let v = 100.0 * self.unit();
        match (self.unit() * 5.0) as u32 {
            0 => Input::Missing("synthetic".into()),
            1 => Input::Unmodeled("synthetic".into()),
            2 => Input::Known {
                value: v,
                version: "s".into(),
                as_of_tdb: NOW - 5000.0,
                max_age_s: Some(100.0),
                simulated: true,
            },
            _ => Input::Known {
                value: v,
                version: "s".into(),
                as_of_tdb: NOW,
                max_age_s: Some(100.0),
                simulated: false,
            },
        }
    }
}

#[test]
#[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)]
fn r7_no_missing_stale_or_unmodelled_input_ever_meets_and_r8_evidence_always_validates() {
    let validator = schema();
    let mut rng = Rng(20_261_031);
    let mut seen = [0usize; 3];
    for _ in 0..5000 {
        let count = 1 + (rng.unit() * 6.0) as usize;
        let checks: Vec<Check> = (0..count)
            .map(|i| {
                let kind = if rng.unit() < 0.7 {
                    Kind::Hard
                } else {
                    Kind::Soft
                };
                let eval = if rng.unit() < 0.5 {
                    Eval::Threshold {
                        value: rng.input(),
                        limit: rng.input(),
                        sense: if rng.unit() < 0.5 {
                            Sense::AtMost
                        } else {
                            Sense::AtLeast
                        },
                        unit: "u".into(),
                    }
                } else {
                    Eval::Budget {
                        terms: (0..3).map(|k| (format!("t{k}"), rng.input())).collect(),
                        available: rng.input(),
                        unit: "s".into(),
                    }
                };
                Check {
                    group: format!("g{i}"),
                    kind,
                    eval,
                }
            })
            .collect();
        let t = template(checks.clone());
        let a = assess(&t, NOW);
        seen[a.state as usize] += 1;
        assert!(validator.is_valid(&a.evidence), "R8: {}", a.evidence);
        let hard: Vec<_> = a.checks.iter().filter(|c| c.kind == Kind::Hard).collect();
        if a.state == State::Meets {
            assert!(
                !hard.is_empty() && hard.iter().all(|c| c.state == State::Meets),
                "R7"
            );
            assert!(
                hard.iter()
                    .flat_map(|c| &c.inputs)
                    .all(|i| i["status"] == "known"),
                "R7: meets only on known inputs"
            );
        }
        if hard.iter().any(|c| c.state == State::Violates) {
            assert_eq!(a.state, State::Violates, "a hard failure is never offset");
        } else if hard.iter().any(|c| c.state == State::CannotAssess) {
            assert_eq!(a.state, State::CannotAssess);
        }
        let only_hard = Template {
            checks: checks
                .into_iter()
                .filter(|c| c.kind == Kind::Hard)
                .collect(),
            ..t
        };
        assert_eq!(
            assess(&only_hard, NOW).state,
            a.state,
            "soft checks never change the state"
        );
    }
}
