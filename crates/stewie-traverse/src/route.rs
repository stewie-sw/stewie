//! Least-cost routing (Python `route_least_cost`, `route_leg`).

use std::cmp::Ordering;
use std::collections::{BinaryHeap, HashMap};

use crate::costmap::{Costmap, CostmapOptions, Keepout, apply_keepouts, slope_costmap};

/// The drop-off a rover must not drive off [m]: Python `MAX_DROP_M` ([ASSUMPTION]).
pub const MAX_DROP_M: f64 = 2.0;

const NB: [(isize, isize, f64); 8] = [
    (-1, 0, 1.0),
    (1, 0, 1.0),
    (0, -1, 1.0),
    (0, 1, 1.0),
    (-1, -1, std::f64::consts::SQRT_2),
    (-1, 1, std::f64::consts::SQRT_2),
    (1, -1, std::f64::consts::SQRT_2),
    (1, 1, std::f64::consts::SQRT_2),
];

/// A min-heap entry ordered like Python's `heapq` on `(d, r, c)` tuples.
#[derive(Debug, PartialEq)]
struct Entry(f64, usize, usize);

impl Eq for Entry {}

impl Ord for Entry {
    fn cmp(&self, o: &Self) -> Ordering {
        o.0.total_cmp(&self.0)
            .then(o.1.cmp(&self.1))
            .then(o.2.cmp(&self.2))
    }
}

impl PartialOrd for Entry {
    fn partial_cmp(&self, o: &Self) -> Option<Ordering> {
        Some(self.cmp(o))
    }
}

/// A found path: cells from start to goal and its geometric length [m].
#[derive(Debug, Clone, PartialEq)]
pub struct Path {
    pub cells: Vec<(usize, usize)>,
    pub length_m: f64,
}

/// Least-cost 8-connected path (Dijkstra) from `start` to `goal` over a row-major costmap; an edge costs
/// `step * cell * mean(cost of its ends)`; a diagonal between two blocked orthogonals is never taken.
/// `None` when either end is off the grid or impassable, or no corridor exists.
#[must_use]
#[allow(clippy::cast_possible_wrap, clippy::cast_sign_loss)]
pub fn least_cost(
    cost: &[f64],
    passable: &[bool],
    width: usize,
    height: usize,
    cell_m: f64,
    start: (usize, usize),
    goal: (usize, usize),
) -> Option<Path> {
    let idx = |r: usize, c: usize| r * width + c;
    let inside = |(r, c): (usize, usize)| r < height && c < width;
    if !(inside(start)
        && inside(goal)
        && passable[idx(start.0, start.1)]
        && passable[idx(goal.0, goal.1)])
    {
        return None;
    }
    let mut dist = vec![f64::INFINITY; cost.len()];
    let mut prev: HashMap<(usize, usize), (usize, usize)> = HashMap::new();
    dist[idx(start.0, start.1)] = 0.0;
    let mut pq = BinaryHeap::from([Entry(0.0, start.0, start.1)]);
    while let Some(Entry(d, r, c)) = pq.pop() {
        if d > dist[idx(r, c)] {
            continue;
        }
        if (r, c) == goal {
            break;
        }
        for &(dr, dc, seg) in &NB {
            let (nr, nc) = (r as isize + dr, c as isize + dc);
            if nr < 0 || nc < 0 || nr >= height as isize || nc >= width as isize {
                continue;
            }
            let (nr, nc) = (nr as usize, nc as usize);
            if !passable[idx(nr, nc)] {
                continue;
            }
            if dr != 0 && dc != 0 && !(passable[idx(nr, c)] && passable[idx(r, nc)]) {
                continue; // no diagonal corner-cut between blocked orthogonals
            }
            let nd = d + seg * cell_m * 0.5 * (cost[idx(r, c)] + cost[idx(nr, nc)]);
            if nd < dist[idx(nr, nc)] {
                dist[idx(nr, nc)] = nd;
                prev.insert((nr, nc), (r, c));
                pq.push(Entry(nd, nr, nc));
            }
        }
    }
    if !dist[idx(goal.0, goal.1)].is_finite() {
        return None;
    }
    let mut cells = vec![goal];
    while *cells.last()? != start {
        cells.push(prev[cells.last()?]);
    }
    cells.reverse();
    let length_m = cells
        .windows(2)
        .map(|p| if p[0].0 != p[1].0 && p[0].1 != p[1].1 { std::f64::consts::SQRT_2 } else { 1.0 } * cell_m)
        .sum();
    Some(Path { cells, length_m })
}

