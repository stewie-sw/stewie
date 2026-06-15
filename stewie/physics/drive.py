"""Closed-loop drive — ROS/policy drives the rover via cmd_vel (Phase 3, 2026-06-01).

Closes the loop the spec is built for: instead of replaying a precomputed path
(drive_spiral.py, left intact), a controller supplies a TWIST (forward speed +
yaw rate) each step. The producer integrates it (rover.step_pose), reads the local
slope (rover.conform_pose), computes SLIP from the terrain demand (slip.py), reduces
the achieved motion by that slip, and carves the slip-deepened ruts
(rover.four_wheel_pass(physical=True)). So commanded and achieved motion DIVERGE
under slip, and that divergence is path-dependent — the whole point of a closed loop.

Two entry points:
  * closed_loop_drive(...)  -- run a sequence of twists (deterministic; testable).
  * poll_cmd_vel(path)      -- the reverse seam: read the latest {v, omega} twist
                               from a JSON file (file-mediated, like the INTERFACE
                               state-field seam), so a ROS node / Nav2 can drive it.

Slip magnitudes are [UNKNOWN]/[CALIB] (DEFERRED_FIXES.md); the loop's STRUCTURE
(commanded-vs-achieved divergence, stall-on-slope) is what is validated here.
"""
from __future__ import annotations

import dataclasses
import json
import math
import os

from stewie.specs import constants as K
from stewie.physics import material as materialmod
from stewie.physics import rover
from stewie.physics import slip as slipmod
from stewie.physics import terramechanics as tm
from stewie.physics.column_state import ColumnState


def poll_cmd_vel(path: str) -> tuple[float, float]:
    """Read the latest twist (v [m/s], omega [rad/s]) from a JSON file. The reverse
    command seam — a ROS node / policy writes ``{"v": .., "omega": ..}`` to ``path``;
    the producer polls it. Missing / unreadable / empty -> (0.0, 0.0) (safe stop).
    """
    if not os.path.exists(path):
        return 0.0, 0.0
    try:
        with open(path) as fh:
            d = json.load(fh)
        return float(d.get("v", 0.0)), float(d.get("omega", 0.0))
    except (ValueError, OSError):
        return 0.0, 0.0


def contact_length_from_sinkage(wheel_radius_m: float, sinkage_m: float) -> float:
    """Rigid-wheel contact-patch length [m] from wheel radius and sinkage (T-03).

    A rigid wheel of radius r sunk by depth z contacts the soil along the arc whose chord is
    L = 2*sqrt(r*z - z^2/4) (z clamped to <= 2r, the full-diameter limit). The patch GROWS with both
    sinkage and wheel radius, so a bigger wheel spreads the same load over a longer patch (lower Bekker
    pressure -> less sinkage) and a deeper rut lengthens the patch — both the failures the old fixed
    0.10 m rectangle could not express. Returns 0 for non-positive inputs.
    """
    if wheel_radius_m <= 0.0 or sinkage_m <= 0.0:
        return 0.0
    z = min(float(sinkage_m), 2.0 * float(wheel_radius_m))
    return 2.0 * math.sqrt(max(0.0, wheel_radius_m * z - 0.25 * z * z))


#: Minimum resolvable contact-patch length [m] — a numerical floor (1 mm) only, NOT the old fixed
#: rectangle. It guards the pressure divide at near-zero sinkage; it is far below any loaded patch so it
#: never masks the radius/sinkage dependence (the failure of the old 0.10 m nominal floor).
_MIN_CONTACT_LEN_M = 1e-3


def _resolve_contact_length(weight_n: float, slope_rad: float, wheel_radius_m: float,
                            nominal_len_m: float, wheel_width_m: float, n_wheels: int,
                            params: "tm.TerramechanicsParams") -> tuple[float, float]:
    """Self-consistently resolve (contact_len, static_sinkage) for the loaded wheel (T-03).

    The Bekker pressure depends on the contact length, and the sinkage-dependent contact length depends
    on the sinkage — a fixed point. Iterate from the nominal patch: sinkage from the current contact
    length -> rigid-wheel chord contact length from that sinkage -> repeat until it converges. The
    converged length is the PHYSICAL chord (which grows with wheel radius and sinkage), floored only by a
    tiny numerical minimum so a barely-loaded wheel does not divide by a zero-area patch. Returns
    (contact_len_m, static_sinkage_m). Pure read of the equilibrium inputs; no mutation, mass-neutral.
    """
    per_wheel_n = weight_n * math.cos(slope_rad) / max(int(n_wheels), 1)
    cl = float(nominal_len_m)                            # iteration seed (not a floor)
    z = 0.0
    for _ in range(40):                                  # monotone fixed point, converges quickly
        z = tm.wheel_static_sinkage(per_wheel_n, params=params,
                                    contact_len_m=cl, contact_width_m=wheel_width_m)
        cl_new = max(_MIN_CONTACT_LEN_M, contact_length_from_sinkage(wheel_radius_m, z))
        if abs(cl_new - cl) < 1e-7:
            cl = cl_new
            break
        cl = cl_new
    return cl, z


