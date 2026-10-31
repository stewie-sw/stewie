//! One closed-loop drive step (Python `stewie.physics.drive`): conform to the terrain, resolve the
//! sinkage-dependent contact patch, solve the slip-sinkage equilibrium, move at the achieved twist and carve
//! slip-deepened ruts. Entrapment is a discrete stuck state: no translation or yaw, only the stuck wheels
//! digging in place. Optional per-cell material strength and per-side skid-steer with lateral scrub.
//! Mass-conserving (every terrain edit is density-only).

use crate::PhysicsError;
use crate::column::ColumnState;
use crate::material::MaterialModel;
use crate::rover::{self, Clast, Compaction, ConformSetup};
use crate::soil::SoilParams;
use crate::terra::{self, DriveCase};

/// Rigid-wheel contact chord [m] for a wheel of radius `r` sunk by `z`: `2*sqrt(r z - z^2/4)`, `z <= 2r`.
#[must_use]
pub fn contact_length_from_sinkage(wheel_radius_m: f64, sinkage_m: f64) -> f64 {
    if wheel_radius_m <= 0.0 || sinkage_m <= 0.0 {
        return 0.0;
    }
    let z = sinkage_m.min(2.0 * wheel_radius_m);
    2.0 * (wheel_radius_m * z - 0.25 * z * z).max(0.0).sqrt()
}

/// Numerical floor on the contact length (1 mm), guarding the pressure divide only.
const MIN_CONTACT_LEN_M: f64 = 1e-3;

/// Fixed point of contact length and static sinkage for the loaded wheel, seeded at `nominal_len_m`
/// (at most 40 rounds, to 1e-7 m). Returns `(contact_len_m, static_sinkage_m)`.
///
/// # Errors
/// As [`terra::contact_static_sinkage`].
pub fn resolve_contact_length(
    weight_n: f64,
    slope_rad: f64,
    veh: &Vehicle,
    density: Option<f64>,
    p: &SoilParams,
) -> Result<(f64, f64), PhysicsError> {
    let per_wheel = weight_n * slope_rad.cos() / f64::from(veh.n_wheels.max(1));
    let (mut cl, mut z) = (veh.nominal_contact_len_m, 0.0);
    for _ in 0..40 {
        z = terra::contact_static_sinkage(per_wheel, cl, veh.wheel_width_m, density, p)?;
        let next = contact_length_from_sinkage(veh.wheel_radius_m, z).max(MIN_CONTACT_LEN_M);
        let done = (next - cl).abs() < 1e-7;
        cl = next;
        if done {
            break;
        }
    }
    Ok((cl, z))
}

/// The vehicle figures a drive step reads (from the rover profile).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Vehicle {
    pub mass_kg: f64,
    pub n_wheels: u32,
    pub gauge_m: f64,
    pub wheelbase_m: f64,
    pub wheel_radius_m: f64,
    pub wheel_width_m: f64,
    /// Seed for the contact-length fixed point [m].
    pub nominal_contact_len_m: f64,
    pub cg_height_m: f64,
    /// Skid-steer kinematic track [m].
    pub track_m: f64,
}

/// Per-side skid-steer outcome.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct SkidSides {
    pub v_left_cmd: f64,
    pub v_right_cmd: f64,
    pub v_left_ach: f64,
    pub v_right_ach: f64,
    pub slip_left: f64,
    pub slip_right: f64,
    /// Yaw throttle in `(0, 1]` from lateral scrub. The interpolation form is an uncalibrated [ASSUMPTION]
    /// (Python TERRA-01); the cross-slope gravity term is sourced.
    pub scrub_factor: f64,
}

