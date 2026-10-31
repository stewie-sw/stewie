//! Cut-fill balance (Python `lode.planner_balance`, RW-33b): route excavated regolith to fills at the least haul
//! cost. A cut excavates bank (in-situ) material at its depth-averaged density on the loose-over-dense profile (or
//! its known in-situ density); a fill places loose spoil at the body's loose density; mass is conserved. Hauls
//! are costed by the routed distance over the real terrain, an unreachable pair is no arc, and the allocation is
//! an exact min-cost transportation. Fill demand no cut can reach is an import; cut mass no fill takes is spoil.
//!
//! Terrain is required (D-R85): the Python's straight-line nearest-first fallback without a DEM is not ported.

use std::collections::HashMap;

use stewie_traverse::costmap::CostmapOptions;
use stewie_traverse::route::{Dem, route_leg};
use stewie_twin::numpy;

use crate::mission::{BuildOrder, Keepout, Mission, OrderKind};

/// The regolith profile the bank density is averaged over: the loose surface density (the profile's reference),
/// the compacted deep density and the transition depth.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Profile {
    pub rho_surface: f64,
    pub rho_deep: f64,
    pub z_t_m: f64,
}

/// Depth-averaged in-situ density [kg/m^3] of a cut column `depth_m` deep, scaled to the body's loose density.
#[must_use]
pub fn insitu_bank_density(depth_m: f64, body_loose_density: f64, p: &Profile) -> f64 {
    let d = depth_m.max(0.0);
    let avg = if d <= p.z_t_m {
        p.rho_surface
    } else {
        (p.rho_surface * p.z_t_m + p.rho_deep * (d - p.z_t_m)) / d
    };
    body_loose_density * (avg / p.rho_surface)
}

/// The density a cut is costed at: its known in-situ density, else the profile average.
#[must_use]
pub fn cut_bank_density(o: &BuildOrder, body_loose_density: f64, p: &Profile) -> f64 {
    o.insitu_density_kg_m3
        .unwrap_or_else(|| insitu_bank_density(o.depth_m, body_loose_density, p))
}

/// An order's mass [kg] at density `rho`.
#[must_use]
pub fn order_mass_kg(o: &BuildOrder, rho: f64) -> f64 {
    o.footprint_m2 * o.depth_m * rho
}

/// One balance flow: `mass_kg` from cut order `cut` to fill order `fill` (indices into the mission's orders);
/// no cut is an import, no fill is spoil. `dist_m` is the straight distance (0 for an import or spoil).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Flow {
    pub cut: Option<usize>,
    pub fill: Option<usize>,
    pub mass_kg: f64,
    pub dist_m: f64,
}

/// Memoised routed distance between local sites over a DEM (Python `_make_routes`): the point router at the
/// mission's slope cap with its keep-outs; an unreached leg is infinite. Sites are rounded to 1e-6 m and the
/// distance is symmetric.
#[derive(Debug)]
pub struct Routes<'a> {
    dem: Dem<'a>,
    max_slope_deg: f64,
    keepouts: &'a [Keepout],
    cache: HashMap<[u64; 4], f64>,
}

impl<'a> Routes<'a> {
    #[must_use]
    pub fn new(dem: Dem<'a>, max_slope_deg: f64, keepouts: &'a [Keepout]) -> Self {
        Self {
            dem,
            max_slope_deg,
            keepouts,
            cache: HashMap::new(),
        }
    }

    /// Routed distance [m] from `a` to `b`, or infinity when no safe corridor exists.
    ///
    /// # Errors
    /// The router's own refusal (a malformed grid).
    pub fn distance(&mut self, a: (f64, f64), b: (f64, f64)) -> Result<f64, String> {
        let r = |p: (f64, f64)| (numpy::round(p.0, 6), numpy::round(p.1, 6));
        let (a, b) = (r(a), r(b));
        #[allow(clippy::float_cmp)] // the Python compares the rounded tuples exactly
        if a == b {
            return Ok(0.0);
        }
        let (lo, hi) = if a.0.total_cmp(&b.0).then(a.1.total_cmp(&b.1)).is_le() {
            (a, b)
        } else {
            (b, a)
        };
        let key = [
            lo.0.to_bits(),
            lo.1.to_bits(),
            hi.0.to_bits(),
            hi.1.to_bits(),
        ];
        if let Some(&d) = self.cache.get(&key) {
            return Ok(d);
        }
        let opts = CostmapOptions {
            max_slope_deg: self.max_slope_deg,
            slip_alpha: 2.0,
            max_drop_m: None,
            illumination: None,
            map_uncertainty: None,
        };
        let leg = route_leg(self.dem, lo, hi, &opts, 20.0, self.keepouts)?;
        let d = if leg.reached {
            leg.routed_m
        } else {
            f64::INFINITY
        };
        self.cache.insert(key, d);
        Ok(d)
    }
}

