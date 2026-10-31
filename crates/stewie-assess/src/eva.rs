//! The suited-crew field task (navigator Field Mode): can a crew member walk to a station, do a task and get
//! back inside the light, the time and the oxygen this EVA has? Built on the RW-30h profile (D-R78).
//!
//! Every mission quantity (reserves, buffers, availability, the route times from the mission's rate model) is
//! a required input: a missing one makes the task cannot-assess, never a default. Oxygen for the whole EVA is
//! charged at the profile's level-walk rate, the higher of its two sourced rates (D-R80).

use lunar_intervals::Window;
use stewie_contracts::astronaut_profile::AstronautProfile;

use crate::{Check, Eval, Input, Kind, Template};

/// One field task's inputs. Times are seconds, oxygen kilograms.
#[derive(Debug, Clone, PartialEq)]
pub struct FieldTask {
    pub station: String,
    pub activity: String,
    /// Sun visibility windows at the station (lunar-intervals).
    pub sun_windows: Input<Vec<Window>>,
    /// Earth visibility windows at the station, for the voice link.
    pub earth_windows: Input<Vec<Window>>,
    pub start_tdb: Input<f64>,
    pub task_s: Input<f64>,
    /// Light that must remain after the task (mission config).
    pub light_buffer_s: Input<f64>,
    /// Earth visibility that must remain after the task (mission config).
    pub link_buffer_s: Input<f64>,
    /// Out and back over the route profile with the mission's rate model (no sourced speed against slope).
    pub traverse_s: Input<f64>,
    pub return_s: Input<f64>,
    pub ingress_s: Input<f64>,
    pub time_reserve_s: Input<f64>,
    pub time_available_s: Input<f64>,
    pub o2_available_kg: Input<f64>,
    pub o2_reserve_kg: Input<f64>,
}

/// `rate_per_s * sum(parts)` as one input: Known only when every part is, as of the oldest part, expiring with
/// the first part to expire, simulated if any part is; otherwise Missing, naming the part that blocked it.
fn rate_times(rate_per_s: f64, rate_version: &str, parts: &[(&str, &Input<f64>)]) -> Input<f64> {
    let (mut total, mut as_of, mut expiry, mut simulated) =
        (0.0, f64::INFINITY, f64::INFINITY, false);
    let mut versions = vec![rate_version.to_owned()];
    for (name, part) in parts {
        let Input::Known {
            value,
            version,
            as_of_tdb,
            max_age_s,
            simulated: sim,
        } = part
        else {
            let why = match part {
                Input::Missing(w) | Input::Unmodeled(w) => w.as_str(),
                Input::Known { .. } => "",
            };
            return Input::Missing(format!("needs {name}: {why}"));
        };
        total += value;
        as_of = as_of.min(*as_of_tdb);
        if let Some(age) = max_age_s {
            expiry = expiry.min(as_of_tdb + age);
        }
        simulated |= sim;
        versions.push(format!("{name}@{version}"));
    }
    Input::Known {
        value: rate_per_s * total,
        version: versions.join(" "),
        as_of_tdb: as_of,
        max_age_s: expiry.is_finite().then_some(expiry - as_of),
        simulated,
    }
}

fn hard(group: &str, eval: Eval) -> Check {
    Check {
        group: group.into(),
        kind: Kind::Hard,
        eval,
    }
}

/// The field-task template: illumination and Earth visibility through the task plus their buffers, the
/// navigator's time budget, and the oxygen budget, all hard.
#[must_use]
pub fn field_task(t: &FieldTask, profile: &AstronautProfile) -> Template {
    let o2 = &profile.level_walk_o2_kg_per_hr;
    let o2_used = rate_times(
        o2.value / 3600.0,
        &format!("{}:level_walk_o2_kg_per_hr", profile.name.as_str()),
        &[
            ("traverse_s", &t.traverse_s),
            ("task_s", &t.task_s),
            ("return_s", &t.return_s),
            ("ingress_s", &t.ingress_s),
        ],
    );
    let cover = |windows: &Input<Vec<Window>>, buffer: &Input<f64>| Eval::WindowCover {
        windows: windows.clone(),
        start_tdb: t.start_tdb.clone(),
        duration_s: t.task_s.clone(),
        buffer_s: buffer.clone(),
    };
    Template {
        name: format!("{} at {}", t.activity, t.station),
        rule_revision: "eva-field-1 (D-R80)".into(),
        checks: vec![
            hard("illumination", cover(&t.sun_windows, &t.light_buffer_s)),
            hard("earth visibility", cover(&t.earth_windows, &t.link_buffer_s)),
            hard(
                "time",
                Eval::Budget {
                    terms: vec![
                        ("traverse".into(), t.traverse_s.clone()),
                        ("task".into(), t.task_s.clone()),
                        ("return".into(), t.return_s.clone()),
                        ("ingress".into(), t.ingress_s.clone()),
                        ("reserve".into(), t.time_reserve_s.clone()),
                    ],
                    available: t.time_available_s.clone(),
                    unit: "s".into(),
                },
            ),
            hard(
                "oxygen",
                Eval::Budget {
                    terms: vec![
                        ("eva".into(), o2_used),
                        ("reserve".into(), t.o2_reserve_kg.clone()),
                    ],
                    available: t.o2_available_kg.clone(),
                    unit: "kg".into(),
                },
            ),
        ],
        not_modeled: vec![
            "suited slope limit (no sourced limit)".into(),
            "cooling water".into(),
            "radio link budget".into(),
            "thermal".into(),
        ],
        assumptions: vec![
            format!(
                "oxygen for the whole EVA at {:.4} kg/hr ({}); Apollo averaged {:.4} kg/hr, so this is conservative",
                o2.value,
                o2.source.as_str(),
                profile.apollo_o2_kg_per_hr.value
            ),
            "traverse and return times come from the route profile with the mission's rate model; no source gives \
             suited walking speed against slope (D-R78)"
                .into(),
            "illumination and Earth visibility apply to the task interval at the station only".into(),
        ],
    }
}
