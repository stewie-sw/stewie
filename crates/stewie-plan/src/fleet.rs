//! Multi-vehicle allocation and space-time deconfliction (Python `lode.planner_multivehicle`, RW-33d2): the
//! pure geometry `plan_multi` runs over the per-vehicle simulations. Trips are allocated site-exclusively
//! (whole site groups, longest work first, to the least-loaded rover); the shared charger and every declared
//! resource are scheduled jointly against one capacity ledger by one per-vehicle delay clock; space-time
//! crowding, cross-vehicle precedence and raised-observation vantages each add a first-come wait. A rover's
//! real finish is its simulated time plus every wait.
//!
//! The Python keys a trip back to its global index by object identity; here each vehicle's simulation runs
//! over the global trip list, so [`TripTimes::trip`] is already the global index.

use std::collections::BTreeMap;

use crate::mission::{Observation, SharedResource};
use crate::sim::{Core, Span, SpanKind, TripTimes};
use crate::trips::Trip;

/// One rover's sequenced and simulated share of the mission.
#[derive(Debug, Clone, PartialEq)]
pub struct VehiclePlan {
    pub vehicle: usize,
    /// Global trip indices in visit order.
    pub trips: Vec<usize>,
    pub tl: Vec<Span>,
    /// Per-trip windows; `trip` is the global index.
    pub times: Vec<TripTimes>,
    pub core: Core,
}

/// A trip's work energy (dig plus haul; sinter is refused upstream), the load the allocation balances.
fn work_e(t: &Trip) -> f64 {
    t.dig_e + t.haul_e
}

/// Site-exclusive, longest-first allocation of trips to `vehicles` rovers: trips at one site stay together
/// and whole groups go to the least-loaded rover (ties to the lower index). Some lists may be empty.
#[must_use]
pub fn allocate_trips(trips: &[Trip], vehicles: usize) -> Vec<Vec<usize>> {
    let mut groups: Vec<((f64, f64), Vec<usize>)> = Vec::new();
    for (i, t) in trips.iter().enumerate() {
        match groups.iter_mut().find(|(s, _)| *s == t.site) {
            Some((_, g)) => g.push(i),
            None => groups.push((t.site, vec![i])),
        }
    }
    let cost = |g: &[usize]| g.iter().map(|&i| work_e(&trips[i])).sum::<f64>();
    let mut groups: Vec<Vec<usize>> = groups.into_iter().map(|(_, g)| g).collect();
    // stable, like Python's sorted(reverse=True): equal costs keep first-seen order
    groups.sort_by(|a, b| cost(b).total_cmp(&cost(a)));
    let mut loads = vec![0.0_f64; vehicles];
    let mut alloc = vec![Vec::new(); vehicles];
    for g in groups {
        let v = (0..vehicles).fold(0, |best, k| if loads[k] < loads[best] { k } else { best });
        loads[v] += cost(&g);
        alloc[v].extend(g);
    }
    alloc
}

/// Two different rovers whose trip windows overlap at the same site (0 by site-exclusive construction).
#[must_use]
pub fn vehicle_conflicts(per: &[VehiclePlan], trips: &[Trip]) -> usize {
    let spans: Vec<(usize, (f64, f64), f64, f64)> = per
        .iter()
        .enumerate()
        .flat_map(|(v, p)| {
            p.times
                .iter()
                .map(move |w| (v, trips[w.trip].site, w.t_start, w.t_end))
        })
        .collect();
    pairs_where(&spans, |a, b| {
        a.0 != b.0 && a.1 == b.1 && a.2 < b.3 && b.2 < a.3
    })
}

/// Two different rovers charging at overlapping times.
#[must_use]
pub fn charger_conflicts(per: &[VehiclePlan]) -> usize {
    let charges: Vec<(usize, f64, f64)> = per
        .iter()
        .enumerate()
        .flat_map(|(v, p)| {
            p.tl.iter()
                .filter(|s| s.kind == SpanKind::Charge)
                .map(move |s| (v, s.t0, s.t1))
        })
        .collect();
    pairs_where(&charges, |a, b| a.0 != b.0 && a.1 < b.2 && b.1 < a.2)
}

fn pairs_where<T>(xs: &[T], hit: impl Fn(&T, &T) -> bool) -> usize {
    (0..xs.len())
        .map(|a| (a + 1..xs.len()).filter(|&b| hit(&xs[a], &xs[b])).count())
        .sum()
}

fn stationary(s: &Span) -> bool {
    (s.from.0 - s.to.0).abs() < 1e-9 && (s.from.1 - s.to.1).abs() < 1e-9
}

