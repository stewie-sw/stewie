//! The human Markdown plan report (RW-55b14d-2; Python `lode.planner_views.report`, its Markdown half): the
//! sequence, material balance, totals, the fleet breakdown, the routing and single-charge range notes, the
//! Assumptions Register and the vehicle configuration, rendered line for line as the Python writes it. The PDF
//! half moves to the report pane (RW-75, D-R85).

use std::fmt::Write as _;

use serde_json::Value;

use crate::assemble::Plan;
use crate::mission::Mission;

/// What the report quotes beyond the plan: the IPEx constants the Python's views import, the mission vehicle's
/// drum, the drum-fill sensing bands, the IPEx geometry and the Assumptions Register (`plan_report.json`).
#[derive(Debug, Clone, Copy)]
pub struct Consts<'a> {
    pub battery_j: f64,
    pub dig_j_per_kg: f64,
    pub drive_j_per_m: f64,
    pub recharge_w: f64,
    pub drum_kg: f64,
    pub fdc_mpe_half_full: f64,
    pub fdc_mpe_all: f64,
    /// The IPEx gauge, wheelbase and CG height [m].
    pub geometry: (f64, f64, f64),
    /// `{name, value, tag, note}` rows.
    pub register: &'a [Value],
    pub default_date: &'a str,
}

/// Python `mission_planner._dur`: hours below two days, else days.
fn dur(s: f64) -> String {
    let h = s / 3600.0;
    if h < 48.0 {
        format!("{h:.1} h")
    } else {
        format!("{:.1} d", h / 24.0)
    }
}

/// Python `str.title` (ASCII): a letter is upper-cased after an uncased character, else lower-cased.
fn title(s: &str) -> String {
    let mut prev_cased = false;
    s.chars()
        .map(|c| {
            let out = if prev_cased {
                c.to_ascii_lowercase()
            } else {
                c.to_ascii_uppercase()
            };
            prev_cased = c.is_ascii_alphabetic();
            out
        })
        .collect()
}

fn num(v: &Value, k: &str) -> f64 {
    v[k].as_f64().unwrap_or(0.0)
}

/// A value as Python's `str()` prints it (an int without a decimal point).
fn py(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        Value::Bool(b) => if *b { "True" } else { "False" }.to_owned(),
        Value::Number(n) if n.is_f64() => {
            stewie_twin::pyjson::float_repr(n.as_f64().unwrap_or(0.0)).unwrap_or_default()
        }
        Value::Null => "None".to_owned(),
        other => other.to_string(),
    }
}

fn truthy(v: &Value) -> bool {
    match v {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Number(n) => n.as_f64().is_some_and(|x| x != 0.0),
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(o) => !o.is_empty(),
    }
}

fn fleet(md: &mut Vec<String>, totals: &Value) {
    let t = totals;
    let mut head = format!(
        "- **{} rovers**, site-exclusive allocation · makespan **{}** (wall-clock the fleet finishes in)",
        py(&t["vehicles"]),
        dur(num(t, "makespan_s"))
    );
    if t.get("makespan_parallel_s").is_some() {
        let _ = write!(
            head,
            ", vs {} with unlimited chargers",
            dur(num(t, "makespan_parallel_s"))
        );
    }
    let mut charger = format!(
        "- Shared charger (one server): **{} overlap(s)** serialised FCFS → **+{}** total queue wait folded into the \
         makespan above",
        py(&t["charger_conflicts"]),
        dur(num(t, "charger_wait_s"))
    );
    if truthy(&t["temporal_conflicts"]) || truthy(&t["haul_path_conflicts"]) {
        let _ = write!(
            charger,
            "  ·  ⚠ **{} crowding + {} haul-path conflict(s)** re-sequenced FCFS → **+{}** wait folded into the \
             makespan above",
            py(&t["temporal_conflicts"]),
            py(&t["haul_path_conflicts"]),
            dur(num(t, "crowd_wait_s"))
        );
    }
    if truthy(&t["fleet_needs_replan"]) {
        charger += "  ·  ⚠ **fleet needs replan** (a rover stranded — reallocate its work)";
    }
    md.extend([
        String::new(),
        "## Fleet".to_owned(),
        head,
        charger,
        String::new(),
        "| Rover | Trips | Time | Energy MJ | Drive km | Recharges | Charger wait | Crowd wait | Health | Min batt |"
            .to_owned(),
        "|---|---|---|---|---|---|---|---|---|---|".to_owned(),
    ]);
    for d in t["vehicles_detail"].as_array().into_iter().flatten() {
        let h = &d["health"];
        md.push(format!(
            "| {} | {} | {} | {:.1} | {:.2} | {} | {} | {} | {} | {:.0}% |",
            py(&d["vehicle"]),
            py(&d["n_trips"]),
            dur(num(d, "time_s")),
            num(d, "energy_J") / 1e6,
            num(d, "distance_m") / 1000.0,
            py(&d["charges"]),
            dur(num(d, "charger_wait_s")),
            dur(num(d, "crowd_wait_s")),
            h["health"].as_str().unwrap_or("?"),
            h["min_batt_frac"].as_f64().unwrap_or(1.0) * 100.0
        ));
    }
}

