//! Rover ground effects on a [`ColumnState`] (Python `stewie.physics.rover`): wheel ruts, the IPEx
//! four-wheel footprint, the excavation drum swath and the pose integrator. Geometry- and state-accurate,
//! not force-accurate: a pass raises density under the contact (capped at the compacted ceiling), so the
//! column thins and the rut sinks while mass is untouched; driving over spoil firms it into a berm.
//! The vehicle geometry comes from the rover profile, never from literals here.

use crate::PhysicsError;
use crate::column::{ColumnState, StateLabel};
use crate::soil::SoilParams;
use crate::terra;

/// Wheel order of every per-wheel array here.
pub const WHEELS: [&str; 4] = ["LF", "RF", "LB", "RB"];

/// Field-space `(row, col)` contact centres of the four wheels for a pose (heading 0 = +col, pi/2 = +row).
#[must_use]
pub fn wheel_contact_points(
    center: (f64, f64),
    heading_rad: f64,
    cell_m: f64,
    gauge_m: f64,
    wheelbase_m: f64,
) -> [(f64, f64); 4] {
    let (sh, ch) = heading_rad.sin_cos();
    let (fwd, lat) = ((sh, ch), (ch, -sh));
    let (hb, hg) = (0.5 * wheelbase_m / cell_m, 0.5 * gauge_m / cell_m);
    [(1.0, 1.0), (1.0, -1.0), (-1.0, 1.0), (-1.0, -1.0)].map(|(fs, ls): (f64, f64)| {
        let off = (
            fs * hb * fwd.0 + ls * hg * lat.0,
            fs * hb * fwd.1 + ls * hg * lat.1,
        );
        (center.0 + off.0, center.1 + off.1)
    })
}

/// Mark the disc of `half_w` cells around `center` into `mask`.
#[allow(clippy::cast_precision_loss)] // grid indices are far below 2^52
fn mark_disc(cs: &ColumnState, mask: &mut [bool], center: (f64, f64), half_w: f64) {
    let w = cs.width();
    for (i, m) in mask.iter_mut().enumerate() {
        let (dr, dc) = ((i / w) as f64 - center.0, (i % w) as f64 - center.1);
        if dr * dr + dc * dc <= half_w * half_w {
            *m = true;
        }
    }
}

fn swath(cs: &ColumnState, centres: &[(f64, f64)], half_w: f64) -> Vec<bool> {
    let mut m = vec![false; cs.width() * cs.height()];
    for &c in centres {
        mark_disc(cs, &mut m, c, half_w);
    }
    m
}

/// Relabel and disturb every touched cell: spoil (as it was before the pass) firms into a berm, anything
/// else becomes tread.
fn mark_traffic(cs: &mut ColumnState, touched: &[bool], spoil_before: &[bool]) {
    let f = cs.fields_mut();
    for i in (0..touched.len()).filter(|&i| touched[i]) {
        f.state_label[i] = if spoil_before[i] {
            StateLabel::CompactedBerm
        } else {
            StateLabel::Tread
        } as u8;
        f.disturbance[i] = (f.disturbance[i] + 0.35).clamp(0.0, 1.0);
    }
}

fn spoil_mask(cs: &ColumnState) -> Vec<bool> {
    cs.fields()
        .state_label
        .iter()
        .map(|&l| l == StateLabel::Spoil as u8)
        .collect()
}

/// One rut along `path` (a single disc footprint): density `*= 1 + compaction`, capped at `rho_deep`.
pub fn wheel_pass(
    cs: &mut ColumnState,
    path: &[(f64, f64)],
    wheel_width_m: f64,
    compaction: f64,
    rho_deep: f64,
) {
    let half_w = (0.5 * wheel_width_m / cs.cell_m()).max(0.5);
    let touched = swath(cs, path, half_w);
    if !touched.contains(&true) {
        return;
    }
    let spoil = spoil_mask(cs);
    let f = cs.fields_mut();
    for i in (0..touched.len()).filter(|&i| touched[i]) {
        f.density[i] = (f.density[i] * (1.0 + compaction)).min(rho_deep);
    }
    mark_traffic(cs, &touched, &spoil);
}

/// Dense straight `(row, col)` path between two cells (numpy `linspace` rounded half to even).
#[must_use]
#[allow(clippy::cast_precision_loss, clippy::cast_possible_truncation)]
pub fn straight_path(r0: i64, c0: i64, r1: i64, c1: i64, step_cells: i64) -> Vec<(i64, i64)> {
    let n = (r1 - r0).abs().max((c1 - c0).abs()) / step_cells.max(1) + 1;
    // numpy linspace: k * ((b - a) / (n - 1)) + a, with the last sample exactly b
    let lin = |a: i64, b: i64, k: i64| {
        if n == 1 {
            a as f64
        } else if k == n - 1 {
            b as f64
        } else {
            k as f64 * ((b - a) as f64 / (n - 1) as f64) + a as f64
        }
    };
    (0..n)
        .map(|k| {
            (
                lin(r0, r1, k).round_ties_even() as i64,
                lin(c0, c1, k).round_ties_even() as i64,
            )
        })
        .collect()
}