def _skid_steer_motion(v_cmd: float, omega_cmd: float, *, track_m: float,
                       normal_left_n: float, normal_right_n: float,
                       slope_rad: float, roll_rad: float, weight_n: float,
                       params: "tm.TerramechanicsParams",
                       contact_len_m: float, contact_width_m: float) -> dict:
    """Per-side skid-steer terramechanics (T-05): left/right thrust balance + lateral scrub.

    A skid-steer rover turns by driving its two SIDES at different speeds: v_left = v - omega*track/2,
    v_right = v + omega*track/2. Each side develops its own LONGITUDINAL slip against its OWN traction
    budget (so differential normal loading on a cross-slope makes the two sides slip differently), and
    the zero-radius-style yaw forces every wheel to SCRUB laterally. That lateral shear consumes part of
    the Coulomb friction budget and resists the yaw moment, so the achieved yaw under-achieves MORE than
    the forward speed and the effective turn radius GROWS on weak soil — the failure a single scalar
    longitudinal-slip multiplier (the old omega_ach=(1-s)*omega_cmd) structurally cannot produce.

    Returns the achieved body twist (v_ach, omega_ach) plus the per-side commanded/achieved speeds and
    per-side longitudinal slip, all mass-/geometry-faithful (no fabricated coefficients — the lateral
    scrub uses the SAME Coulomb-Mohr budget as the longitudinal traction).
    """
    half = 0.5 * track_m
    v_left_cmd = v_cmd - omega_cmd * half
    v_right_cmd = v_cmd + omega_cmd * half
    area = contact_len_m * contact_width_m

    def _side_long_slip(v_side: float, normal_side_n: float) -> float:
        # per-side longitudinal demand = along-slope gravity carried by this side's normal load; slip is
        # the Janosi-Hanamoto slip that develops that demand against the side's Coulomb-Mohr budget. A
        # side under more normal load (downhill on a cross-slope) has a bigger budget -> less slip.
        if abs(v_side) < 1e-12:
            return 0.0
        demand = normal_side_n * math.sin(slope_rad)         # along-slope gravity on this side
        h_max = slipmod.traction_budget(normal_side_n, cohesion=params.cohesion,
                                        phi_rad=params.phi_rad, contact_area_m2=area)
        s, _ent = slipmod.slip_for_demand(abs(demand), h_max, contact_len_m=contact_len_m,
                                          k_shear=params.k_shear)
        return s

    s_left = _side_long_slip(v_left_cmd, normal_left_n)
    s_right = _side_long_slip(v_right_cmd, normal_right_n)
    v_left_ach = (1.0 - s_left) * v_left_cmd
    v_right_ach = (1.0 - s_right) * v_right_cmd

    # Body twist from the achieved per-side speeds (the kinematic inverse of the differential):
    #   v_body = (v_left + v_right)/2,  omega_body = (v_right - v_left)/track.
    v_ach = 0.5 * (v_left_ach + v_right_ach)
    omega_from_sides = (v_right_ach - v_left_ach) / track_m if track_m > 1e-9 else omega_cmd

    # Lateral SCRUB resistance (the skid-steer turn drags the wheels sideways across the soil). The
    # required lateral shear to yaw at omega is resisted by the available lateral Coulomb-Mohr friction;
    # when the demanded lateral shear approaches that ceiling the yaw is throttled. We scale the yaw by a
    # scrub factor in (0,1] = available_lateral_friction / (available + demanded_scrub), so a sharper
    # turn (more lateral demand) loses more yaw -> the effective radius grows.  demanded scrub rises with
    # |omega| and the lateral lever (track/2); the ceiling is the side normal load's friction.
    normal_total = normal_left_n + normal_right_n
    h_lat = slipmod.traction_budget(normal_total, cohesion=params.cohesion,
                                    phi_rad=params.phi_rad, contact_area_m2=2.0 * area)
    # lateral scrub "demand" proxy: the lateral velocity the outer track sweeps relative to the ground,
    # converted to a resisting shear via the friction ceiling. Larger |omega|*half -> larger scrub.
    scrub_speed = abs(omega_cmd) * half
    ref_speed = max(abs(v_cmd), 1e-3)
    # TERRA-01 [ASSUMPTION]: this lateral-scrub interpolation FORM (and the scrub_factor throttling below)
    # is a MODELING CHOICE -- dimensionally sane and bounded in (0,1], but NOT derived from Janosi-Hanamoto
    # lateral shear-displacement, wheel/track contact-patch integration, or measured skid-steer turn data.
    # Turn radius and energy on weak soil may be materially biased; calibrating it against IPEx/RASSOR (or
    # representative skid-steer) data is deferred (DEFERRED_FIXES). The cross-slope gravity term IS sourced
    # (same Coulomb-Mohr budget); the INTERPOLATION is the assumption. Evidence status exposed as scrub_evidence.
    scrub_demand = h_lat * scrub_speed / (scrub_speed + ref_speed)
    # cross-slope: the lateral (roll) gravity component weight*sin(roll) is carried by the same lateral
    # friction budget, so a turn on a side-slope yaws differently than the identical turn on flat ground.
    lateral_gravity = abs(weight_n) * abs(math.sin(roll_rad))
    scrub_demand = scrub_demand + lateral_gravity
    scrub_factor = h_lat / (h_lat + scrub_demand) if h_lat > 0.0 else 1.0
    omega_ach = omega_from_sides * scrub_factor
    return {
        "v_ach": v_ach, "omega_ach": omega_ach,
        "v_left_cmd": v_left_cmd, "v_right_cmd": v_right_cmd,
        "v_left_ach": v_left_ach, "v_right_ach": v_right_ach,
        "slip_left": s_left, "slip_right": s_right,
        "scrub_factor": scrub_factor,
        "scrub_evidence": "ASSUMPTION",                   # TERRA-01: the scrub interpolation is uncalibrated
    }


