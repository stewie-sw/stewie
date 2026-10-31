//! Static tip-over assessment from the rover's terrain attitude (Python `stewie.physics.stability`): the
//! static stability angle about each axis, `atan(half_support / cg_height)`, the binding margin and a risk
//! band. Non-finite attitude fails closed (risk `Tip`).

/// Static stability angle [deg]; 90 for a CG at or below the contact plane.
#[must_use]
pub fn ssa_deg(half_support_m: f64, cg_height_m: f64) -> f64 {
    if cg_height_m <= 0.0 {
        return 90.0;
    }
    half_support_m.atan2(cg_height_m).to_degrees()
}

/// The binding tilt before tipping: the physical ceiling on a traverse-slope cap.
#[must_use]
pub fn tip_tilt_limit_deg(gauge_m: f64, wheelbase_m: f64, cg_height_m: f64) -> f64 {
    ssa_deg(gauge_m / 2.0, cg_height_m).min(ssa_deg(wheelbase_m / 2.0, cg_height_m))
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Risk {
    Ok,
    Warn,
    Tip,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Axis {
    Pitch,
    Roll,
    Unknown,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Stability {
    pub ssa_pitch_deg: f64,
    pub ssa_roll_deg: f64,
    /// Degrees of tilt left before tipping; <= 0 is tipping.
    pub margin_deg: f64,
    pub binding_axis: Axis,
    pub risk: Risk,
}

/// Assess `pitch_deg`/`roll_deg`. A fore/aft CG offset `cg_dx_m` shortens the pitch lever (conservative);
/// `warn_frac` of either SSA raises a warning.
#[must_use]
pub fn stability(
    pitch_deg: f64,
    roll_deg: f64,
    gauge_m: f64,
    wheelbase_m: f64,
    cg_height_m: f64,
    cg_dx_m: f64,
    warn_frac: f64,
) -> Stability {
    if !(pitch_deg.is_finite() && roll_deg.is_finite()) {
        return Stability {
            ssa_pitch_deg: f64::NAN,
            ssa_roll_deg: f64::NAN,
            margin_deg: f64::NEG_INFINITY,
            binding_axis: Axis::Unknown,
            risk: Risk::Tip,
        };
    }
    let ssa_pitch = ssa_deg((wheelbase_m / 2.0 - cg_dx_m.abs()).max(0.0), cg_height_m);
    let ssa_roll = ssa_deg(gauge_m / 2.0, cg_height_m);
    let (mp, mr) = (ssa_pitch - pitch_deg.abs(), ssa_roll - roll_deg.abs());
    let margin = mp.min(mr);
    let risk = if margin <= 0.0 {
        Risk::Tip
    } else if pitch_deg.abs() >= warn_frac * ssa_pitch || roll_deg.abs() >= warn_frac * ssa_roll {
        Risk::Warn
    } else {
        Risk::Ok
    };
    Stability {
        ssa_pitch_deg: ssa_pitch,
        ssa_roll_deg: ssa_roll,
        margin_deg: margin,
        binding_axis: if mp <= mr { Axis::Pitch } else { Axis::Roll },
        risk,
    }
}