/// Every non-charge stationary span (work, offload, wait) as (vehicle, at, t0, t1).
fn stationary_spans(per: &[VehiclePlan]) -> Vec<(usize, (f64, f64), f64, f64)> {
    per.iter()
        .enumerate()
        .flat_map(|(v, p)| {
            p.tl.iter()
                .filter(|s| s.kind != SpanKind::Charge && stationary(s))
                .map(move |s| (v, s.from, s.t0, s.t1))
        })
        .collect()
}

/// A moving drive leg: (vehicle, from, to, t0, t1).
type Leg = (usize, (f64, f64), (f64, f64), f64, f64);

/// Every moving drive leg.
fn moving_legs(per: &[VehiclePlan]) -> Vec<Leg> {
    per.iter()
        .enumerate()
        .flat_map(|(v, p)| {
            p.tl.iter()
                .filter(|s| s.kind == SpanKind::Drive && !stationary(s))
                .map(move |s| (v, s.from, s.to, s.t0, s.t1))
        })
        .collect()
}

fn dist(a: (f64, f64), b: (f64, f64)) -> f64 {
    (a.0 - b.0).hypot(a.1 - b.1)
}

/// Two different rovers working within `proximity_m` of each other at overlapping times.
#[must_use]
pub fn temporal_conflicts(per: &[VehiclePlan], proximity_m: f64) -> usize {
    pairs_where(&stationary_spans(per), |a, b| {
        a.0 != b.0 && a.2 < b.3 && b.2 < a.3 && dist(a.1, b.1) < proximity_m
    })
}

/// Two different rovers whose drive legs pass within `proximity_m` during overlapping times.
#[must_use]
pub fn haul_path_conflicts(per: &[VehiclePlan], proximity_m: f64) -> usize {
    pairs_where(&moving_legs(per), |a, b| {
        a.0 != b.0 && a.3 < b.4 && b.3 < a.4 && seg_seg_min_dist(a.1, a.2, b.1, b.2) < proximity_m
    })
}

/// Minimum distance between segments a0->a1 and b0->b1 (Ericson's clamped closest points).
#[must_use]
#[allow(clippy::many_single_char_names)] // Ericson's notation, as in the Python
pub fn seg_seg_min_dist(a0: (f64, f64), a1: (f64, f64), b0: (f64, f64), b1: (f64, f64)) -> f64 {
    const EPS: f64 = 1e-12;
    let dot = |p: (f64, f64), q: (f64, f64)| p.0 * q.0 + p.1 * q.1;
    let (d1, d2, r) = (
        (a1.0 - a0.0, a1.1 - a0.1),
        (b1.0 - b0.0, b1.1 - b0.1),
        (a0.0 - b0.0, a0.1 - b0.1),
    );
    let (aa, ee, f) = (dot(d1, d1), dot(d2, d2), dot(d2, r));
    let (s, t);
    if aa <= EPS && ee <= EPS {
        (s, t) = (0.0, 0.0);
    } else if aa <= EPS {
        (s, t) = (0.0, (f / ee).clamp(0.0, 1.0));
    } else {
        let c = dot(d1, r);
        if ee <= EPS {
            (s, t) = ((-c / aa).clamp(0.0, 1.0), 0.0);
        } else {
            let b = dot(d1, d2);
            let denom = aa * ee - b * b;
            let s0 = if denom > EPS {
                ((b * f - c * ee) / denom).clamp(0.0, 1.0)
            } else {
                0.0
            };
            let t0 = (b * s0 + f) / ee;
            (s, t) = if t0 < 0.0 {
                ((-c / aa).clamp(0.0, 1.0), 0.0)
            } else if t0 > 1.0 {
                (((b - c) / aa).clamp(0.0, 1.0), 1.0)
            } else {
                (s0, t0)
            };
        }
    }
    let (p, q) = (
        (a0.0 + d1.0 * s, a0.1 + d1.1 * s),
        (b0.0 + d2.0 * t, b0.1 + d2.1 * t),
    );
    (p.0 - q.0).hypot(p.1 - q.1)
}

/// A capacity ledger over named servers (Python `lode.fleet_resources.ReservationLedger`): a reservation is
/// admitted when the peak simultaneous occupancy, with it, stays within the server's capacity; windows are
/// half-open, so back-to-back holds do not overlap.
struct Ledger {
    capacity: BTreeMap<String, u64>,
    held: Vec<(String, f64, f64)>,
}