def drive_step(cs: ColumnState, rc: tuple[float, float], yaw: float,
               v_cmd: float, omega_cmd: float, *, dt: float = 0.1,
               params: "tm.TerramechanicsParams | None" = None,
               payload_kg: float = 0.0, wheel_width_m: float = 0.18,
               contact_len_m: float = 0.10, g: float = K.g,
               material: bool = False,
               clasts: "list[dict] | None" = None,
               skid_steer: bool = False,
               track_m: float = 0.5207,
               mass_kg: float = K.ROVER_MASS_DRY_KG,
               n_wheels: int = K.N_WHEELS,
               gauge_m: float = rover.WHEEL_GAUGE_M,
               wheelbase_m: float = rover.WHEEL_BASE_M,
               wheel_radius_m: float = rover.WHEEL_RADIUS_M,
               ) -> tuple[tuple[float, float], float, dict]:
    """One closed-loop step: command twist in, (new_rc, new_yaw, telemetry) out.

    read local forward slope (conform_pose pitch, incl. clast ride-over if ``clasts``
    given) -> slip-sinkage equilibrium (slip.py) -> achieved v = (1-slip)*commanded v
    -> integrate pose (step_pose) -> carve slip-deepened ruts at the achieved pose
    (four_wheel_pass(physical=True)). MASS-CONSERVING. ``g`` sets the body gravity (default
    lunar; see bodies.py) -> weight = m*g drives the load. Telemetry dict: rc, yaw, v_cmd,
    omega_cmd, v_achieved, slip, entrapped, slope_rad, sinkage_m.
    """
    p = params or tm.TerramechanicsParams.from_constants()
    if material:                                          # Material layer: per-cell strength from local density
        row = min(max(int(round(rc[0])), 0), cs.density.shape[0] - 1)
        col = min(max(int(round(rc[1])), 0), cs.density.shape[1] - 1)
        phi_r, coh = materialmod.cell_strength(float(cs.density[row, col]))
        p = dataclasses.replace(p, cohesion=coh, phi_rad=phi_r)   # loose cell -> less traction -> more slip
    # A-02: load is the RESOLVED vehicle mass (dry + drum fill), not the K.ROVER_MASS_DRY_KG global, so a
    # 65 kg RASSOR-2 puts ~2.2x the per-wheel normal load of a 30 kg IPEx and therefore sinks/slips more.
    weight_n = (float(mass_kg) + max(0.0, payload_kg)) * float(g)
    h = cs.derive_height()
    # the conform reads the slope over THIS vehicle's stance (gauge/wheelbase) and rides clasts up to one
    # of ITS wheel radii -- the geometry that sets the pitch the slip-sinkage solve sees.
    cf = rover.conform_pose(h, rc, yaw, cell_m=cs.cell_m, payload_kg=payload_kg, clasts=clasts, g=g,
                            gauge_m=gauge_m, wheelbase_m=wheelbase_m, climb_limit_m=wheel_radius_m,
                            rover_mass_dry_kg=float(mass_kg))
    # the traction DEMAND is the magnitude of the along-slope gravity: descending a grade requires
    # braking traction equal to climbing it -- the signed pitch made every descent a perfect-grip
    # zero-slip case (a 55-deg drop descended at exactly v_cmd; audit 2026-06-09)
    slope_rad = abs(cf["pitch_rad"])
    # T-03: the contact patch is SINKAGE-DEPENDENT, not a fixed 0.10 m rectangle. Resolve the rigid-wheel
    # contact length self-consistently with the static sinkage (a bigger wheel / firmer soil spreads the
    # load over a longer patch -> lower pressure -> less sinkage) before the slip-sinkage equilibrium.
    contact_len_resolved, _z_static = _resolve_contact_length(
        weight_n, slope_rad, wheel_radius_m, contact_len_m, wheel_width_m, int(n_wheels), p)
    eq = slipmod.slip_sinkage_equilibrium(weight_n, slope_rad, params=p,
                                          n_wheels=int(n_wheels),
                                          contact_len_m=contact_len_resolved,
                                          contact_width_m=wheel_width_m)
    s = eq["slip"]
    entrapped = bool(eq["entrapped"])
    # T-01: entrapment is a DISCRETE stuck state, not a slow creep. When the demanded thrust exceeds
    # the traction budget the wheels spin in place (slip pinned near 1): there is NO net forward
    # translation and NO yaw authority, and the rover cannot self-improve the terrain into an escape.
    # The old `v_ach = (1-s_max)*v_cmd` left ~1% of commanded speed, so a "stuck" rover crept forward
    # ~0.002 m/step and carved fresh ruts that eventually let it walk out — contradicting the discrete
    # entrapment state (audit T-01). Recovery requires a CHANGED condition (gentler slope / backed-off
    # thrust), modelled by re-solving the equilibrium next step, not numerical creep at the old pose.
    side_telem: dict = {}
    if entrapped:
        # spinning wheels still shear/deepen the rut UNDER the (unchanged) pose: a real entrapped wheel
        # digs in. We apply only that in-place wheel pass at the CURRENT pose (no translation), so the
        # terrain change is the burial of a stuck wheel, never a forward advance.
        v_ach = 0.0
        omega_ach = 0.0
        rover.four_wheel_pass(cs, [(rc, yaw)], wheel_width_m=wheel_width_m,
                              physical=True, loads=cf["normal_loads"], params=p,
                              contact_len_m=contact_len_resolved, slip=s)
        new_rc, new_yaw = (float(rc[0]), float(rc[1])), float(yaw)
    else:
        v_ach = (1.0 - s) * v_cmd                         # slip robs forward progress
        if skid_steer:
            # T-05: per-side skid-steer terramechanics. Left = LF+LB, right = RF+RB normal reactions
            # (T-04 gives differential loading on a cross-slope), so the two sides slip differently and
            # the yaw also pays a LATERAL SCRUB penalty -> achieved yaw under-achieves more than v and the
            # effective turn radius grows. Supersedes the scalar omega_ach=(1-s)*omega_cmd.
            loads = cf["normal_loads"]
            normal_left = float(loads["LF"] + loads["LB"])
            normal_right = float(loads["RF"] + loads["RB"])
            ss = _skid_steer_motion(
                v_cmd, omega_cmd, track_m=track_m,
                normal_left_n=normal_left, normal_right_n=normal_right,
                slope_rad=slope_rad, roll_rad=float(cf["roll_rad"]), weight_n=weight_n,
                params=p,
                contact_len_m=contact_len_resolved, contact_width_m=wheel_width_m)
            v_ach = ss["v_ach"]
            omega_ach = ss["omega_ach"]
            side_telem = {
                "v_left_cmd": float(ss["v_left_cmd"]), "v_right_cmd": float(ss["v_right_cmd"]),
                "v_left_ach": float(ss["v_left_ach"]), "v_right_ach": float(ss["v_right_ach"]),
                "slip_left": float(ss["slip_left"]), "slip_right": float(ss["slip_right"]),
                "scrub_factor": float(ss["scrub_factor"]),
                "scrub_evidence": str(ss["scrub_evidence"]),   # TERRA-01: scrub interpolation is uncalibrated
            }
        else:
            omega_ach = omega_cmd
        new_rc, new_yaw = rover.step_pose(rc, yaw, v_ach, omega_ach, dt, cell_m=cs.cell_m)
        rover.four_wheel_pass(cs, [(new_rc, new_yaw)], wheel_width_m=wheel_width_m,
                              physical=True, loads=cf["normal_loads"], params=p,
                              contact_len_m=contact_len_resolved, slip=s)
    telem = {
        "rc": [new_rc[0], new_rc[1]], "yaw": new_yaw,
        "v_cmd": float(v_cmd), "omega_cmd": float(omega_cmd),
        "omega_achieved": float(omega_ach), "track_m": float(track_m) if skid_steer else None,
        "v_achieved": float(v_ach), "slip": float(s), "entrapped": entrapped,
        "slope_rad": float(slope_rad), "sinkage_m": float(eq["sinkage_m"]),
        "contact_len_m": float(contact_len_resolved),    # T-03: sinkage/radius-resolved contact patch
    }
    telem.update(side_telem)                              # T-05: per-side skid-steer breakdown (if any)
    return new_rc, new_yaw, telem