#[allow(clippy::too_many_arguments)] // the per-side balance has this many independent inputs
fn skid_steer_motion(
    v_cmd: f64,
    omega_cmd: f64,
    track_m: f64,
    normal_left: f64,
    normal_right: f64,
    slope_rad: f64,
    roll_rad: f64,
    weight_n: f64,
    contact_len_m: f64,
    contact_width_m: f64,
    extra_demand_n: f64,
    p: &SoilParams,
) -> (f64, f64, SkidSides) {
    let half = 0.5 * track_m;
    let (vl, vr) = (v_cmd - omega_cmd * half, v_cmd + omega_cmd * half);
    let area = contact_len_m * contact_width_m;
    let side = |v: f64, n: f64| {
        if v.abs() < 1e-12 {
            return 0.0;
        }
        let demand = n * slope_rad.sin() + 0.5 * extra_demand_n.abs();
        terra::slip_for_demand(
            demand.abs(),
            terra::traction_budget(n, area, p),
            contact_len_m,
            p.k_shear_m,
        )
        .0
    };
    let (sl, sr) = (side(vl, normal_left), side(vr, normal_right));
    let (vla, vra) = ((1.0 - sl) * vl, (1.0 - sr) * vr);
    let v_ach = 0.5 * (vla + vra);
    let omega_sides = if track_m > 1e-9 {
        (vra - vla) / track_m
    } else {
        omega_cmd
    };
    let h_lat = terra::traction_budget(normal_left + normal_right, 2.0 * area, p);
    let scrub_speed = omega_cmd.abs() * half;
    let demand = h_lat * scrub_speed / (scrub_speed + v_cmd.abs().max(1e-3))
        + weight_n.abs() * roll_rad.sin().abs();
    let scrub = if h_lat > 0.0 {
        h_lat / (h_lat + demand)
    } else {
        1.0
    };
    (
        v_ach,
        omega_sides * scrub,
        SkidSides {
            v_left_cmd: vl,
            v_right_cmd: vr,
            v_left_ach: vla,
            v_right_ach: vra,
            slip_left: sl,
            slip_right: sr,
            scrub_factor: scrub,
        },
    )
}

/// What one step asks for.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct StepCommand {
    pub v_cmd: f64,
    pub omega_cmd: f64,
    pub dt_s: f64,
    pub payload_kg: f64,
    pub gravity_ms2: f64,
    /// Unbalanced excavation draft reaction [N] the wheels must also carry.
    pub dig_reaction_n: f64,
    pub skid_steer: bool,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Telemetry {
    pub rc: (f64, f64),
    pub yaw: f64,
    pub v_achieved: f64,
    pub omega_achieved: f64,
    pub slip: f64,
    pub entrapped: bool,
    pub slope_rad: f64,
    pub sinkage_m: f64,
    pub contact_len_m: f64,
    pub sides: Option<SkidSides>,
}

/// The soil under the rover: with a material model, the cell's own strength and its density for bearing.
#[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)]
fn local_soil(
    cs: &ColumnState,
    rc: (f64, f64),
    soil: &SoilParams,
    material: Option<&MaterialModel>,
) -> (SoilParams, Option<f64>) {
    let Some(m) = material else {
        return (*soil, None);
    };
    let row = (rc.0.round_ties_even().max(0.0) as usize).min(cs.height() - 1);
    let col = (rc.1.round_ties_even().max(0.0) as usize).min(cs.width() - 1);
    let rho = cs.fields().density[row * cs.width() + col];
    let mut here = *soil;
    (here.phi_rad, here.cohesion_pa) = m.cell_strength(rho);
    (here, Some(rho))
}

fn conform_setup(cs: &ColumnState, veh: &Vehicle, weight_n: f64) -> ConformSetup {
    ConformSetup {
        cell_m: cs.cell_m(),
        world_x0: 0.0,
        world_y0: 0.0,
        climb_limit_m: veh.wheel_radius_m,
        min_grad_cells: 2.5,
        gauge_m: veh.gauge_m,
        wheelbase_m: veh.wheelbase_m,
        cg_height_m: veh.cg_height_m,
        total_weight_n: weight_n,
    }
}