impl Ledger {
    fn admits(&self, server: &str, t0: f64, t1: f64) -> bool {
        let mut ev: Vec<(f64, i64)> = self
            .held
            .iter()
            .filter(|h| h.0 == server)
            .flat_map(|h| [(h.1, 1), (h.2, -1)])
            .chain([(t0, 1), (t1, -1)])
            .collect();
        ev.sort_by(|a, b| a.0.total_cmp(&b.0).then(a.1.cmp(&b.1)));
        let (mut cur, mut peak) = (0_i64, 0_i64);
        for (_, d) in ev {
            cur += d;
            peak = peak.max(cur);
        }
        u64::try_from(peak).unwrap_or(0) <= self.capacity[server]
    }

    fn reserve(&mut self, server: &str, t0: f64, t1: f64) {
        if self.admits(server, t0, t1) {
            self.held.push((server.to_owned(), t0, t1));
        }
    }

    /// The earliest start at or after `after` at which `server` admits a hold of `dur`.
    fn earliest_start(&self, server: &str, dur: f64, after: f64) -> f64 {
        let mut cands = vec![after];
        cands.extend(
            self.held
                .iter()
                .filter(|h| h.0 == server && h.2 > after)
                .map(|h| h.2),
        );
        cands.sort_by(f64::total_cmp);
        cands.dedup();
        cands
            .iter()
            .copied()
            .find(|&tau| self.admits(server, tau, tau + dur))
            .unwrap_or(cands[cands.len() - 1])
    }
}

/// The joint charger-and-resource schedule.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct JointWaits {
    /// Each rover's total accrued wait [s].
    pub delay: Vec<f64>,
    pub charger_delay: Vec<f64>,
    pub resource_delay: Vec<f64>,
    /// The wait each declared resource caused, in first-wait order (only non-zero).
    pub resource_waits: Vec<(String, f64)>,
}

/// Schedule every rover's charges (server `charger`) and its trips at declared resource sites (within
/// `tol_m`) by earliest effective arrival against one ledger; a wait on any server delays the rover's later
/// events on every server. Ties break by rover, then charger before resource, then server id.
#[must_use]
pub fn resolve_joint_resources(
    per: &[VehiclePlan],
    trips: &[Trip],
    charger_capacity: u64,
    resources: &[SharedResource],
    tol_m: f64,
) -> JointWaits {
    let n = per.len();
    let mut ledger = Ledger {
        capacity: BTreeMap::from([("charger".to_owned(), charger_capacity.max(1))]),
        held: Vec::new(),
    };
    for r in resources {
        ledger.capacity.insert(r.id.clone(), r.capacity.max(1));
    }
    let near = |site: (f64, f64), pts: &[(f64, f64)]| {
        pts.iter()
            .any(|p| (site.0 - p.0).abs() <= tol_m && (site.1 - p.1).abs() <= tol_m)
    };
    // (vehicle, t0, dur, server, is_resource)
    let mut segs: Vec<(usize, f64, f64, &str, u8)> = Vec::new();
    for (v, p) in per.iter().enumerate() {
        for s in p.tl.iter().filter(|s| s.kind == SpanKind::Charge) {
            if s.t1 > s.t0 {
                segs.push((v, s.t0, s.t1 - s.t0, "charger", 0));
            }
        }
        for r in resources {
            for w in &p.times {
                if near(trips[w.trip].site, &r.sites) && w.t_end > w.t_start {
                    segs.push((v, w.t_start, w.t_end - w.t_start, &r.id, 1));
                }
            }
        }
    }
    let mut out = JointWaits {
        delay: vec![0.0; n],
        charger_delay: vec![0.0; n],
        resource_delay: vec![0.0; n],
        resource_waits: Vec::new(),
    };
    let mut placed = vec![false; segs.len()];
    loop {
        let key = |k: usize| {
            let (v, t0, _, sid, kind) = segs[k];
            (t0 + out.delay[v], v, kind, sid)
        };
        let best = (0..segs.len()).filter(|&k| !placed[k]).reduce(|b, k| {
            let (kb, kk) = (key(b), key(k));
            let less =
                kk.0.total_cmp(&kb.0)
                    .then(kk.1.cmp(&kb.1))
                    .then(kk.2.cmp(&kb.2))
                    .then(kk.3.cmp(kb.3))
                    .is_lt();
            if less { k } else { b }
        });
        let Some(best) = best else { break };
        let (v, t0, dur, sid, kind) = segs[best];
        let arr = t0 + out.delay[v];
        let start = ledger.earliest_start(sid, dur, arr);
        let wait = start - arr;
        if wait > 0.0 {
            out.delay[v] += wait;
            if kind == 0 {
                out.charger_delay[v] += wait;
            } else {
                out.resource_delay[v] += wait;
                match out.resource_waits.iter_mut().find(|(id, _)| id == sid) {
                    Some((_, w)) => *w += wait,
                    None => out.resource_waits.push((sid.to_owned(), wait)),
                }
            }
        }
        ledger.reserve(sid, start, start + dur);
        placed[best] = true;
    }
    out.resource_waits.retain(|(_, w)| *w > 0.0);
    out
}