fn endurance(md: &mut Vec<String>, e: &Value, body: &str) {
    let mut line = format!(
        "- **Per-sortie range:** {:.1} km flat to reserve ({:.1} km full pack, {:.0} h driving at {:.2} m/s)",
        num(e, "range_flat_reserve_km"),
        num(e, "range_flat_full_km"),
        num(e, "duration_flat_h"),
        num(e, "speed_ms")
    );
    if e.get("range_slopeslip_km").is_some() {
        let _ = write!(
            line,
            "; **{:.1} km** slope+slip-adjusted at the work-area median {:.0}° slope",
            num(e, "range_slopeslip_km"),
            num(e, "work_area_median_slope_deg")
        );
    }
    md.push(line);
    if let Some(r) = e.get("reach") {
        md.push(format!(
            "- One-charge reach on this DEM: {}",
            if truthy(&r["tile_fully_reachable"]) {
                format!(
                    "**entire {:.1} km work area** within reach (~{:.0}% of the pack to the farthest point)",
                    num(r, "radius_m") / 1000.0,
                    num(r, "worst_cell_pack_frac") * 100.0
                )
            } else {
                format!("radius **{:.1} km** from the charger", num(r, "radius_m") / 1000.0)
            }
        ));
    }
    if let Some(pw) = e.get("power").filter(|p| truthy(p)) {
        let derate = num(pw, "thermal_derate");
        md.push(format!(
            "- Power: **{}** — {}; charge {:.0} W (effective {:.0} W @ duty {:.2}){}",
            pw["kind"].as_str().unwrap_or("").replace('_', " "),
            py(&pw["availability"]),
            num(pw, "charge_power_w"),
            num(pw, "effective_charge_w"),
            num(pw, "duty_frac"),
            if derate < 1.0 {
                format!("; cold-derated pack ×{derate:.2}")
            } else {
                String::new()
            }
        ));
    }
    if let Some(ts) = e.get("timescale").filter(|t| truthy(t)) {
        let d = num(ts, "solar_day_h");
        let scale = if d >= 48.0 {
            format!("{:.1} Earth-days", d / 24.0)
        } else {
            format!("{d:.1} h")
        };
        let label = ts["day_label"].as_str().unwrap_or("");
        let rel = if truthy(&ts["fits_in_window"]) {
            format!(
                "a full-range {:.0} h sortie fits ~{:.0}× in the ~{:.0}–{:.0} h sunlit window",
                num(ts, "sortie_h"),
                num(ts, "sorties_per_window"),
                ts["op_window_h"][0].as_f64().unwrap_or(0.0),
                ts["op_window_h"][1].as_f64().unwrap_or(0.0)
            )
        } else {
            format!(
                "a full-range {:.0} h sortie spans ~{:.1} {label}s (> the ~{:.0} h daylight → night pauses)",
                num(ts, "sortie_h"),
                num(ts, "spans_days"),
                num(ts, "daylight_h")
            )
        };
        md.push(format!(
            "- Timescale ({}): **1 {label} ≈ {scale}** (~{:.0} h daylight) — {rel}; range is not window-bound.",
            title(body),
            num(ts, "daylight_h")
        ));
    }
    if let Some(c) = e.get("conops").filter(|c| truthy(c)) {
        let pair = |k: &str, i: usize| c[k][i].as_f64().unwrap_or(0.0);
        md.push(format!(
            "- ConOps [SCHULER24, lunar IPEx]: **{:.0} km traverse + {:.0}–{:.0} t excavated over {:.0} days** → \
             driving ~{:.1} MJ (~{:.1} packs) vs digging ~{:.0}–{:.0} MJ (~{:.0}–{:.0} packs): **the drums dominate \
             the energy budget** (recharged daily).",
            num(c, "traverse_km"),
            pair("regolith_t", 0),
            pair("regolith_t", 1),
            num(c, "mission_days"),
            num(c, "drive_energy_MJ"),
            num(c, "drive_packs"),
            pair("dig_energy_MJ", 0),
            pair("dig_energy_MJ", 1),
            pair("dig_packs", 0),
            pair("dig_packs", 1)
        ));
    }
}

