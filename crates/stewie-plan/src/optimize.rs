//! Sequencing (Python `lode.planner_optimize`, RW-33d1): choose the order the trips are visited in, scored by the
//! battery-aware simulation against an objective (a single metric or a weighted mix), with hard budgets as
//! penalties and order precedence honoured. Eight sequencers: nearest-neighbour, greedy, 2-opt, Or-opt, an
//! LK-style composite, brute force (exact, up to 7 trips), Held-Karp (exact on routed driving distance, up to 16)
//! and `auto`, which picks the strongest the size allows.
//!
//! Tie-breaking follows the Python everywhere a choice is made: the first of equal minima in candidate order,
//! permutations in lexicographic order, and local-search moves enumerated from the order the pass started with.

use crate::balance::Routes;
use crate::mission::Mission;
use crate::sim::{Core, simulate};
use crate::trips::{Context, Trip};

/// The objectives, each minimised (`mass` is maximised).
pub const OBJECTIVES: [&str; 8] = [
    "time",
    "duration",
    "energy",
    "average_power",
    "power",
    "distance",
    "charges",
    "mass",
];
pub const SEQUENCERS: [&str; 8] = [
    "auto",
    "nearest",
    "greedy",
    "two_opt",
    "or_opt",
    "lk",
    "brute",
    "held_karp",
];
pub const BRUTE_MAX_TRIPS: usize = 7;
pub const HELD_KARP_MAX_TRIPS: usize = 16;

/// `(minimised, raw)` value of one objective on a simulation's totals.
#[allow(clippy::cast_precision_loss)]
fn metric(core: &Core, name: &str) -> (bool, f64) {
    match name {
        "time" | "duration" => (true, core.time_s),
        "energy" => (true, core.energy_j),
        "average_power" | "power" => (true, core.avg_power_w),
        "distance" => (true, core.distance_m),
        "charges" => (true, core.charges as f64),
        _ => (false, core.mass_kg),
    }
}

/// The solver that actually runs for `(algorithm, n_trips)`: `auto` resolves by size, and brute force and
/// Held-Karp past their caps fall back to the LK-style local search.
#[must_use]
pub fn effective_algorithm(algorithm: &str, n: usize) -> &str {
    match algorithm {
        "auto" if n <= BRUTE_MAX_TRIPS => "brute",
        "auto" if n <= HELD_KARP_MAX_TRIPS => "held_karp_lk",
        "auto" => "lk",
        "brute" if n > BRUTE_MAX_TRIPS => "lk",
        "held_karp" if n > HELD_KARP_MAX_TRIPS => "lk",
        a => a,
    }
}

/// An objective spec as normalised weights, in the order given: a single name, `name:w,name:w`, or name/weight
/// pairs. Weights must be finite and non-negative with a positive sum; names known and not repeated.
///
/// # Errors
/// A malformed, unknown, repeated or non-positive spec.
pub fn parse_objective(spec: &str) -> Result<Vec<(String, f64)>, String> {
    if OBJECTIVES.contains(&spec) {
        return Ok(vec![(spec.to_owned(), 1.0)]);
    }
    let mut pairs: Vec<(String, f64)> = Vec::new();
    for part in spec.split(',') {
        let (name, w) = part.split_once(':').unwrap_or((part, ""));
        let name = name.trim();
        if pairs.iter().any(|(n, _)| n == name) {
            return Err(format!(
                "duplicate objective component {} in {}",
                py_str(name),
                py_str(spec)
            ));
        }
        let w = w.trim();
        let weight = if w.is_empty() {
            1.0
        } else {
            w.parse::<f64>().map_err(|_| {
                format!(
                    "malformed objective weight {} for {} in {}",
                    py_str(w),
                    py_str(name),
                    py_str(spec)
                )
            })?
        };
        pairs.push((name.to_owned(), weight));
    }
    normalise(pairs)
}

/// Validate and normalise name/weight pairs (an objective given as a map).
///
/// # Errors
/// As [`parse_objective`].
pub fn normalise(pairs: Vec<(String, f64)>) -> Result<Vec<(String, f64)>, String> {
    if pairs.is_empty() {
        return Err("unparseable objective (empty)".into());
    }
    for (k, v) in &pairs {
        if !OBJECTIVES.contains(&k.as_str()) {
            let mut known = OBJECTIVES.map(py_str);
            known.sort();
            return Err(format!(
                "unknown objective {}; known: [{}]",
                py_str(k),
                known.join(", ")
            ));
        }
        if !v.is_finite() || *v < 0.0 {
            return Err(format!(
                "objective weight for {} must be finite and >= 0 (got {})",
                py_str(k),
                py_float(*v)
            ));
        }
    }
    let total: f64 = pairs.iter().map(|(_, v)| v).sum();
    if !(total.is_finite() && total > 0.0) {
        return Err(format!(
            "objective weights must sum to a finite positive value (got {})",
            py_float(total)
        ));
    }
    Ok(pairs.into_iter().map(|(k, v)| (k, v / total)).collect())
}