/// A row-major DEM and where the local order frame sits in it.
#[derive(Debug, Clone, Copy)]
pub struct Dem<'a> {
    pub z: &'a [f64],
    pub width: usize,
    pub height: usize,
    pub cell_m: f64,
    pub origin: (f64, f64),
}

/// What [`route_leg`] returns.
#[derive(Debug, Clone, PartialEq)]
pub struct Leg {
    /// Path length [m], or the straight distance when unreached.
    pub routed_m: f64,
    /// Straight distance between the start and goal cells [m].
    pub grid_straight_m: f64,
    pub reached: bool,
    /// The terrain-following polyline in local `(x, y)`.
    pub waypoints: Vec<(f64, f64)>,
    /// Each cost term along the path, cell by cell.
    pub breakdown: Vec<(&'static str, Vec<f64>)>,
}

/// Python `int()`: truncate toward zero.
#[allow(clippy::cast_possible_truncation)]
fn trunc(v: f64) -> i64 {
    v as i64
}

/// Route between two local sites on the real DEM: crop to their box plus `margin_m`, cost it, keep out
/// the keep-outs, and search; widen the margin twofold and retry until a corridor is found or the crop is
/// the whole DEM. Endpoints off the DEM are unreachable, never clamped on.
///
/// # Errors
/// A cost layer whose size differs from the DEM.
#[allow(
    clippy::cast_possible_wrap,
    clippy::cast_sign_loss,
    clippy::cast_precision_loss,
    clippy::too_many_lines,
    clippy::cast_possible_truncation
)]
pub fn route_leg_inflated(
    dem: Dem<'_>,
    from: (f64, f64),
    to: (f64, f64),
    opts: &CostmapOptions<'_>,
    margin_m: f64,
    keepouts: &[Keepout],
    footprint_radius_m: f64,
) -> Result<Leg, String> {
    let (cell, (ox, oy)) = (dem.cell_m, dem.origin);
    let (ax, ay, bx, by) = (ox + from.0, oy + from.1, ox + to.0, oy + to.1);
    let (cols, rows) = (dem.width as i64, dem.height as i64);
    let straight = (bx - ax).hypot(by - ay);
    let miss = Leg {
        routed_m: straight,
        grid_straight_m: straight,
        reached: false,
        waypoints: vec![],
        breakdown: vec![],
    };
    let on = |v: f64, n: i64| 0.0 <= v && v < n as f64 * cell;
    if !(on(ax, cols) && on(bx, cols) && on(ay, rows) && on(by, rows)) {
        return Ok(miss);
    }
    let mut m = margin_m;
    loop {
        let c0 = trunc((ax.min(bx) - m) / cell).max(0);
        let c1 = (trunc((ax.max(bx) + m) / cell) + 1).min(cols);
        let r0 = trunc((ay.min(by) - m) / cell).max(0);
        let r1 = (trunc((ay.max(by) + m) / cell) + 1).min(rows);
        if c1 - c0 < 2 || r1 - r0 < 2 {
            return Ok(miss);
        }
        let (cw, ch) = ((c1 - c0) as usize, (r1 - r0) as usize);
        let crop_of = |layer: &[f64]| -> Vec<f64> {
            (r0..r1)
                .flat_map(|r| {
                    layer[(r * cols + c0) as usize..(r * cols + c1) as usize]
                        .iter()
                        .copied()
                })
                .collect()
        };
        let z = crop_of(dem.z);
        let illum = opts
            .illumination
            .map(|(il, g)| (crate::costmap::crop_illumination(il, &crop_of), g));
        let mu = opts.map_uncertainty.map(|(l, g)| (crop_of(l), g));
        let crop_opts = CostmapOptions {
            max_slope_deg: opts.max_slope_deg,
            slip_alpha: opts.slip_alpha,
            max_drop_m: Some(MAX_DROP_M),
            illumination: illum.as_ref().map(|(il, g)| (il, *g)),
            map_uncertainty: mu.as_ref().map(|(l, g)| (l.as_slice(), *g)),
        };
        let Costmap {
            cost,
            mut passable,
            terms,
        } = slope_costmap(&z, cw, ch, cell, &crop_opts)?;
        apply_keepouts(
            &mut passable,
            cw,
            ch,
            cell,
            (r0 as usize, c0 as usize),
            dem.origin,
            keepouts,
        );
        let clamp =
            |v: f64, lo: i64, n: usize| (trunc(v / cell) - lo).clamp(0, n as i64 - 1) as usize;
        let start = (clamp(ay, r0, ch), clamp(ax, c0, cw));
        let goal = (clamp(by, r0, ch), clamp(bx, c0, cw));
        let grid_straight = ((goal.1 as f64 - start.1 as f64) * cell)
            .hypot((goal.0 as f64 - start.0 as f64) * cell);
        // inflate hazards by the swept footprint, but keep the endpoints as the plain map has them
        let mut usable = erode(&passable, cw, ch, cell, footprint_radius_m);
        for (r, c) in [start, goal] {
            usable[r * cw + c] = passable[r * cw + c];
        }
        if let Some(p) = crate::route::least_cost(&cost, &usable, cw, ch, cell, start, goal) {
            let waypoints = p
                .cells
                .iter()
                .map(|&(r, c)| {
                    (
                        (c0 as f64 + c as f64) * cell - ox,
                        (r0 as f64 + r as f64) * cell - oy,
                    )
                })
                .collect();
            let breakdown = terms
                .into_iter()
                .map(|(n, l)| (n, p.cells.iter().map(|&(r, c)| l[r * cw + c]).collect()))
                .collect();
            return Ok(Leg {
                routed_m: p.length_m,
                grid_straight_m: grid_straight,
                reached: true,
                waypoints,
                breakdown,
            });
        }
        if c0 == 0 && c1 == cols && r0 == 0 && r1 == rows {
            return Ok(miss);
        }
        m *= 2.0;
    }
}

