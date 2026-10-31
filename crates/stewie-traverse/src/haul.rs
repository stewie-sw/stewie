//! Haul geometry (Python `lode.planner_routing` haul and coverage helpers): elevation gain and cumulative
//! ascent along a haul read from the DEM, the outward-spiral coverage route and its terrain feasibility.
//! Where the Python returns 0 m for a site off the DEM, these return `None`: an unknown gain is not flat.

use crate::costmap::{CostmapOptions, slope_costmap};
use crate::route::{Dem, MAX_DROP_M};

/// The DEM cell nearest a local point (Python `int(round(...))`, half to even), if on the grid.
#[allow(
    clippy::cast_possible_truncation,
    clippy::cast_precision_loss,
    clippy::cast_sign_loss
)]
fn cell_at(dem: &Dem<'_>, (x, y): (f64, f64)) -> Option<usize> {
    let c = ((dem.origin.0 + x) / dem.cell_m).round_ties_even() as i64;
    let r = ((dem.origin.1 + y) / dem.cell_m).round_ties_even() as i64;
    let ok = r >= 0 && c >= 0 && (r as usize) < dem.height && (c as usize) < dem.width;
    ok.then(|| r as usize * dem.width + c as usize)
}

/// Net elevation change `z(b) - z(a)` [m]; `None` if either site is off the DEM.
#[must_use]
pub fn elevation_gain_m(dem: &Dem<'_>, a: (f64, f64), b: (f64, f64)) -> Option<f64> {
    Some(dem.z[cell_at(dem, b)?] - dem.z[cell_at(dem, a)?])
}

/// Total positive gain [m] along a waypoint polyline (descents do not regenerate). Off-DEM waypoints are
/// skipped as in the Python; `None` with fewer than two on-grid samples.
#[must_use]
pub fn cumulative_ascent_m(dem: &Dem<'_>, waypoints: &[(f64, f64)]) -> Option<f64> {
    let zs: Vec<f64> = waypoints
        .iter()
        .filter_map(|&p| cell_at(dem, p).map(|i| dem.z[i]))
        .collect();
    (zs.len() >= 2).then(|| zs.windows(2).map(|w| (w[1] - w[0]).max(0.0)).sum())
}

/// Points from `a` to `b` inclusive, no more than `step` apart.
#[allow(
    clippy::cast_possible_truncation,
    clippy::cast_sign_loss,
    clippy::cast_precision_loss
)]
fn densify(a: (f64, f64), b: (f64, f64), step: f64) -> Vec<(f64, f64)> {
    let n = ((b.0 - a.0).hypot(b.1 - a.1) / step).ceil().max(1.0) as usize;
    (0..=n)
        .map(|t| {
            (
                a.0 + (b.0 - a.0) * t as f64 / n as f64,
                a.1 + (b.1 - a.1) * t as f64 / n as f64,
            )
        })
        .collect()
}

/// Outward-spiral coverage over `bbox = (x0, y0, x1, y1)`: from the centre, nested rectangular loops
/// `swath_m` apart (clamped to the region), each closed back to its start when `close_loops` (a
/// re-observation candidate for loop closure), with waypoints no more than `min(spacing, swath)` apart.
///
/// # Errors
/// A degenerate region or a non-positive swath.
#[allow(
    clippy::cast_possible_truncation,
    clippy::cast_sign_loss,
    clippy::cast_precision_loss
)]
pub fn coverage_spiral(
    bbox: (f64, f64, f64, f64),
    swath_m: f64,
    spacing_m: Option<f64>,
    close_loops: bool,
) -> Result<Vec<(f64, f64)>, String> {
    let (x0, y0, x1, y1) = bbox;
    if !(x1 > x0 && y1 > y0) {
        return Err(format!("bbox must have positive extent; got {bbox:?}"));
    }
    if swath_m <= 0.0 {
        return Err("swath_m must be positive".into());
    }
    let step = spacing_m
        .filter(|s| *s != 0.0)
        .unwrap_or(swath_m)
        .min(swath_m)
        .max(1e-6);
    let (cx, cy, hw, hh) = (
        0.5 * (x0 + x1),
        0.5 * (y0 + y1),
        0.5 * (x1 - x0),
        0.5 * (y1 - y0),
    );
    let mut route = vec![(cx, cy)];
    let rings = (hw.max(hh) / swath_m).ceil().max(1.0) as usize;
    for k in 1..=rings {
        let (rx, ry) = ((k as f64 * swath_m).min(hw), (k as f64 * swath_m).min(hh));
        let mut corners = vec![
            (cx - rx, cy - ry),
            (cx + rx, cy - ry),
            (cx + rx, cy + ry),
            (cx - rx, cy + ry),
        ];
        if close_loops {
            corners.push(corners[0]);
        }
        for w in corners.windows(2) {
            let mut edge = densify(w[0], w[1], step);
            edge.pop(); // the next edge starts at this corner
            route.extend(edge);
        }
        route.push(corners[corners.len() - 1]);
    }
    Ok(route)
}

/// Share of `waypoints` on passable terrain (same slope cap and drop-off hazard as the router), and which.
///
/// # Errors
/// As [`slope_costmap`].
pub fn coverage_feasible(
    dem: &Dem<'_>,
    waypoints: &[(f64, f64)],
    max_slope_deg: f64,
    slip_alpha: f64,
) -> Result<(f64, Vec<bool>), String> {
    let o = CostmapOptions {
        max_slope_deg,
        slip_alpha,
        max_drop_m: Some(MAX_DROP_M),
        illumination: None,
        map_uncertainty: None,
    };
    let cm = slope_costmap(dem.z, dem.width, dem.height, dem.cell_m, &o)?;
    let flags: Vec<bool> = waypoints
        .iter()
        .map(|&p| cell_at(dem, p).is_some_and(|i| cm.passable[i]))
        .collect();
    #[allow(clippy::cast_precision_loss)]
    let frac = if flags.is_empty() {
        0.0
    } else {
        flags.iter().filter(|&&f| f).count() as f64 / flags.len() as f64
    };
    Ok((frac, flags))
}
