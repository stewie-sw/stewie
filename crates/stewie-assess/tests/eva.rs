//! The suited-crew field task on the real EVA profile (`eva_crew.json`, D-R78). Task inputs and visibility
//! windows are SYNTHETIC (labelled): the navigator's Station Bravo numbers and round mission figures.

use lunar_intervals::{Verdict, Window};
use serde_json::Value;
use stewie_assess::eva::{FieldTask, field_task};
use stewie_assess::{Input, State, assess};
use stewie_contracts::astronaut_profile::AstronautProfile;

const NOW: f64 = 1.0e9;
const MIN: f64 = 60.0;

fn profile() -> AstronautProfile {
    serde_json::from_str(include_str!(
        "../../stewie-contracts/fixtures/eva_crew.json"
    ))
    .unwrap()
}

fn known(v: f64) -> Input<f64> {
    Input::Known {
        value: v,
        version: "mission-r1".into(),
        as_of_tdb: NOW,
        max_age_s: None,
        simulated: false,
    }
}

fn lit_until(end: f64) -> Input<Vec<Window>> {
    Input::Known {
        value: vec![
            Window {
                start_tdb: NOW - 3600.0,
                end_tdb: end,
                verdict: Verdict::Lit,
            },
            Window {
                start_tdb: end,
                end_tdb: NOW + 86_400.0,
                verdict: Verdict::Shadow,
            },
        ],
        version: "eph-de440+ldem".into(),
        as_of_tdb: NOW,
        max_age_s: None,
        simulated: false,
    }
}

/// A 20-minute sampling task, 30 min out and back, 10 min ingress, 30 min reserve in 3 h; 1 kg O2, 0.2 kg reserve.
fn task() -> FieldTask {
    FieldTask {
        station: "Station Bravo".into(),
        activity: "Sampling".into(),
        sun_windows: lit_until(NOW + 3.0 * 3600.0),
        earth_windows: lit_until(NOW + 3.0 * 3600.0),
        start_tdb: known(NOW),
        task_s: known(20.0 * MIN),
        light_buffer_s: known(5.0 * MIN),
        link_buffer_s: known(5.0 * MIN),
        traverse_s: known(30.0 * MIN),
        return_s: known(30.0 * MIN),
        ingress_s: known(10.0 * MIN),
        time_reserve_s: known(30.0 * MIN),
        time_available_s: known(3.0 * 3600.0),
        o2_available_kg: known(1.0),
        o2_reserve_kg: known(0.2),
    }
}

fn group<'a>(a: &'a stewie_assess::Assessment, g: &str) -> &'a stewie_assess::CheckResult {
    a.checks.iter().find(|c| c.group == g).unwrap()
}

#[test]
fn a_task_inside_light_time_and_oxygen_meets_and_charges_oxygen_at_the_walkback_rate() {
    let p = profile();
    let a = assess(&field_task(&task(), &p), NOW);
    assert_eq!(a.state, State::Meets);
    // 90 min of EVA at 0.4 lb/hr = 0.181436948 kg/hr
    let used = p.level_walk_o2_kg_per_hr.value * 1.5;
    assert!((used - 0.4 * 0.453_592_37 * 1.5).abs() < 1e-12);
    let o2 = group(&a, "oxygen");
    assert!(
        (o2.margin.unwrap() - (1.0 - 0.2 - used)).abs() < 1e-12,
        "{o2:?}"
    );
    assert!((group(&a, "time").margin.unwrap() - 60.0 * MIN).abs() < 1e-9);
    let ev = a.evidence.to_string();
    assert!(
        ev.contains("0.1814 kg/hr") && ev.contains("slide 14"),
        "{ev}"
    );
    assert!(
        ev.contains("suited slope limit"),
        "not-modelled groups are listed"
    );
}

#[test]
fn the_station_bravo_light_rule_violates_whatever_the_budgets_say() {
    // shadow 18 min after the start; 5 min buffer; 20 min task (navigator example)
    let t = FieldTask {
        sun_windows: lit_until(NOW + 18.0 * MIN),
        ..task()
    };
    let a = assess(&field_task(&t, &profile()), NOW);
    assert_eq!(a.state, State::Violates);
    let light = group(&a, "illumination");
    assert_eq!(light.state, State::Violates);
    assert!(
        (light.margin.unwrap() + 7.0 * MIN).abs() < 1e-9,
        "{light:?}"
    );
    assert_eq!(group(&a, "oxygen").state, State::Meets);
}

#[test]
fn too_little_oxygen_violates_and_binds() {
    let t = FieldTask {
        o2_available_kg: known(0.4),
        ..task()
    };
    let a = assess(&field_task(&t, &profile()), NOW);
    assert_eq!(a.state, State::Violates);
    assert_eq!(group(&a, "oxygen").state, State::Violates);
    assert_eq!(a.checks[a.binding.unwrap()].group, "oxygen");
}

#[test]
fn a_missing_reserve_or_a_stale_route_time_cannot_be_assessed() {
    let p = profile();
    let no_reserve = FieldTask {
        o2_reserve_kg: Input::Missing("no O2 reserve in mission config".into()),
        ..task()
    };
    let a = assess(&field_task(&no_reserve, &p), NOW);
    assert_eq!(a.state, State::CannotAssess);
    assert_eq!(group(&a, "oxygen").state, State::CannotAssess);
    let stale = FieldTask {
        traverse_s: Input::Known {
            value: 30.0 * MIN,
            version: "route-r3".into(),
            as_of_tdb: NOW - 120.0,
            max_age_s: Some(60.0),
            simulated: false,
        },
        ..task()
    };
    let a = assess(&field_task(&stale, &p), NOW);
    assert_eq!(a.state, State::CannotAssess);
    // the stale route time reaches the derived oxygen term too
    assert_eq!(group(&a, "oxygen").state, State::CannotAssess);
    assert_eq!(group(&a, "time").state, State::CannotAssess);
    let unrouted = FieldTask {
        return_s: Input::Unmodeled("no route back".into()),
        ..task()
    };
    let o2 = assess(&field_task(&unrouted, &p), NOW);
    assert!(
        group(&o2, "oxygen").detail.contains("return_s"),
        "{:?}",
        group(&o2, "oxygen")
    );
}

#[test]
fn every_field_result_carries_schema_valid_evidence() {
    let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../stewie-contracts/schema/assessment.schema.json");
    let schema: Value = serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
    let v = jsonschema::validator_for(&schema).unwrap();
    for t in [
        task(),
        FieldTask {
            o2_available_kg: known(0.1),
            ..task()
        },
        FieldTask {
            earth_windows: Input::Missing("no Earth ephemeris installed".into()),
            ..task()
        },
    ] {
        let a = assess(&field_task(&t, &profile()), NOW);
        assert!(v.is_valid(&a.evidence), "{}", a.evidence);
    }
}
