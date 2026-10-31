//! Terrain-aware traverse planning (Python `lode.planner_routing`): a slope costmap where steeper ground
//! costs more per metre (`1 + alpha * tan(slope)`) and ground past the slope cap, or overlooking a
//! drop-off, is impassable; keep-out shapes; an 8-connected least-cost route that never cuts a corner
//! between two blocked cells; and route legs that widen their search window until a corridor is found
//! or the whole DEM has been searched. Optional illumination and map-uncertainty layers add soft cost,
//! each kept as its own inspectable term, and never change passability.

pub mod costmap;
pub mod profile;
pub mod route;

/// Bilinear height at fractional `(row, col)` of a row-major grid (inside the grid).
#[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)]
pub(crate) fn bilinear(z: &[f64], width: usize, height: usize, row: f64, col: f64) -> f64 {
    let (r0, c0) = (
        (row.floor() as usize).min(height - 2),
        (col.floor() as usize).min(width - 2),
    );
    #[allow(clippy::cast_precision_loss)]
    let (tr, tc) = (row - r0 as f64, col - c0 as f64);
    let at = |r: usize, c: usize| z[r * width + c];
    (1.0 - tr) * ((1.0 - tc) * at(r0, c0) + tc * at(r0, c0 + 1))
        + tr * ((1.0 - tc) * at(r0 + 1, c0) + tc * at(r0 + 1, c0 + 1))
}