/// [`route_leg_inflated`] for a point agent (no footprint).
///
/// # Errors
/// As [`route_leg_inflated`].
pub fn route_leg(
    dem: Dem<'_>,
    from: (f64, f64),
    to: (f64, f64),
    opts: &CostmapOptions<'_>,
    margin_m: f64,
    keepouts: &[Keepout],
) -> Result<Leg, String> {
    route_leg_inflated(dem, from, to, opts, margin_m, keepouts, 0.0)
}

/// Configuration-space inflation: a cell stays passable only if every cell within `radius_m` (a disk) is
/// passable; outside the grid counts as blocked (scipy `minimum_filter(..., mode="constant", cval=0)`).
#[must_use]
#[allow(
    clippy::cast_possible_truncation,
    clippy::cast_sign_loss,
    clippy::cast_possible_wrap
)]
pub fn erode(
    passable: &[bool],
    width: usize,
    height: usize,
    cell_m: f64,
    radius_m: f64,
) -> Vec<bool> {
    let rad = (radius_m / cell_m).ceil() as isize;
    if radius_m <= 0.0 || rad <= 0 {
        return passable.to_vec();
    }
    let r2 = (radius_m / cell_m).powi(2);
    #[allow(clippy::cast_precision_loss)]
    let disk: Vec<(isize, isize)> = (-rad..=rad)
        .flat_map(|dy| (-rad..=rad).map(move |dx| (dy, dx)))
        .filter(|&(dy, dx)| (dy * dy + dx * dx) as f64 <= r2)
        .collect();
    let (cols, rows) = (width as isize, height as isize);
    (0..passable.len())
        .map(|i| {
            let (row, col) = ((i / width) as isize, (i % width) as isize);
            disk.iter().all(|&(dy, dx)| {
                let (rr, cc) = (row + dy, col + dx);
                rr >= 0 && cc >= 0 && rr < rows && cc < cols && passable[(rr * cols + cc) as usize]
            })
        })
        .collect()
}