/// Allocate the mission's cut mass to its fills. Returns the flows (routed cut-to-fill pairs in cut, fill order;
/// then imports by fill; then spoil by cut) and the total spoil [kg].
///
/// # Errors
/// The router's refusal.
pub fn balance(
    m: &Mission,
    body_density: f64,
    p: &Profile,
    routes: &mut Routes<'_>,
) -> Result<(Vec<Flow>, f64), String> {
    let cuts: Vec<(usize, f64)> = m
        .orders
        .iter()
        .enumerate()
        .filter(|(_, o)| o.kind == OrderKind::Cut)
        .map(|(i, o)| (i, order_mass_kg(o, cut_bank_density(o, body_density, p))))
        .collect();
    let fills: Vec<(usize, f64)> = m
        .orders
        .iter()
        .enumerate()
        .filter(|(_, o)| o.kind == OrderKind::Fill)
        .map(|(i, o)| (i, order_mass_kg(o, body_density)))
        .collect();
    let at = |i: usize| (m.orders[i].x, m.orders[i].y);
    let straight = |a: usize, b: usize| (at(a).0 - at(b).0).hypot(at(a).1 - at(b).1);
    let mut flows = Vec::new();
    if cuts.is_empty() || fills.is_empty() {
        // nothing to pair: every fill is imported, every cut is spoil
        flows.extend(fills.iter().filter(|f| f.1 > 1e-6).map(|&(j, mass)| Flow {
            cut: None,
            fill: Some(j),
            mass_kg: mass,
            dist_m: 0.0,
        }));
        flows.extend(cuts.iter().filter(|c| c.1 > 1e-6).map(|&(i, mass)| Flow {
            cut: Some(i),
            fill: None,
            mass_kg: mass,
            dist_m: 0.0,
        }));
    } else {
        let mut cost = Vec::with_capacity(cuts.len());
        for &(i, _) in &cuts {
            cost.push(
                fills
                    .iter()
                    .map(|&(j, _)| routes.distance(at(i), at(j)))
                    .collect::<Result<Vec<_>, _>>()?,
            );
        }
        let sup: Vec<f64> = cuts.iter().map(|c| c.1).collect();
        let dem: Vec<f64> = fills.iter().map(|f| f.1).collect();
        let (flow, unmet, leftover) = mincost_transport(&sup, &dem, &cost);
        for (a, &(i, _)) in cuts.iter().enumerate() {
            for (b, &(j, _)) in fills.iter().enumerate() {
                if flow[a][b] > 1e-6 {
                    flows.push(Flow {
                        cut: Some(i),
                        fill: Some(j),
                        mass_kg: flow[a][b],
                        dist_m: straight(i, j),
                    });
                }
            }
        }
        for (b, &(j, _)) in fills.iter().enumerate() {
            if unmet[b] > 1e-6 {
                flows.push(Flow {
                    cut: None,
                    fill: Some(j),
                    mass_kg: unmet[b],
                    dist_m: 0.0,
                });
            }
        }
        for (a, &(i, _)) in cuts.iter().enumerate() {
            if leftover[a] > 1e-6 {
                flows.push(Flow {
                    cut: Some(i),
                    fill: None,
                    mass_kg: leftover[a],
                    dist_m: 0.0,
                });
            }
        }
    }
    let surplus = flows
        .iter()
        .filter(|f| f.cut.is_some() && f.fill.is_none())
        .map(|f| f.mass_kg)
        .sum();
    Ok((flows, surplus))
}

