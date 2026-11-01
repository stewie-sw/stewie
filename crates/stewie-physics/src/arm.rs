//! The drum-arm posture's shift of the rover's centre of gravity (Python `stewie.specs.arm_state.ArmState
//! .cg_offset_m`): each arm's link carries a share of the dry mass and its drum carries the load, so posturing
//! the arms and loading the drums move the CG the stability model sees. The geometry values are the Python's
//! own, which it labels assumptions (render-rig consistent), not measured IPEx values.

/// Pivot to drum axis [m] (Python `ARM_LENGTH_M`, an assumption).
pub const ARM_LENGTH_M: f64 = 0.28;
/// The front and back pivots in `base_link` x [m] (Python `ARM_ORIGIN_FRONT` / `ARM_ORIGIN_BACK`).
pub const ARM_ORIGIN_FRONT_X: f64 = 0.20;
pub const ARM_ORIGIN_BACK_X: f64 = -0.20;
/// Each arm and drum's share of the dry mass (Python `ARM_MASS_FRAC`, an assumption).
pub const ARM_MASS_FRAC: f64 = 0.15;
/// The arm sweep [deg] (Python `ARM_TRAVEL_DEG`, an assumption).
pub const ARM_TRAVEL_DEG: (f64, f64) = (-110.0, 110.0);

/// The `(dx, dz)` CG shift from stowed [m] for arm angles [deg] and drum loads [kg] over `dry_mass_kg`, mass-
/// weighted about the total; a link moves its own mass from stow, a load enters at its drum.
#[must_use]
pub fn cg_offset_m(
    front_deg: f64,
    back_deg: f64,
    front_drum_kg: f64,
    back_drum_kg: f64,
    dry_mass_kg: f64,
) -> (f64, f64) {
    let total = (dry_mass_kg + front_drum_kg + back_drum_kg).max(1e-9);
    let (mut mx, mut mz) = (0.0, 0.0);
    for (ox, deg, load) in [
        (ARM_ORIGIN_FRONT_X, front_deg, front_drum_kg),
        (ARM_ORIGIN_BACK_X, back_deg, back_drum_kg),
    ] {
        let a = deg.to_radians();
        let sgn = if ox > 0.0 { 1.0 } else { -1.0 };
        let link_m = ARM_MASS_FRAC * dry_mass_kg;
        let (px, pz) = (ox + sgn * ARM_LENGTH_M * a.cos(), ARM_LENGTH_M * a.sin());
        let stow_x = ox + sgn * ARM_LENGTH_M;
        mx += link_m * (px - stow_x) + load * px;
        mz += link_m * pz + load * pz;
    }
    (mx / total, mz / total)
}
