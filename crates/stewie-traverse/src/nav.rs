//! The navigation family (RW-55b24; Python `lode.faults`, `lode.recovery`, `lode.executive`, `lode.local_planner`):
//! the NV-08 fault taxonomy, the NV-06/07 recovery decision, the NV-09 executive's strict safety precedence, and
//! the NV-03 local arc planner with its NV-04 bounded tracker. Pure decision logic and geometry: the signals are
//! computed elsewhere and passed in.

use serde_json::{Value, json};

/// The skid-steer maximum yaw rate [rad/s] (Python `local_planner.DEFAULT_OMEGA_MAX`, an assumption).
pub const DEFAULT_OMEGA_MAX: f64 = 0.20;

const TIP_WARN_DEG: f64 = 5.0;
const SLIP_ENTRAP: f64 = 0.95;
const SLIP_WARN: f64 = 0.80;
const LOC_DIVERGED_M: f64 = 5.0;
const LOC_WARN_M: f64 = 2.0;
const LOW_ENERGY_WARN: f64 = 0.20;
const ACTUATOR_TMIN_C: f64 = -35.0;
const ACTUATOR_TMAX_C: f64 = 40.0;
const THERMAL_WARN_MARGIN_C: f64 = 5.0;

/// The telemetry a fault check reads; an absent signal is not classified.
#[derive(Debug, Clone, Copy, Default, PartialEq)]
pub struct Telemetry {
    pub tip_margin_deg: Option<f64>,
    pub slip: Option<f64>,
    pub loc_sigma_m: Option<f64>,
    pub battery_frac: Option<f64>,
    pub temp_c: Option<f64>,
    pub actuator_ok: Option<bool>,
}

/// NV-08: the active faults, in fault-class order, each `{fault, severity, value, limit, message}`. The pack
/// `reserve_frac` is the mission configuration's (RW-30: no crate compiles a reserve in).
#[must_use]
#[allow(clippy::too_many_lines)] // one block per fault class, as the Python
pub fn classify_faults(t: &Telemetry, reserve_frac: f64) -> Vec<Value> {
    let mut out = Vec::new();
    let mut add = |fault: &str, sev: &str, value: Value, limit: Value, msg: &str| {
        out.push(json!({"fault": fault, "severity": sev, "value": value, "limit": limit, "message": msg}));
    };
    if let Some(m) = t.tip_margin_deg {
        if m <= 0.0 {
            add(
                "tip",
                "critical",
                json!(m),
                json!(0.0),
                "static stability margin exhausted -> tipping",
            );
        } else if m < TIP_WARN_DEG {
            add(
                "tip",
                "warn",
                json!(m),
                json!(TIP_WARN_DEG),
                "low tip-over margin",
            );
        }
    }
    if let Some(s) = t.slip {
        if s >= SLIP_ENTRAP {
            add(
                "entrapment",
                "critical",
                json!(s),
                json!(SLIP_ENTRAP),
                "wheel slip at entrapment (slip-sinkage runaway)",
            );
        } else if s >= SLIP_WARN {
            add(
                "entrapment",
                "warn",
                json!(s),
                json!(SLIP_WARN),
                "high slip approaching entrapment",
            );
        }
    }
    if let Some(l) = t.loc_sigma_m {
        if l >= LOC_DIVERGED_M {
            add(
                "localization_divergence",
                "critical",
                json!(l),
                json!(LOC_DIVERGED_M),
                "pose uncertainty diverged",
            );
        } else if l >= LOC_WARN_M {
            add(
                "localization_divergence",
                "warn",
                json!(l),
                json!(LOC_WARN_M),
                "growing pose uncertainty",
            );
        }
    }
    if let Some(b) = t.battery_frac {
        if b < reserve_frac {
            add(
                "low_energy",
                "critical",
                json!(b),
                json!(reserve_frac),
                "battery below operational reserve",
            );
        } else if b < LOW_ENERGY_WARN {
            add(
                "low_energy",
                "warn",
                json!(b),
                json!(LOW_ENERGY_WARN),
                "battery approaching reserve",
            );
        }
    }
    if let Some(c) = t.temp_c {
        let range = json!([ACTUATOR_TMIN_C, ACTUATOR_TMAX_C]);
        if !(ACTUATOR_TMIN_C..=ACTUATOR_TMAX_C).contains(&c) {
            add(
                "thermal",
                "critical",
                json!(c),
                range,
                "temperature outside the actuator qual range",
            );
        } else if !(ACTUATOR_TMIN_C + THERMAL_WARN_MARGIN_C
            ..=ACTUATOR_TMAX_C - THERMAL_WARN_MARGIN_C)
            .contains(&c)
        {
            add(
                "thermal",
                "warn",
                json!(c),
                range,
                "temperature near the qual edge",
            );
        }
    }
    if t.actuator_ok == Some(false) {
        add(
            "actuator",
            "critical",
            json!(false),
            json!(true),
            "actuator fault reported",
        );
    }
    out
}

