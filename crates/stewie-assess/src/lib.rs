//! The assessment engine (navigator N22, requirements R7 and R8).
//!
//! A task template is a list of checks, each hard (a requirement) or soft (a preference). Every result
//! is one of three states: **meets modeled constraints**, **violates** a named constraint, or **cannot
//! assess**. The rules:
//! - Only hard checks set the state. A violated hard check makes the result `Violates`, whatever else is
//!   true: a soft preference never offsets it.
//! - With no hard violation, any hard check that cannot be assessed (an input missing, stale or
//!   unmodelled; a visibility window that is Unknown or outside the computed range) makes the result
//!   `CannotAssess`. Cannot-assess never becomes a favourable answer (R7).
//! - Margin is reported as its own number with its unit, never as a fourth verdict. The binding check
//!   is the hard check with the least relative slack (margin over its scale), so checks in different
//!   units compare.
//! - Every result carries its evidence: each input with its value, version and whether it is simulated,
//!   the template's assumptions and rule revision, and the constraint groups not assessed (R8).

use lunar_intervals::{Verdict, Window};
use serde_json::{Value, json};

/// One input to a check.
#[derive(Debug, Clone, PartialEq)]
pub enum Input<T> {
    /// A value with its data version, the epoch it describes (TDB s) and how old it may be.
    Known {
        value: T,
        version: String,
        as_of_tdb: f64,
        max_age_s: Option<f64>,
        simulated: bool,
    },
    /// No value is installed.
    Missing(String),
    /// The quantity is not modelled by this build.
    Unmodeled(String),
}

impl<T> Input<T> {
    /// The value if present and fresh at `now_tdb`, else why it cannot be used.
    fn usable(&self, now_tdb: f64) -> Result<&T, String> {
        match self {
            Input::Known {
                value,
                as_of_tdb,
                max_age_s,
                ..
            } => match max_age_s {
                Some(age) if now_tdb - as_of_tdb > *age => Err(format!(
                    "stale: {:.0} s old, limit {age:.0} s",
                    now_tdb - as_of_tdb
                )),
                _ => Ok(value),
            },
            Input::Missing(why) => Err(format!("missing: {why}")),
            Input::Unmodeled(why) => Err(format!("not modelled: {why}")),
        }
    }

    fn evidence(&self, name: &str, show: impl Fn(&T) -> Value) -> Value {
        match self {
            Input::Known {
                value,
                version,
                as_of_tdb,
                simulated,
                ..
            } => {
                json!({"name": name, "status": "known", "value": show(value), "version": version, "as_of_tdb": as_of_tdb, "simulated": simulated})
            }
            Input::Missing(why) => json!({"name": name, "status": "missing", "why": why}),
            Input::Unmodeled(why) => json!({"name": name, "status": "unmodeled", "why": why}),
        }
    }