/// Python `repr` of a string.
fn py_str(s: &str) -> String {
    stewie_twin::pyjson::repr(&serde_json::Value::String(s.to_owned()))
}

/// Python `repr` of a float, `nan` and `inf` included.
fn py_float(x: f64) -> String {
    if x.is_nan() {
        "nan".to_owned()
    } else if x.is_infinite() {
        if x > 0.0 { "inf" } else { "-inf" }.to_owned()
    } else {
        stewie_twin::pyjson::float_repr(x).unwrap_or_else(|_| x.to_string())
    }
}

fn is_only(weights: &[(String, f64)], target: &[&str]) -> bool {
    weights.len() == 1 && target.contains(&weights[0].0.as_str())
}

/// The optimality label of a resolved solver for an objective, and whether it is exact on that objective: brute
/// force is exact on any objective; Held-Karp only on routed distance.
#[must_use]
pub fn objective_optimality(resolved: &str, weights: &[(String, f64)]) -> (String, bool) {
    match resolved {
        "brute" => ("exact".into(), true),
        "held_karp" | "held_karp_lk" => {
            let polish = if resolved == "held_karp_lk" {
                "+polish"
            } else {
                ""
            };
            if is_only(weights, &["distance"]) {
                (format!("distance-exact{polish}"), true)
            } else {
                (
                    format!("distance-exact (heuristic for this objective){polish}"),
                    false,
                )
            }
        }
        _ => ("heuristic".into(), false),
    }
}

/// The penalty for overshooting a mission budget (a large constant plus the fractional overshoot, so any
/// feasible order beats any infeasible one), plus the risk weight per recharge.
#[must_use]
#[allow(clippy::cast_precision_loss)]
pub fn constraint_penalty(core: &Core, m: &Mission) -> f64 {
    let c = &m.objective_constraints;
    let mut pen = 0.0;
    for (cap_key, value) in [
        ("max_time_s", core.time_s),
        ("max_energy_J", core.energy_j),
        ("max_charges", core.charges as f64),
        ("max_distance_m", core.distance_m),
    ] {
        if let Some(&cap) = c.get(cap_key)
            && value > cap
        {
            pen += 1e6 * (1.0 + (value - cap) / cap.abs().max(1e-9));
        }
    }
    if let Some(&rw) = c.get("risk_weight") {
        pen += rw * core.charges as f64;
    }
    pen
}

/// Everything a sequencing run reads.
pub struct Sequencing<'a, 'r, 'd> {
    pub mission: &'a Mission,
    pub trips: &'a [Trip],
    pub ctx: &'a Context,
    pub routes: &'r mut Routes<'d>,
    pub precedence: &'a [(usize, usize)],
}

impl std::fmt::Debug for Sequencing<'_, '_, '_> {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Sequencing")
            .field("trips", &self.trips.len())
            .finish_non_exhaustive()
    }
}

fn straight(a: (f64, f64), b: (f64, f64)) -> f64 {
    (a.0 - b.0).hypot(a.1 - b.1)
}