fn critical_names(faults: &[Value]) -> Vec<String> {
    let mut names: Vec<String> = faults
        .iter()
        .filter(|f| f["severity"] == "critical")
        .filter_map(|f| f["fault"].as_str().map(str::to_owned))
        .collect();
    names.sort();
    names
}

/// The rollup: count, the distinct classes, the critical ones, and whether any is safety-critical.
#[must_use]
pub fn fault_summary(faults: &[Value]) -> Value {
    let mut classes: Vec<String> = faults
        .iter()
        .filter_map(|f| f["fault"].as_str().map(str::to_owned))
        .collect();
    classes.sort();
    classes.dedup();
    let critical = critical_names(faults);
    json!({"n": faults.len(), "classes": classes, "safety_critical": !critical.is_empty(), "critical": critical})
}

/// NV-06+07: the recovery action for the progress telemetry, a slope/slip slowdown never mistaken for a
/// blockage: `replan_global` on a planner failure, else `continue` unless low progress persisted, then
/// `reverse` for a blockage and `persist` for an expected slowdown.
#[must_use]
pub fn recommend(
    progress_ratio: f64,
    stall_s: f64,
    expected_progress_ratio: f64,
    planner_failed: bool,
) -> Value {
    const THRESH: f64 = 0.25;
    const MIN_STALL_S: f64 = 2.0;
    const SLOWDOWN_TOL: f64 = 0.15;
    let (recover, reason) = if planner_failed {
        (true, "planner_failure")
    } else if progress_ratio < THRESH && stall_s >= MIN_STALL_S {
        (true, "low_progress")
    } else {
        (false, "nominal")
    };
    let stall = if progress_ratio >= expected_progress_ratio - SLOWDOWN_TOL {
        if progress_ratio >= THRESH {
            "nominal"
        } else {
            "slope_slip"
        }
    } else {
        "blockage"
    };
    let action = if planner_failed {
        "replan_global"
    } else if !recover {
        "continue"
    } else if stall == "blockage" {
        "reverse"
    } else {
        "persist"
    };
    json!({"action": action, "recover": recover, "reason": reason, "stall_class": stall})
}

/// NV-09: the next executive action in strict safety precedence (a safety-critical fault always wins).
#[must_use]
pub fn executive_step(
    faults: &[Value],
    command_acked: bool,
    plan_accepted: bool,
    recovery: Option<&Value>,
    reactive_scope: Option<&str>,
) -> Value {
    let rec = recovery.and_then(|r| r["action"].as_str());
    let step = |action: &str, reason: &str| json!({"action": action, "reason": reason, "safety_critical": false});
    let critical = critical_names(faults);
    if !critical.is_empty() {
        return json!({"action": "fail_safe", "reason": format!("safety-critical fault(s): {}", critical.join(", ")),
                      "safety_critical": true});
    }
    if !command_acked {
        return step("pause", "last command not acknowledged (move-and-wait)");
    }
    if !plan_accepted {
        return step("pause", "current step not accepted for execution");
    }
    if rec == Some("replan_global") || reactive_scope == Some("global") {
        return step(
            "replan_global",
            "planner failure / no local detour -> global re-route",
        );
    }
    match rec {
        Some("reverse") => step(
            "reverse",
            "blockage (progress far below slip prediction) -> back out",
        ),
        Some("persist") => step(
            "persist",
            "expected slope/slip slowdown -> keep pushing (no false reverse)",
        ),
        _ if reactive_scope == Some("local") => {
            step("replan_local", "reactive hazard -> local detour")
        }
        _ => step("continue", "nominal"),
    }
}

/// numpy's `linspace(0, length, n)`: `i * step`, the last sample exactly `length`.
#[allow(clippy::cast_precision_loss)] // a sample count
fn linspace(length: f64, n: usize) -> Vec<f64> {
    let step = length / (n - 1) as f64;
    let mut s: Vec<f64> = (0..n).map(|i| i as f64 * step + 0.0).collect();
    s[n - 1] = length;
    s
}

/// `n` poses `(x, y, theta)` along a constant-curvature arc of length `length_m` from `(x0, y0, th0)` (the exact
/// unicycle integral; straight below `|kappa|` 1e-9).
#[must_use]
pub fn constant_curvature_arc(
    x0: f64,
    y0: f64,
    th0: f64,
    kappa: f64,
    length_m: f64,
    n: usize,
) -> Vec<[f64; 3]> {
    linspace(length_m, n)
        .into_iter()
        .map(|s| {
            let th = th0 + kappa * s;
            if kappa.abs() < 1e-9 {
                [x0 + s * th0.cos(), y0 + s * th0.sin(), th]
            } else {
                [
                    x0 + (th.sin() - th0.sin()) / kappa,
                    y0 - (th.cos() - th0.cos()) / kappa,
                    th,
                ]
            }
        })
        .collect()
}

/// The default fan: eleven curvatures in `[-0.33, 0.33]` 1/m with straight, ascending.
#[must_use]
#[allow(clippy::cast_precision_loss)] // fan indices
pub fn curvature_fan() -> Vec<f64> {
    const MAX_KAPPA: f64 = 0.33;
    const HALF: usize = 5;
    let mut ks = vec![0.0];
    for i in 1..=HALF {
        let k = MAX_KAPPA * i as f64 / HALF as f64;
        ks.push(k);
        ks.push(-k);
    }
    ks.sort_by(f64::total_cmp);
    ks
}