/// How a pass compacts the soil.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum Compaction {
    /// `density *= 1 + f` per pass (the Python default).
    Constant(f64),
    /// Toward the Bekker equilibrium density for each wheel's normal load [N] and slip (idempotent at a
    /// fixed load; never loosens a firmer cell).
    Physical {
        loads_n: [f64; 4],
        slip: [f64; 4],
        contact_len_m: f64,
        soil: SoilParams,
    },
}

/// Stamp the four IPEx ruts along `poses` (`((row, col), heading)`); returns each wheel's contact polyline in
/// [`WHEELS`] order. Density-only edit, so mass is unchanged.
pub fn four_wheel_pass(
    cs: &mut ColumnState,
    poses: &[((f64, f64), f64)],
    gauge_m: f64,
    wheelbase_m: f64,
    wheel_width_m: f64,
    rho_deep: f64,
    compaction: &Compaction,
) -> [Vec<(f64, f64)>; 4] {
    let half_w = (0.5 * wheel_width_m / cs.cell_m()).max(0.5);
    let mut lines: [Vec<(f64, f64)>; 4] = Default::default();
    for &(c, h) in poses {
        for (k, p) in wheel_contact_points(c, h, cs.cell_m(), gauge_m, wheelbase_m)
            .into_iter()
            .enumerate()
        {
            lines[k].push(p);
        }
    }
    let spoil = spoil_mask(cs);
    let mut any = vec![false; spoil.len()];
    for (k, line) in lines.iter().enumerate() {
        let touched = swath(cs, line, half_w);
        let f = cs.fields_mut();
        for i in (0..touched.len()).filter(|&i| touched[i]) {
            f.density[i] = match *compaction {
                Compaction::Constant(c) => (f.density[i] * (1.0 + c)).min(rho_deep),
                Compaction::Physical {
                    loads_n,
                    slip,
                    contact_len_m,
                    soil,
                } => {
                    let t = terra::compaction_target_density(
                        f.mass_areal[i],
                        loads_n[k],
                        contact_len_m,
                        wheel_width_m,
                        slip[k],
                        &soil,
                    );
                    f.density[i].max(t).min(rho_deep)
                }
            };
            any[i] = true;
        }
    }
    if any.contains(&true) {
        mark_traffic(cs, &any, &spoil);
    }
    lines
}

/// Dig a swath `width_m` wide along `swath_rc` to `depth_m` of column into the drum (labelled excavated),
/// and if `dump_rc` is given, dump what was cut there as spoil. Returns the kg excavated.
///
/// # Errors
/// A negative or non-finite depth, or a non-positive width.
pub fn drum_pass(
    cs: &mut ColumnState,
    swath_rc: &[(f64, f64)],
    depth_m: f64,
    width_m: f64,
    dump_rc: Option<&[(f64, f64)]>,
    spoil_density: f64,
) -> Result<f64, PhysicsError> {
    if !(depth_m.is_finite() && depth_m >= 0.0 && width_m.is_finite() && width_m > 0.0) {
        return Err(PhysicsError::InvalidInput(format!(
            "drum cut {depth_m} m deep, {width_m} m wide"
        )));
    }
    let half_w = (0.5 * width_m / cs.cell_m()).max(0.5);
    let cut = swath(cs, swath_rc, half_w);
    if !cut.contains(&true) {
        return Ok(0.0);
    }
    let per: Vec<f64> = cs.fields().density.iter().map(|d| depth_m * d).collect();
    let moved = cs.cut_to_inventory(&cut, &per)?;
    let f = cs.fields_mut();
    for i in (0..cut.len()).filter(|&i| cut[i]) {
        f.state_label[i] = StateLabel::Excavated as u8;
        f.disturbance[i] = (f.disturbance[i] + 0.4).clamp(0.0, 1.0);
    }
    if let Some(d) = dump_rc {
        let dump = swath(cs, d, half_w);
        if dump.contains(&true) {
            cs.dump_from_inventory(&dump, moved, spoil_density)?;
        }
    }
    Ok(moved)
}

/// Advance a differential-drive pose by one constant twist over `dt_s` (exact arc); yaw wrapped to
/// `[-pi, pi)`. Forward in `(row, col)` is `(sin yaw, cos yaw)`.
#[must_use]
pub fn step_pose(
    center: (f64, f64),
    yaw_rad: f64,
    v_mps: f64,
    omega_radps: f64,
    dt_s: f64,
    cell_m: f64,
) -> ((f64, f64), f64) {
    use std::f64::consts::PI;
    let new_yaw = yaw_rad + omega_radps * dt_s;
    let dist = v_mps * dt_s / cell_m;
    let (dr, dc) = if omega_radps.abs() < 1e-9 {
        (dist * yaw_rad.sin(), dist * yaw_rad.cos())
    } else {
        let k = (dist / dt_s) / omega_radps;
        (
            k * (yaw_rad.cos() - new_yaw.cos()),
            k * (new_yaw.sin() - yaw_rad.sin()),
        )
    };
    (
        (center.0 + dr, center.1 + dc),
        (new_yaw + PI).rem_euclid(2.0 * PI) - PI,
    )
}