def closed_loop_drive(cs: ColumnState, start_rc: tuple[float, float], start_yaw: float,
                      twists, *, dt: float = 0.1,
                      params: "tm.TerramechanicsParams | None" = None,
                      payload_kg: float = 0.0, wheel_width_m: float = 0.18,
                      contact_len_m: float = 0.10, g: float = K.g,
                      clasts: "list[dict] | None" = None,
                      mass_kg: float = K.ROVER_MASS_DRY_KG,
                      n_wheels: int = K.N_WHEELS,
                      gauge_m: float = rover.WHEEL_GAUGE_M,
                      wheelbase_m: float = rover.WHEEL_BASE_M,
                      wheel_radius_m: float = rover.WHEEL_RADIUS_M) -> dict:
    """Drive ``cs`` through a sequence of ``twists`` ((v_mps, omega_radps) pairs),
    one drive_step each. Deterministic. ``clasts`` (optional) enables boulder
    ride-over in the per-step conform. ``g`` sets body gravity (default lunar; bodies.py).
    Returns {steps, commanded_dist_m, achieved_dist_m, final_rc, final_yaw, any_entrapped}.
    """
    p = params or tm.TerramechanicsParams.from_constants()
    rc = (float(start_rc[0]), float(start_rc[1]))
    yaw = float(start_yaw)
    steps: list[dict] = []
    commanded_dist = achieved_dist = 0.0
    any_entrapped = False
    for i, (v_cmd, omega_cmd) in enumerate(twists):
        rc, yaw, telem = drive_step(cs, rc, yaw, v_cmd, omega_cmd, dt=dt, params=p,
                                    payload_kg=payload_kg, wheel_width_m=wheel_width_m,
                                    contact_len_m=contact_len_m, g=g, clasts=clasts,
                                    mass_kg=mass_kg, n_wheels=n_wheels, gauge_m=gauge_m,
                                    wheelbase_m=wheelbase_m, wheel_radius_m=wheel_radius_m)
        telem["frame"] = i
        commanded_dist += abs(v_cmd) * dt
        achieved_dist += abs(telem["v_achieved"]) * dt
        any_entrapped = any_entrapped or telem["entrapped"]
        steps.append(telem)
    return {
        "steps": steps,
        "commanded_dist_m": commanded_dist,
        "achieved_dist_m": achieved_dist,
        "final_rc": [rc[0], rc[1]],
        "final_yaw": yaw,
        "any_entrapped": any_entrapped,
    }