/// A clearance-inflated circle `(x, y, r)`.
pub type Circle = (f64, f64, f64);

fn arc_feasible(
    arc: &[[f64; 3]],
    blocked: Option<&dyn Fn(f64, f64) -> bool>,
    keepouts: &[Circle],
    rocks: &[Circle],
    clearance_m: f64,
) -> bool {
    arc.iter().all(|p| {
        let (x, y) = (p[0], p[1]);
        !blocked.is_some_and(|b| b(x, y))
            && keepouts
                .iter()
                .all(|(kx, ky, kr)| (x - kx).hypot(y - ky) > kr + clearance_m)
            && rocks
                .iter()
                .all(|(rx, ry, rr)| (x - rx).hypot(y - ry) > rr + clearance_m)
    })
}

/// An NV-03 local plan: the chosen arc and its figures, or every arc blocked.
#[derive(Debug, Clone, PartialEq)]
pub struct LocalPlan {
    pub feasible: bool,
    pub arc: Vec<[f64; 3]>,
    pub curvature: f64,
    pub progress_m: f64,
    pub n_sampled: usize,
    pub n_feasible: usize,
}

/// NV-03: sample the curvature fan from the pose and keep the feasible arc that ends nearest the goal, a small
/// straightness penalty breaking near-ties; every arc blocked is `feasible: false` (never a forced unsafe arc).
#[must_use]
#[allow(clippy::too_many_arguments)] // the Python's keyword arguments
pub fn plan_local(
    pose: (f64, f64),
    heading_rad: f64,
    goal: (f64, f64),
    blocked: Option<&dyn Fn(f64, f64) -> bool>,
    keepouts: &[Circle],
    rocks: &[Circle],
    clearance_m: f64,
    horizon_m: f64,
) -> LocalPlan {
    let fan = curvature_fan();
    let mut best: Option<(f64, Vec<[f64; 3]>, f64)> = None;
    let mut n_feasible = 0;
    for &k in &fan {
        let arc = constant_curvature_arc(pose.0, pose.1, heading_rad, k, horizon_m, 12);
        if !arc_feasible(&arc, blocked, keepouts, rocks, clearance_m) {
            continue;
        }
        n_feasible += 1;
        let end = arc[arc.len() - 1];
        let cost = (goal.0 - end[0]).hypot(goal.1 - end[1]) + 0.5 * k.abs() * horizon_m;
        if best.as_ref().is_none_or(|b| cost < b.0) {
            best = Some((cost, arc, k));
        }
    }
    match best {
        None => LocalPlan {
            feasible: false,
            arc: Vec::new(),
            curvature: 0.0,
            progress_m: 0.0,
            n_sampled: fan.len(),
            n_feasible: 0,
        },
        Some((_, arc, k)) => {
            let end = arc[arc.len() - 1];
            let progress =
                (goal.0 - pose.0).hypot(goal.1 - pose.1) - (goal.0 - end[0]).hypot(goal.1 - end[1]);
            LocalPlan {
                feasible: true,
                arc,
                curvature: k,
                progress_m: progress,
                n_sampled: fan.len(),
                n_feasible,
            }
        }
    }
}

/// The NV-04 bounded command for a plan's arc.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Command {
    pub v_cmd: f64,
    pub omega_cmd: f64,
    pub expected_speed_ms: f64,
    pub duration_s: f64,
    pub arc_length_m: f64,
}

/// NV-04: bound the arc's twist so neither the linear nor the yaw-rate cap is exceeded, over its measured
/// polyline length (numpy's pairwise sum).
#[must_use]
pub fn track_plan(plan: &LocalPlan, v_max: f64, omega_max: f64) -> Command {
    let seg: Vec<f64> = plan
        .arc
        .windows(2)
        .map(|w| (w[1][0] - w[0][0]).hypot(w[1][1] - w[0][1]))
        .collect();
    let length = stewie_twin::numpy::sum(&seg);
    let k = plan.curvature.abs();
    let v = if k < 1e-9 {
        v_max
    } else {
        v_max.min(omega_max / k)
    };
    let duration = if v > 1e-9 { length / v } else { f64::INFINITY };
    Command {
        v_cmd: v,
        omega_cmd: plan.curvature * v,
        expected_speed_ms: v,
        duration_s: duration,
        arc_length_m: length,
    }
}

#[cfg(test)]
mod tests {
    use super::{curvature_fan, linspace};

    #[test]
    fn the_fan_and_the_samples_are_numpys() {
        let fan = curvature_fan();
        assert_eq!(fan.len(), 11);
        assert_eq!(fan[5].to_bits(), 0.0_f64.to_bits());
        let s = linspace(8.0, 12);
        assert_eq!(s[11].to_bits(), 8.0_f64.to_bits());
        assert_eq!(s[1].to_bits(), (8.0_f64 / 11.0).to_bits());
    }
}