/// An exact min-cost transportation over a bipartite cut-to-fill graph (Python `_mincost_transport`, P-03): route
/// the maximum reachable mass from `supplies` to `demands` and, among all such routings, the cheapest. `cost[i][j]`
/// is the per-unit haul cost; an infinite cost is no arc. Returns `(flow, unmet, leftover)`, each below 1e-9 read
/// as zero (the Python's thresholds).
///
/// Successive shortest paths over the residual graph (Bellman-Ford, since residual arcs carry negative cost):
/// each augmentation pushes the bottleneck along the cheapest source-to-sink path, so the result is a minimum-
/// cost maximum flow, the optimum the Python's linear program (`cost - M` per unit) encodes. Where several routings
/// cost the same, the flows may differ from the Python's; their total cost and throughput do not.
#[must_use]
#[allow(clippy::many_single_char_names, clippy::too_many_lines)] // graph indices: s, t, u, v, i, j
pub fn mincost_transport(
    supplies: &[f64],
    demands: &[f64],
    cost: &[Vec<f64>],
) -> (Vec<Vec<f64>>, Vec<f64>, Vec<f64>) {
    const EPS: f64 = 1e-12;
    #[derive(Clone)]
    struct Arc {
        to: usize,
        cap: f64,
        cost: f64,
        rev: usize,
    }
    let (ni, nj) = (supplies.len(), demands.len());
    let (s, t) = (ni + nj, ni + nj + 1);
    let mut g: Vec<Vec<Arc>> = vec![Vec::new(); ni + nj + 2];
    let add = |g: &mut Vec<Vec<Arc>>, u: usize, v: usize, cap: f64, cost: f64| -> (usize, usize) {
        let (iu, iv) = (g[u].len(), g[v].len());
        g[u].push(Arc {
            to: v,
            cap,
            cost,
            rev: iv,
        });
        g[v].push(Arc {
            to: u,
            cap: 0.0,
            cost: -cost,
            rev: iu,
        });
        (u, iu)
    };
    for (i, &sup) in supplies.iter().enumerate() {
        add(&mut g, s, i, sup.max(0.0), 0.0);
    }
    for (j, &dem) in demands.iter().enumerate() {
        add(&mut g, ni + j, t, dem.max(0.0), 0.0);
    }
    let mut arc_at = vec![vec![None; nj]; ni];
    for i in 0..ni {
        for j in 0..nj {
            if cost[i][j].is_finite() {
                arc_at[i][j] = Some(add(&mut g, i, ni + j, f64::INFINITY, cost[i][j]));
            }
        }
    }
    let n = g.len();
    loop {
        // cheapest residual path from s to t
        let mut dist = vec![f64::INFINITY; n];
        let mut prev: Vec<Option<(usize, usize)>> = vec![None; n];
        dist[s] = 0.0;
        for _ in 0..n {
            let mut changed = false;
            for u in 0..n {
                if !dist[u].is_finite() {
                    continue;
                }
                for (k, a) in g[u].iter().enumerate() {
                    if a.cap > EPS && dist[u] + a.cost < dist[a.to] - 1e-12 {
                        dist[a.to] = dist[u] + a.cost;
                        prev[a.to] = Some((u, k));
                        changed = true;
                    }
                }
            }
            if !changed {
                break;
            }
        }
        if !dist[t].is_finite() {
            break;
        }
        let mut push = f64::INFINITY;
        let mut v = t;
        while let Some((u, k)) = prev[v] {
            push = push.min(g[u][k].cap);
            v = u;
        }
        if push.is_nan() || push <= EPS {
            break;
        }
        let mut v = t;
        while let Some((u, k)) = prev[v] {
            g[u][k].cap -= push;
            let (to, rev) = (g[u][k].to, g[u][k].rev);
            g[to][rev].cap += push;
            v = u;
        }
    }
    let mut flow = vec![vec![0.0; nj]; ni];
    let mut sup: Vec<f64> = supplies.to_vec();
    let mut dem: Vec<f64> = demands.to_vec();
    for i in 0..ni {
        for j in 0..nj {
            if let Some((u, k)) = arc_at[i][j] {
                let a = &g[u][k];
                let f = g[a.to][a.rev].cap; // the reverse residual is the flow carried
                if f > 1e-9 {
                    flow[i][j] = f;
                    sup[i] -= f;
                    dem[j] -= f;
                }
            }
        }
    }
    let zero = |v: f64| if v > 1e-9 { v } else { 0.0 };
    (
        flow,
        dem.into_iter().map(zero).collect(),
        sup.into_iter().map(zero).collect(),
    )
}