/// The Markdown report of `plan` with its `totals` (the plan's totals JSON) and endurance report `endu`.
#[must_use]
#[allow(clippy::too_many_lines)] // the Python's report, section by section
pub fn markdown(m: &Mission, plan: &Plan, totals: &Value, endu: &Value, c: &Consts<'_>) -> String {
    let t = totals;
    let feasible = t["feasible"].as_bool().unwrap_or(true);
    let mut md: Vec<String> = vec![
        format!("# Lunar Build Mission Plan — {}", m.name),
        String::new(),
        format!(
            "**Body:** {} · **Date:** {} · cut-fill balanced · sequence **{}** optimizing **{}**",
            title(&m.body),
            m.date.as_deref().unwrap_or(c.default_date),
            t["algorithm"].as_str().unwrap_or("nearest"),
            t["objective"].as_str().unwrap_or("time")
        ),
        String::new(),
        format!(
            "**Mode:** `DEM_KNOWN_POSE_MISSION_SIM` (known-pose mission simulation; not SLAM / not real-rover \
             autonomy) · **Plan feasibility:** {}",
            if feasible {
                "**FEASIBLE**".to_owned()
            } else {
                format!(
                    "⚠ **INFEASIBLE** — {} route leg(s) have no safe corridor",
                    py(&t["blocked_legs"])
                )
            }
        ),
        String::new(),
        "## Sequence".to_owned(),
        "| # | Trip | kind | Site (x,y) | Mass t | Duration | Energy (chg) |".to_owned(),
        "|---|------|------|-----------|--------|----------|--------------|".to_owned(),
    ];
    for (i, pt) in plan.times.iter().enumerate() {
        let tr = &plan.trips[pt.trip];
        let e = tr.dig_e + tr.haul_m * c.drive_j_per_m + tr.lift_e;
        md.push(format!(
            "| {} | {} | {} | ({:.0},{:.0}) | {:.2} | {} | {:.1} |",
            i + 1,
            tr.label,
            tr.kind.name(),
            tr.site.0,
            tr.site.1,
            tr.mass_kg / 1000.0,
            dur(pt.t_end - pt.t_start),
            e / c.battery_j
        ));
    }
    let lift = num(t, "lift_energy_J");
    let (survival, energy) = (num(t, "survival_energy_J"), num(t, "energy_J"));
    md.extend([
        String::new(),
        "## Material balance".to_owned(),
        format!(
            "- cut **{:.1} t** → fill **{:.1} t** · surplus(spoil) {:.1} t · deficit(import) {:.1} t · sinter {:.2} t",
            num(t, "cut_kg") / 1000.0,
            num(t, "fill_kg") / 1000.0,
            num(t, "surplus_kg") / 1000.0,
            num(t, "deficit_kg") / 1000.0,
            num(t, "sinter_kg") / 1000.0
        ),
        String::new(),
        "## Totals".to_owned(),
        format!(
            "- Project time **{}** ({:.0} h) · moved **{:.1} t** ({:.0} drum loads)",
            dur(num(t, "time_s")),
            num(t, "time_s") / 3600.0,
            num(t, "mass_kg") / 1000.0,
            num(t, "mass_kg") / c.drum_kg
        ),
        format!(
            "- Energy **{:.1} MJ** = {:.1} charges ({} recharge stops) · drive {:.2} km{}",
            energy / 1e6,
            energy / c.battery_j,
            py(&t["charges"]),
            num(t, "distance_m") / 1000.0,
            if lift > 0.0 {
                format!(
                    " · incl. **{:.2} MJ** lifting regolith uphill (exact m·g·Δh, real DEM)",
                    lift / 1e6
                )
            } else {
                String::new()
            }
        ),
        if survival > 0.0 {
            format!(
                "- Survival/idle power **{:.1} MJ** over the sortie (@ {:.0} W continuous) **[ASSUMPTION]** -- folded \
                 into the total above",
                survival / 1e6,
                num(t, "idle_power_w")
            )
        } else {
            "- Survival/idle power **not modelled** (active legs only; set IDLE_POWER_W to include the continuous \
             heater/avionics load, the likely-dominant multi-day term) **[ASSUMPTION]**"
                .to_owned()
        },
        format!(
            "- **{} drum cycles** (offload events); drum fill SENSED from motor current (no load cell, ICE-RASSOR \
             NTRS 20210022781) -- known to ±{:.1}% when >half full, ±{:.1}% below; rover offloads at the upper \
             confidence bound",
            py(&t["drum_cycles"]),
            c.fdc_mpe_half_full * 100.0,
            c.fdc_mpe_all * 100.0
        ),
    ]);
    if t["vehicles"].as_f64().unwrap_or(1.0) > 1.0 {
        fleet(&mut md, t);
    }
    if truthy(&t["routed_haul"]) {
        let blocked = &t["blocked_legs"];
        md.push(format!(
            "- Hauls **routed around hazards** on the real Haworth slope costmap (traverse cap {:.0}°): **+{:.1}% \
             detour** over straight lines{}",
            num(t, "traverse_cap_deg"),
            num(t, "haul_detour_frac") * 100.0,
            if truthy(blocked) {
                format!(
                    "; ⚠ **{} leg(s) had NO safe corridor → plan INFEASIBLE** (route not driven; no straight-line \
                     through the hazard)",
                    py(blocked)
                )
            } else {
                String::new()
            }
        ));
    }
    if truthy(endu) {
        endurance(&mut md, endu, &m.body);
    }
    md.extend([
        String::new(),
        "## Assumptions Register".to_owned(),
        format!(
            "Every calibrated/assumed value this plan rests on ({} tagged). Review before acting.",
            c.register.len()
        ),
        String::new(),
        "| Parameter | Value | Tag | Basis |".to_owned(),
        "|---|---|---|---|".to_owned(),
    ]);
    for r in c.register {
        md.push(format!(
            "| `{}` | {} | {} | {} |",
            py(&r["name"]),
            py(&r["value"]),
            py(&r["tag"]),
            py(&r["note"])
        ));
    }
    let (gauge, wheelbase, cg) = c.geometry;
    md.extend([
        String::new(),
        "## Vehicle Configuration".to_owned(),
        format!(
            "- Vehicle: **IPEx** (ISRU Pilot Excavator) · gauge {gauge:.4} m · wheelbase {wheelbase:.2} m · CG height \
             {cg:.2} m"
        ),
        format!(
            "- Energy: dig {:.0} J/kg · drive {:.1} J/m · battery {:.2} MJ · recharge {:.0} W [CALIB]",
            c.dig_j_per_kg,
            c.drive_j_per_m,
            c.battery_j / 1e6,
            c.recharge_w
        ),
        String::new(),
        "_Grounded (bodies.json + ipex_specs + rassor_mass_model); sinter 0.92 MJ/kg; recharge 700 W + sinter-head \
         1000 W are [CALIB]. REVIEW-PENDING — not approved for execution until signed off._"
            .to_owned(),
    ]);
    md.join("\n")
}

#[cfg(test)]
mod tests {
    use super::{dur, title};

    #[test]
    fn durations_and_titles_print_as_the_python() {
        assert_eq!(dur(3600.0 * 47.9), "47.9 h");
        assert_eq!(dur(3600.0 * 48.0), "2.0 d");
        assert_eq!(title("moon"), "Moon");
        assert_eq!(title("bp1_testbed"), "Bp1_Testbed");
    }
}