    fn simulated(&self) -> bool {
        matches!(
            self,
            Input::Known {
                simulated: true,
                ..
            }
        )
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Sense {
    AtMost,
    AtLeast,
}

/// How a check is evaluated.
#[derive(Debug, Clone, PartialEq)]
pub enum Eval {
    /// `value <= limit` (or `>=`); margin = the distance to the limit, positive when met.
    Threshold {
        value: Input<f64>,
        limit: Input<f64>,
        sense: Sense,
        unit: String,
    },
    /// `sum(terms) <= available` (the navigator's time and resource inequalities); every term, the
    /// reserve included, is a required input.
    Budget {
        terms: Vec<(String, Input<f64>)>,
        available: Input<f64>,
        unit: String,
    },
    /// The task `[start, start + duration]` plus `buffer_s` must lie inside one `Lit` window; `Shadow`
    /// first violates, `Unknown` first (or running past the computed windows) cannot be assessed.
    /// Margin [s] = usable lit time after the buffer minus the duration.
    WindowCover {
        windows: Input<Vec<Window>>,
        start_tdb: Input<f64>,
        duration_s: Input<f64>,
        buffer_s: Input<f64>,
    },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Kind {
    Hard,
    Soft,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Check {
    /// The constraint group, e.g. "illumination", "terrain slope".
    pub group: String,
    pub kind: Kind,
    pub eval: Eval,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Template {
    pub name: String,
    pub rule_revision: String,
    pub checks: Vec<Check>,
    /// Constraint groups this build does not compute; always listed as not assessed.
    pub not_modeled: Vec<String>,
    pub assumptions: Vec<String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum State {
    Meets,
    Violates,
    CannotAssess,
}

#[derive(Debug, Clone, PartialEq)]
pub struct CheckResult {
    pub group: String,
    pub kind: Kind,
    pub state: State,
    pub margin: Option<f64>,
    pub unit: String,
    /// Margin over the check's scale (dimensionless), for choosing the binding check.
    pub slack: Option<f64>,
    pub detail: String,
    pub inputs: Vec<Value>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Assessment {
    pub template: String,
    pub state: State,
    /// Index into `checks` of the binding hard check, when any hard check has a margin.
    pub binding: Option<usize>,
    pub checks: Vec<CheckResult>,
    pub not_assessed: Vec<String>,
    pub simulated: bool,
    pub evidence: Value,
}

fn scaled(margin: f64, scale: f64) -> f64 {
    margin / scale.abs().max(f64::MIN_POSITIVE)
}

/// What one evaluation found, before it is labelled with its check.
struct Found {
    state: State,
    margin: Option<f64>,
    unit: String,
    slack: Option<f64>,
    detail: String,
    inputs: Vec<Value>,
}

#[allow(clippy::trivially_copy_pass_by_ref)] // evidence() shows every value through &T
fn num(v: &f64) -> Value {
    json!(v)
}

fn threshold(value: &Input<f64>, limit: &Input<f64>, sense: Sense, unit: &str, now: f64) -> Found {
    let inputs = vec![value.evidence("value", num), limit.evidence("limit", num)];
    match (value.usable(now), limit.usable(now)) {
        (Ok(v), Ok(l)) => {
            let margin = match sense {
                Sense::AtMost => l - v,
                Sense::AtLeast => v - l,
            };
            let state = if margin >= 0.0 {
                State::Meets
            } else {
                State::Violates
            };
            Found {
                state,
                margin: Some(margin),
                unit: unit.into(),
                slack: Some(scaled(margin, *l)),
                detail: format!("{v} against limit {l}"),
                inputs,
            }
        }
        (Err(e), _) | (_, Err(e)) => Found {
            state: State::CannotAssess,
            margin: None,
            unit: unit.into(),
            slack: None,
            detail: e,
            inputs,
        },
    }
}

fn budget(terms: &[(String, Input<f64>)], available: &Input<f64>, unit: &str, now: f64) -> Found {
    let mut inputs: Vec<Value> = terms.iter().map(|(n, t)| t.evidence(n, num)).collect();
    inputs.push(available.evidence("available", num));
    let used: Result<f64, String> = terms
        .iter()
        .map(|(n, t)| t.usable(now).copied().map_err(|e| format!("{n} {e}")))
        .sum();
    match (used, available.usable(now)) {
        (Ok(u), Ok(a)) => {
            let margin = a - u;
            let state = if margin >= 0.0 {
                State::Meets
            } else {
                State::Violates
            };
            Found {
                state,
                margin: Some(margin),
                unit: unit.into(),
                slack: Some(scaled(margin, *a)),
                detail: format!("{u} used of {a}"),
                inputs,
            }
        }
        (Err(e), _) | (_, Err(e)) => Found {
            state: State::CannotAssess,
            margin: None,
            unit: unit.into(),
            slack: None,
            detail: e,
            inputs,
        },
    }
}

fn cover(
    windows: &Input<Vec<Window>>,
    start: &Input<f64>,
    duration: &Input<f64>,
    buffer: &Input<f64>,
    now: f64,
) -> Found {
    let inputs = vec![
        windows.evidence("windows", |w| json!(w.len())),
        start.evidence("start_tdb", num),
        duration.evidence("duration_s", num),
        buffer.evidence("buffer_s", num),
    ];
    match (
        windows.usable(now),
        start.usable(now),
        duration.usable(now),
        buffer.usable(now),
    ) {
        (Ok(ws), Ok(&t0), Ok(&dur), Ok(&buf)) => {
            let (state, margin, detail) = window_cover(ws, t0, dur, buf, t0 + dur + buf);
            Found {
                state,
                margin,
                unit: "s".into(),
                slack: margin.map(|m| scaled(m, dur.max(1.0))),
                detail,
                inputs,
            }
        }
        (Err(e), ..) | (_, Err(e), ..) | (_, _, Err(e), _) | (.., Err(e)) => Found {
            state: State::CannotAssess,
            margin: None,
            unit: "s".into(),
            slack: None,
            detail: e,
            inputs,
        },
    }
}

fn evaluate(c: &Check, now: f64) -> CheckResult {
    let f = match &c.eval {
        Eval::Threshold {
            value,
            limit,
            sense,
            unit,
        } => threshold(value, limit, *sense, unit, now),
        Eval::Budget {
            terms,
            available,
            unit,
        } => budget(terms, available, unit, now),
        Eval::WindowCover {
            windows,
            start_tdb,
            duration_s,
            buffer_s,
        } => cover(windows, start_tdb, duration_s, buffer_s, now),
    };
    CheckResult {
        group: c.group.clone(),
        kind: c.kind,
        state: f.state,
        margin: f.margin,
        unit: f.unit,
        slack: f.slack,
        detail: f.detail,
        inputs: f.inputs,
    }
}

fn window_cover(
    ws: &[Window],
    t0: f64,
    dur: f64,
    buf: f64,
    need_until: f64,
) -> (State, Option<f64>, String) {
    let Some(first) = ws.iter().position(|w| w.start_tdb <= t0 && t0 < w.end_tdb) else {
        return (
            State::CannotAssess,
            None,
            "task start is outside the computed windows".into(),
        );
    };
    let mut lit_until = t0;
    for w in &ws[first..] {
        match w.verdict {
            Verdict::Lit => {
                lit_until = w.end_tdb;
                if lit_until >= need_until {
                    break;
                }
            }
            Verdict::Shadow => break,
            Verdict::Unknown => {
                return (
                    State::CannotAssess,
                    None,
                    format!(
                        "visibility unknown from {:.0} s after start",
                        w.start_tdb.max(t0) - t0
                    ),
                );
            }
        }
    }
    if lit_until < need_until && ws.last().is_some_and(|w| w.end_tdb <= lit_until) {
        return (
            State::CannotAssess,
            None,
            "the task runs past the computed windows".into(),
        );
    }
    let usable = lit_until - t0 - buf;
    let margin = usable - dur;
    let state = if margin >= 0.0 {
        State::Meets
    } else {
        State::Violates
    };
    // still lit where the computed windows end: the margin is a lower bound, not a predicted loss
    let through = ws
        .last()
        .is_some_and(|w| w.verdict == Verdict::Lit && w.end_tdb <= lit_until);
    let detail = if through {
        format!(
            "visible through the computed windows ({:.0} s); buffer {buf:.0} s; at least {:.0} s meet the rule",
            lit_until - t0,
            usable.max(0.0)
        )
    } else {
        format!(
            "lost after {:.0} s; buffer {buf:.0} s; {:.0} s meet the rule",
            lit_until - t0,
            usable.max(0.0)
        )
    };
    (state, Some(margin), detail)
}

/// Assess `t` at `now_tdb` (staleness is judged against it).
#[must_use]
pub fn assess(t: &Template, now_tdb: f64) -> Assessment {
    let checks: Vec<CheckResult> = t.checks.iter().map(|c| evaluate(c, now_tdb)).collect();
    let hard = || {
        checks
            .iter()
            .enumerate()
            .filter(|(_, r)| r.kind == Kind::Hard)
    };
    let state = if hard().any(|(_, r)| r.state == State::Violates) {
        State::Violates
    } else if hard().any(|(_, r)| r.state == State::CannotAssess) || hard().next().is_none() {
        State::CannotAssess
    } else {
        State::Meets
    };
    let binding = hard()
        .filter_map(|(i, r)| r.slack.map(|s| (i, s)))
        .min_by(|a, b| a.1.total_cmp(&b.1))
        .map(|(i, _)| i);
    let simulated = t.checks.iter().any(|c| match &c.eval {
        Eval::Threshold { value, limit, .. } => value.simulated() || limit.simulated(),
        Eval::Budget {
            terms, available, ..
        } => available.simulated() || terms.iter().any(|(_, x)| x.simulated()),
        Eval::WindowCover {
            windows,
            start_tdb,
            duration_s,
            buffer_s,
        } => {
            windows.simulated()
                || start_tdb.simulated()
                || duration_s.simulated()
                || buffer_s.simulated()
        }
    });
    let name = |s: State| match s {
        State::Meets => "meets modeled constraints",
        State::Violates => "violates",
        State::CannotAssess => "cannot assess",
    };
    let evidence = json!({
        "template": t.name,
        "rule_revision": t.rule_revision,
        "assessed_at_tdb": now_tdb,
        "state": name(state),
        "binding": binding.map(|i| checks[i].group.clone()),
        "simulated": simulated,
        "assumptions": t.assumptions,
        "not_assessed": t.not_modeled,
        "checks": checks.iter().map(|r| json!({
            "group": r.group,
            "kind": if r.kind == Kind::Hard { "hard" } else { "soft" },
            "state": name(r.state),
            "margin": r.margin,
            "unit": r.unit,
            "detail": r.detail,
            "inputs": r.inputs,
        })).collect::<Vec<_>>(),
    });
    Assessment {
        template: t.name.clone(),
        state,
        binding,
        checks,
        not_assessed: t.not_modeled.clone(),
        simulated,
        evidence,
    }
}