/// Resolve space-time crowding: of two rovers working within `proximity_m` (stationary spans) or driving
/// within it (moving legs) at overlapping times, the higher index waits until the lower's span clears.
/// Iterated to a fixed point (at most `max_iter` passes).
#[must_use]
pub fn resolve_spacetime_crowding(
    per: &[VehiclePlan],
    proximity_m: f64,
    max_iter: usize,
) -> Vec<f64> {
    let n = per.len();
    let mut delay = vec![0.0; n];
    // the crowding spans, including charger-side waits, exactly as the two detectors select them
    let stat = stationary_spans(per);
    let mv = moving_legs(per);
    let mut pairs: Vec<(usize, usize, f64, f64, f64, f64)> = Vec::new();
    for a in &stat {
        for b in &stat {
            if a.0 < b.0 && dist(a.1, b.1) < proximity_m {
                pairs.push((a.0, b.0, a.2, a.3, b.2, b.3));
            }
        }
    }
    for a in &mv {
        for b in &mv {
            if a.0 < b.0 && seg_seg_min_dist(a.1, a.2, b.1, b.2) < proximity_m {
                pairs.push((a.0, b.0, a.3, a.4, b.3, b.4));
            }
        }
    }
    if pairs.is_empty() {
        return delay;
    }
    for _ in 0..max_iter {
        let mut next = delay.clone();
        for &(vi, vj, wt0, wt1, lt0, lt1) in &pairs {
            let (wi0, wi1) = (wt0 + delay[vi], wt1 + delay[vi]);
            let (lj0, lj1) = (lt0 + delay[vj], lt1 + delay[vj]);
            if wi0 < lj1 && lj0 < wi1 {
                let need = wi1 - lj0;
                if need > 0.0 {
                    next[vj] = next[vj].max(delay[vj] + need);
                }
            }
        }
        if next == delay {
            break;
        }
        delay = next;
    }
    delay
}

/// Hold each cross-vehicle precedence edge (global trip `i` before `j`): the dependent rover waits until
/// its leg starts at or after the predecessor's leg ends. Intra-vehicle edges are the sequencer's.
#[must_use]
pub fn resolve_cross_vehicle_precedence(
    per: &[VehiclePlan],
    precedence: &[(usize, usize)],
) -> Vec<f64> {
    let n = per.len();
    let mut delay = vec![0.0; n];
    if precedence.is_empty() {
        return delay;
    }
    let mut veh_of = BTreeMap::new();
    let mut win = BTreeMap::new();
    for (v, p) in per.iter().enumerate() {
        for &g in &p.trips {
            veh_of.insert(g, v);
        }
        for w in &p.times {
            win.insert(w.trip, (w.t_start, w.t_end));
        }
    }
    let cross: Vec<(usize, f64, usize, f64)> = precedence
        .iter()
        .filter_map(|&(i, j)| {
            let (vi, vj) = (*veh_of.get(&i)?, *veh_of.get(&j)?);
            let (wi, wj) = (win.get(&i)?, win.get(&j)?);
            (vi != vj).then_some((vi, wi.1, vj, wj.0))
        })
        .collect();
    for _ in 0..=n {
        let mut next = delay.clone();
        for &(pv, pend, dv, dstart) in &cross {
            let (ep, ed) = (pend + delay[pv], dstart + delay[dv]);
            if ed < ep {
                next[dv] = next[dv].max(delay[dv] + (ep - ed));
            }
        }
        if next == delay {
            break;
        }
        delay = next;
    }
    delay
}

/// Union-find root with path halving.
fn find(p: &mut [usize], mut x: usize) -> usize {
    while p[x] != x {
        p[x] = p[p[x]];
        x = p[x];
    }
    x
}

/// The vantage schedule of the raised observations.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct VantageWaits {
    pub delay: Vec<f64>,
    /// Each vantage's member observations (indices into the declared list), by vantage number.
    pub vantages: Vec<(String, Vec<usize>)>,
}