/// One closed-loop step from pose `(rc, yaw)` on `cs`. `material`, when given, replaces the soil's
/// friction and cohesion with the strength of the cell under the rover and stiffens bearing by its density.
///
/// # Errors
/// As [`terra::slip_sinkage_equilibrium`].
#[allow(clippy::too_many_arguments)] // a step is the terrain, pose, command, vehicle and soil
pub fn drive_step(
    cs: &mut ColumnState,
    rc: (f64, f64),
    yaw: f64,
    cmd: &StepCommand,
    veh: &Vehicle,
    soil: &SoilParams,
    material: Option<&MaterialModel>,
    clasts: &[Clast],
) -> Result<Telemetry, PhysicsError> {
    let (here, cell_rho) = local_soil(cs, rc, soil, material);
    let weight_n = (veh.mass_kg + cmd.payload_kg.max(0.0)) * cmd.gravity_ms2;
    let heights = cs.derive_height();
    let cf = rover::conform_pose(
        &heights,
        cs.width(),
        cs.height(),
        rc,
        yaw,
        clasts,
        &conform_setup(cs, veh, weight_n),
    );
    // descending needs braking traction equal to climbing, so the demand uses |pitch|
    let slope_rad = cf.pitch_rad.abs();
    let (cl, _) = resolve_contact_length(weight_n, slope_rad, veh, cell_rho, &here)?;
    let eq = terra::slip_sinkage_equilibrium(
        &DriveCase {
            total_weight_n: weight_n,
            slope_rad,
            n_wheels: veh.n_wheels,
            contact_len_m: cl,
            contact_width_m: veh.wheel_width_m,
            density: cell_rho,
            demand_frac: 1.0,
            extra_demand_n: cmd.dig_reaction_n.abs(),
            s_entrap: 0.95,
            z_entrap_m: 0.36,
        },
        &here,
    )?;
    let compaction = Compaction::Physical {
        loads_n: cf.normal_loads_n,
        slip: [eq.slip; 4],
        contact_len_m: cl,
        soil: here,
    };
    let (new_rc, new_yaw, v_ach, omega_ach, sides) = if eq.entrapped {
        // stuck: the wheels dig in under the unchanged pose, no translation, no yaw
        rover::four_wheel_pass(
            cs,
            &[(rc, yaw)],
            veh.gauge_m,
            veh.wheelbase_m,
            veh.wheel_width_m,
            here.rho_deep,
            &compaction,
        );
        (rc, yaw, 0.0, 0.0, None)
    } else {
        let (v_ach, omega_ach, sides) = if cmd.skid_steer {
            let l = cf.normal_loads_n;
            let (va, oa, sd) = skid_steer_motion(
                cmd.v_cmd,
                cmd.omega_cmd,
                veh.track_m,
                l[0] + l[2],
                l[1] + l[3],
                slope_rad,
                cf.roll_rad,
                weight_n,
                cl,
                veh.wheel_width_m,
                cmd.dig_reaction_n,
                &here,
            );
            (va, oa, Some(sd))
        } else {
            ((1.0 - eq.slip) * cmd.v_cmd, cmd.omega_cmd, None)
        };
        let (nrc, nyaw) = rover::step_pose(rc, yaw, v_ach, omega_ach, cmd.dt_s, cs.cell_m());
        rover::four_wheel_pass(
            cs,
            &[(nrc, nyaw)],
            veh.gauge_m,
            veh.wheelbase_m,
            veh.wheel_width_m,
            here.rho_deep,
            &compaction,
        );
        (nrc, nyaw, v_ach, omega_ach, sides)
    };
    Ok(Telemetry {
        rc: new_rc,
        yaw: new_yaw,
        v_achieved: v_ach,
        omega_achieved: omega_ach,
        slip: eq.slip,
        entrapped: eq.entrapped,
        slope_rad,
        sinkage_m: eq.sinkage_m,
        contact_len_m: cl,
        sides,
    })
}