impl Sequencing<'_, '_, '_> {
    fn core(&mut self, order: &[usize]) -> Result<Core, String> {
        Ok(simulate(self.mission, self.trips, order, self.ctx, self.routes)?.2)
    }

    fn pred(&self) -> Vec<u64> {
        let mut pred = vec![0u64; self.trips.len()];
        for &(i, j) in self.precedence {
            pred[j] |= 1 << i;
        }
        pred
    }

    /// Nearest-neighbour by straight distance from the charger, each step from the last trip's site; with
    /// precedence, only trips whose predecessors are placed.
    fn nn_order(&self, pred: Option<&[u64]>) -> Vec<usize> {
        let mut seq = Vec::new();
        let mut unvisited: Vec<usize> = (0..self.trips.len()).collect();
        let mut cur = self.mission.charger;
        while !unvisited.is_empty() {
            let placed = seq.iter().fold(0u64, |m, &p| m | (1u64 << p));
            let mut best: Option<(usize, f64)> = None;
            for &i in &unvisited {
                if pred.is_some_and(|p| p[i] & !placed != 0) {
                    continue;
                }
                let d = straight(cur, self.trips[i].site);
                if best.is_none_or(|(_, bd)| d < bd) {
                    best = Some((i, d));
                }
            }
            let Some((k, _)) = best else { break };
            seq.push(k);
            unvisited.retain(|&u| u != k);
            cur = self.trips[k].site;
        }
        seq
    }

    /// Exact minimum routed-driving tour (charger, every site, charger) honouring precedence.
    fn held_karp(&mut self, pred: &[u64]) -> Result<Vec<usize>, String> {
        let n = self.trips.len();
        let pts: Vec<(f64, f64)> = std::iter::once(self.mission.charger)
            .chain(self.trips.iter().map(|t| t.site))
            .collect();
        let mut dmat = vec![vec![0.0; n + 1]; n + 1];
        for a in 0..=n {
            for b in 0..=n {
                dmat[a][b] = self.routes.distance(pts[a], pts[b])?;
            }
        }
        let full = (1usize << n) - 1;
        let mut dp = vec![vec![f64::INFINITY; n]; 1 << n];
        let mut par = vec![vec![usize::MAX; n]; 1 << n];
        for j in 0..n {
            if pred[j] == 0 {
                dp[1 << j][j] = dmat[0][j + 1];
            }
        }
        for mask in 0..1usize << n {
            for j in 0..n {
                let base = dp[mask][j];
                if base.is_infinite() {
                    continue;
                }
                for k in 0..n {
                    if mask & (1 << k) != 0 || pred[k] & !(mask as u64) != 0 {
                        continue;
                    }
                    let (nm, nd) = (mask | (1 << k), base + dmat[j + 1][k + 1]);
                    if nd < dp[nm][k] {
                        dp[nm][k] = nd;
                        par[nm][k] = j;
                    }
                }
            }
        }
        let mut best = (f64::INFINITY, usize::MAX);
        for j in 0..n {
            let v = dp[full][j] + dmat[j + 1][0];
            if v < best.0 {
                best = (v, j);
            }
        }
        if best.1 == usize::MAX {
            return Err(
                "precedence is infeasible (cyclic / unsatisfiable): no valid trip ordering exists"
                    .into(),
            );
        }
        let (mut order, mut mask, mut j) = (Vec::new(), full, best.1);
        while j != usize::MAX {
            order.push(j);
            let pj = par[mask][j];
            mask ^= 1 << j;
            j = pj;
        }
        order.reverse();
        Ok(order)
    }
}

fn respects(order: &[usize], pred: &[u64]) -> bool {
    let mut seen = 0u64;
    for &j in order {
        if pred[j] & !seen != 0 {
            return false;
        }
        seen |= 1 << j;
    }
    true
}

/// The next permutation in lexicographic order, or false after the last.
fn next_permutation(p: &mut [usize]) -> bool {
    let Some(i) = (1..p.len()).rev().find(|&i| p[i - 1] < p[i]) else {
        return false;
    };
    let j = (i..p.len()).rev().find(|&j| p[j] > p[i - 1]).unwrap_or(i);
    p.swap(i - 1, j);
    p[i..].reverse();
    true
}

fn two_opt_moves(o: &[usize]) -> Vec<Vec<usize>> {
    let n = o.len();
    let mut out = Vec::new();
    for i in 0..n.saturating_sub(1) {
        for j in i + 1..n {
            let mut c = o.to_vec();
            c[i..=j].reverse();
            out.push(c);
        }
    }
    out
}

fn or_opt_moves(o: &[usize]) -> Vec<Vec<usize>> {
    let n = o.len();
    let mut out = Vec::new();
    for seg in 1..=3usize {
        if seg > n {
            continue;
        }
        for i in 0..=n - seg {
            let chunk = &o[i..i + seg];
            let rest: Vec<usize> = o[..i].iter().chain(&o[i + seg..]).copied().collect();
            for k in 0..=rest.len() {
                if k != i {
                    let mut c = rest[..k].to_vec();
                    c.extend_from_slice(chunk);
                    c.extend_from_slice(&rest[k..]);
                    out.push(c);
                }
            }
        }
    }
    out
}