/// Raised observations reserve a capacity-1 vantage; observations within `exclusion_radius_m` (transitively)
/// share one. Each is placed first-come by effective arrival; the wait delays that rover.
///
/// # Errors
/// A vehicle index outside the fleet, or an empty window.
pub fn resolve_observation_vantages(
    n: usize,
    observations: &[Observation],
    exclusion_radius_m: f64,
) -> Result<VantageWaits, String> {
    let mut out = VantageWaits {
        delay: vec![0.0; n],
        vantages: Vec::new(),
    };
    if observations.is_empty() {
        return Ok(out);
    }
    let m = observations.len();
    let mut obs = Vec::with_capacity(m);
    for (k, o) in observations.iter().enumerate() {
        let v = usize::try_from(o.vehicle)
            .ok()
            .filter(|&v| v < n)
            .ok_or_else(|| {
                format!(
                    "observations[{k}] vehicle {} out of range for a {n}-vehicle fleet",
                    o.vehicle
                )
            })?;
        if o.t_end <= o.t_start {
            // the Python's message prints the bounds as Python floats
            let r = |x: f64| stewie_twin::pyjson::float_repr(x).unwrap_or_else(|_| x.to_string());
            return Err(format!(
                "observations[{k}] window [{}, {}) is empty/negative",
                r(o.t_start),
                r(o.t_end)
            ));
        }
        obs.push((v, (o.x, o.y), o.t_start, o.t_end));
    }
    let mut parent: Vec<usize> = (0..m).collect();
    for i in 0..m {
        for j in i + 1..m {
            if dist(obs[i].1, obs[j].1) <= exclusion_radius_m {
                let (ri, rj) = (find(&mut parent, i), find(&mut parent, j));
                if ri != rj {
                    parent[ri] = rj;
                }
            }
        }
    }
    let mut members: BTreeMap<usize, Vec<usize>> = BTreeMap::new();
    for k in 0..m {
        let r = find(&mut parent, k);
        members.entry(r).or_default().push(k);
    }
    let vid: BTreeMap<usize, String> = members
        .keys()
        .enumerate()
        .map(|(c, &root)| (root, format!("vantage{c}")))
        .collect();
    let mut ledger = Ledger {
        capacity: vid.values().map(|v| (v.clone(), 1)).collect(),
        held: Vec::new(),
    };
    let mut placed = vec![false; m];
    loop {
        let best = (0..m).filter(|&k| !placed[k]).reduce(|b, k| {
            let (kb, kk) = (
                obs[b].2 + out.delay[obs[b].0],
                obs[k].2 + out.delay[obs[k].0],
            );
            if kk.total_cmp(&kb).then(obs[k].0.cmp(&obs[b].0)).is_lt() {
                k
            } else {
                b
            }
        });
        let Some(best) = best else { break };
        let (v, _, t0, t1) = obs[best];
        let id = &vid[&find(&mut parent, best)];
        let arr = t0 + out.delay[v];
        let start = ledger.earliest_start(id, t1 - t0, arr);
        out.delay[v] += start - arr;
        ledger.reserve(id, start, start + (t1 - t0));
        placed[best] = true;
    }
    out.vantages = members
        .into_iter()
        .map(|(root, idxs)| (vid[&root].clone(), idxs))
        .collect();
    Ok(out)
}

/// A rover's health rollup.
#[derive(Debug, Clone, PartialEq)]
pub struct Health {
    pub feasible: bool,
    /// The lowest battery fraction reached, rounded to 3 places.
    pub min_batt_frac: f64,
    pub charges: u64,
    /// `stranded`, `low_margin` (below 15 % at some point) or `nominal`.
    pub health: &'static str,
    /// The first three reasons.
    pub infeasible_reasons: Vec<String>,
}

#[must_use]
pub fn rover_health(p: &VehiclePlan) -> Health {
    let full = p.tl.iter().map(|s| s.batt0).fold(0.0, f64::max);
    let lowest = p.tl.iter().map(|s| s.batt1).reduce(f64::min);
    let min_frac = match lowest {
        Some(b) if full > 1e-9 => b / full,
        _ => 1.0,
    };
    let health = if !p.core.feasible {
        "stranded"
    } else if min_frac < 0.15 {
        "low_margin"
    } else {
        "nominal"
    };
    Health {
        feasible: p.core.feasible,
        min_batt_frac: stewie_twin::numpy::round(min_frac, 3),
        charges: p.core.charges,
        health,
        infeasible_reasons: p.core.infeasible_reasons.iter().take(3).cloned().collect(),
    }
}