/// A visit order for the trips chosen by `algorithm` against `objective` (a parsed spec), honouring precedence.
///
/// # Errors
/// An unknown algorithm, infeasible precedence for Held-Karp, or a routing refusal.
#[allow(clippy::too_many_lines)] // the dispatcher and its eight solvers, in the Python's order
pub fn optimize_sequence(
    s: &mut Sequencing<'_, '_, '_>,
    algorithm: &str,
    objective: &[(String, f64)],
) -> Result<Vec<usize>, String> {
    let n = s.trips.len();
    if n <= 1 {
        return Ok((0..n).collect());
    }
    if n > 63 {
        return Err(format!(
            "{n} trips exceed the 63 a precedence mask can hold"
        ));
    }
    let pred = s.pred();
    let has_prec = pred.iter().any(|&p| p != 0);
    let pmask = has_prec.then_some(pred.as_slice());
    // the multi-objective scale reference: the nearest-neighbour order, ignoring precedence
    let reference = if objective.len() > 1 {
        let o = s.nn_order(None);
        Some(s.core(&o)?)
    } else {
        None
    };
    let weights = objective.to_vec();
    let score_core = move |core: &Core, m: &Mission| -> f64 {
        let base = match &reference {
            None => {
                let (min, raw) = metric(core, &weights[0].0);
                if min { raw } else { -raw }
            }
            Some(r) => weights
                .iter()
                .map(|(name, w)| {
                    let ((min, raw), (_, rv)) = (metric(core, name), metric(r, name));
                    let norm = if raw.abs() <= 1e-9 && rv.abs() <= 1e-9 {
                        1.0
                    } else if min {
                        raw / rv.max(1e-9)
                    } else {
                        rv.max(0.0) / raw.max(1e-9)
                    };
                    w * norm
                })
                .sum(),
        };
        base + constraint_penalty(core, m)
    };
    let mut score = |s: &mut Sequencing<'_, '_, '_>, order: &[usize]| -> Result<f64, String> {
        let core = s.core(order)?;
        Ok(score_core(&core, s.mission))
    };
    let algorithm = if algorithm == "auto" && n <= BRUTE_MAX_TRIPS {
        "brute"
    } else {
        effective_algorithm(algorithm, n)
    };
    match algorithm {
        "nearest" => return Ok(s.nn_order(pmask)),
        "held_karp" if n <= HELD_KARP_MAX_TRIPS => return s.held_karp(&pred),
        "greedy" => {
            let mut order: Vec<usize> = Vec::new();
            let mut unvisited: Vec<usize> = (0..n).collect();
            while !unvisited.is_empty() {
                let placed = order.iter().fold(0u64, |m, &p| m | (1u64 << p));
                let mut best: Option<(usize, f64)> = None;
                for &i in &unvisited {
                    if has_prec && pred[i] & !placed != 0 {
                        continue;
                    }
                    let mut cand = order.clone();
                    cand.push(i);
                    let v = score(s, &cand)?;
                    if best.is_none_or(|(_, bv)| v < bv) {
                        best = Some((i, v));
                    }
                }
                let Some((k, _)) = best else {
                    return Err("precedence is infeasible: no eligible trip".into());
                };
                order.push(k);
                unvisited.retain(|&u| u != k);
            }
            return Ok(order);
        }
        "brute" if n <= BRUTE_MAX_TRIPS => {
            let mut p: Vec<usize> = (0..n).collect();
            let mut best: Option<(Vec<usize>, f64)> = None;
            loop {
                if !has_prec || respects(&p, &pred) {
                    let v = score(s, &p)?;
                    if best.as_ref().is_none_or(|(_, bv)| v < *bv) {
                        best = Some((p.clone(), v));
                    }
                }
                if !next_permutation(&mut p) {
                    break;
                }
            }
            return best
                .map(|b| b.0)
                .ok_or_else(|| "precedence is infeasible: no valid trip ordering exists".into());
        }
        _ => {}
    }
    #[allow(clippy::type_complexity)]
    // the scorer is borrowed mutably alongside the sequencing state
    let local_search =
        |s: &mut Sequencing<'_, '_, '_>,
         seed: Vec<usize>,
         two: bool,
         or: bool,
         score: &mut dyn FnMut(&mut Sequencing<'_, '_, '_>, &[usize]) -> Result<f64, String>|
         -> Result<Vec<usize>, String> {
            let mut order = seed;
            let mut best = score(s, &order)?;
            let mut improving = true;
            while improving {
                improving = false;
                for moves in [
                    two.then_some(two_opt_moves as fn(&[usize]) -> Vec<Vec<usize>>),
                    or.then_some(or_opt_moves),
                ]
                .into_iter()
                .flatten()
                {
                    // the moves come from the order this pass started with, as the Python's generator does
                    for cand in moves(&order.clone()) {
                        if has_prec && !respects(&cand, &pred) {
                            continue;
                        }
                        let v = score(s, &cand)?;
                        if v < best - 1e-9 {
                            order = cand;
                            best = v;
                            improving = true;
                        }
                    }
                }
            }
            Ok(order)
        };
    let nn_seed = s.nn_order(pmask);
    match algorithm {
        "two_opt" => local_search(s, nn_seed, true, false, &mut score),
        "or_opt" => local_search(s, nn_seed, false, true, &mut score),
        "held_karp_lk" => {
            let seed = s.held_karp(&pred)?;
            local_search(s, seed, true, true, &mut score)
        }
        "lk" | "brute" | "held_karp" => local_search(s, nn_seed, true, true, &mut score),
        other => Err(format!(
            "unknown algorithm {other:?}; known: {SEQUENCERS:?}"
        )),
    }
}
