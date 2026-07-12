"""Tests for the closed-loop drive (rover.step_pose + drive.py) — Phase 3.

Host-runnable + pytest-discoverable. Validates the unicycle integrator, the
commanded-vs-achieved divergence under slip (the closed loop), stall-on-slope,
determinism, mass conservation, and the cmd_vel file seam.
"""
from __future__ import annotations

import json
import math
import os
import tempfile

import numpy as np

from stewie.physics import drive
from stewie.physics import rover
from stewie.physics.column_state import ColumnState


# -- step_pose integrator ----------------------------------------------------

def test_step_pose_straight_advances_col():
    (r, c), yaw = rover.step_pose((10.0, 10.0), 0.0, 1.0, 0.0, 1.0, cell_m=0.1)
    assert math.isclose(r, 10.0, abs_tol=1e-9)
    assert math.isclose(c, 10.0 + 10.0, rel_tol=1e-9)   # 1 m / 0.1 m = +10 cells in col
    assert math.isclose(yaw, 0.0, abs_tol=1e-9)


def test_step_pose_heading_halfpi_advances_row():
    (r, c), yaw = rover.step_pose((10.0, 10.0), math.pi / 2, 1.0, 0.0, 1.0, cell_m=0.1)
    assert math.isclose(r, 20.0, rel_tol=1e-9)
    assert math.isclose(c, 10.0, abs_tol=1e-6)


def test_step_pose_pure_rotation():
    (r, c), yaw = rover.step_pose((5.0, 5.0), 0.0, 0.0, 1.0, 0.5, cell_m=0.1)
    assert math.isclose(r, 5.0, abs_tol=1e-12) and math.isclose(c, 5.0, abs_tol=1e-12)
    assert math.isclose(yaw, 0.5, rel_tol=1e-9)


def test_step_pose_arc_deterministic_and_moves():
    a = rover.step_pose((20.0, 20.0), 0.3, 0.5, 0.4, 0.2, cell_m=0.05)
    b = rover.step_pose((20.0, 20.0), 0.3, 0.5, 0.4, 0.2, cell_m=0.05)
    assert a == b
    assert (a[0][0], a[0][1]) != (20.0, 20.0)
    assert not math.isclose(a[1], 0.3)   # yaw changed on the arc


def test_step_pose_arc_matches_straight_limit():
    straight = rover.step_pose((0.0, 0.0), 0.7, 1.0, 1e-12, 1.0, cell_m=0.1)
    near = rover.step_pose((0.0, 0.0), 0.7, 1.0, 1e-7, 1.0, cell_m=0.1)
    assert math.isclose(straight[0][0], near[0][0], abs_tol=1e-4)
    assert math.isclose(straight[0][1], near[0][1], abs_tol=1e-4)


def test_step_pose_yaw_wrapped():
    (_, _), yaw = rover.step_pose((0.0, 0.0), 3.0, 0.0, 1.0, 1.0, cell_m=0.1)
    assert -math.pi < yaw <= math.pi
    assert math.isclose(yaw, 4.0 - 2 * math.pi, rel_tol=1e-9)


# -- closed loop -------------------------------------------------------------

def _flat(grid=96, cell=0.02):
    return ColumnState(width=grid, height=grid, cell_m=cell)


def _ramp(slope_deg, grid=96, cell=0.02):
    cs = ColumnState(width=grid, height=grid, cell_m=cell)
    cols = np.arange(grid)[None, :].repeat(grid, axis=0).astype(np.float64)
    cs.datum = math.tan(math.radians(slope_deg)) * cols * cell
    return cs


def test_closed_loop_flat_advances_low_slip():
    cs = _flat()
    res = drive.closed_loop_drive(cs, (48.0, 20.0), 0.0, [(0.2, 0.0)] * 20, dt=0.1)
    assert not res["any_entrapped"]
    assert res["achieved_dist_m"] > 0.8 * res["commanded_dist_m"]   # low slip on flat
    assert res["final_rc"][1] > 20.0                                # advanced in +col


def test_closed_loop_uphill_stalls():
    cs = _ramp(55.0)
    res = drive.closed_loop_drive(cs, (48.0, 20.0), 0.0, [(0.2, 0.0)] * 20, dt=0.1)
    assert res["any_entrapped"]
    assert res["achieved_dist_m"] < 0.3 * res["commanded_dist_m"]   # slip stalls the climb


def test_closed_loop_mass_conserved():
    cs = _flat()
    m0 = cs.total_mass()
    drive.closed_loop_drive(cs, (48.0, 30.0), 0.5, [(0.2, 0.1)] * 15, dt=0.1)
    assert math.isclose(cs.total_mass(), m0, rel_tol=1e-9)


def test_drive_step_dig_reaction_raises_slip():
    """council #2: dig_reaction_n adds to the drive_step traction demand, so slip rises vs no reaction on
    the SAME flat terrain + pose; default 0 is unchanged; telemetry reports the reaction."""
    _, _, base = drive.drive_step(_flat(), (48.0, 48.0), 0.0, 0.2, 0.0, dt=0.1)
    _, _, react = drive.drive_step(_flat(), (48.0, 48.0), 0.0, 0.2, 0.0, dt=0.1, dig_reaction_n=200.0)
    assert react["slip"] > base["slip"]
    assert react["dig_reaction_n"] == 200.0
    assert base["dig_reaction_n"] == 0.0


def test_closed_loop_determinism():
    twists = [(0.2, 0.05)] * 12
    a = drive.closed_loop_drive(_flat(), (48.0, 40.0), 0.2, twists, dt=0.1)
    b = drive.closed_loop_drive(_flat(), (48.0, 40.0), 0.2, twists, dt=0.1)
    assert a["steps"] == b["steps"]
    assert a["final_rc"] == b["final_rc"] and a["final_yaw"] == b["final_yaw"]


# -- cmd_vel reverse seam ----------------------------------------------------

def test_poll_cmd_vel_reads_and_defaults():
    assert drive.poll_cmd_vel("/no/such/cmd_vel.json") == (0.0, 0.0)
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        with open(path, "w") as fh:
            json.dump({"v": 0.3, "omega": -0.2}, fh)
        assert drive.poll_cmd_vel(path) == (0.3, -0.2)
    finally:
        os.remove(path)


def test_drive_step_threads_clasts():
    """clasts reach conform_pose (boulder ride-over) -> a front boulder tilts the
    rover's forward pitch, so the slope/slip the step sees changes. (Found live:
    drive_step previously ignored clasts.)"""
    # at yaw=0 the forward axis is +x (+col); a boulder ahead lifts the front wheels.
    front_boulder = [{"center_m": [24 * 0.02 + 0.20, 0.0, 24 * 0.02], "radius_m": 0.35}]

    def slope(use):
        cs = ColumnState(width=48, height=48, cell_m=0.02)
        _, _, t = drive.drive_step(cs, (24.0, 24.0), 0.0, 0.0, 0.0, dt=0.1,
                                   clasts=(front_boulder if use else None))
        return t["slope_rad"]

    assert abs(slope(True)) > abs(slope(False)) + 1e-3


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"[PASS] {fn.__name__}")
    print(f"\n{len(fns)}/{len(fns)} drive checks passed.")


if __name__ == "__main__":
    _run_all()


def test_skid_steer_yaw_authority_is_slip_coupled():
    """Navigation T1.2: with skid_steer=True, yaw comes from DIFFERENTIAL thrust over the documented
    0.5207 m track -- the same slip that robs forward progress robs the speed differential, so
    omega under-achieves on low-traction slopes exactly as v does. Default path: byte-identical."""
    import numpy as np

    from stewie.physics import drive
    from stewie.physics.column_state import ColumnState
    from stewie.specs import ipex_specs as ix

    def fresh():
        cs = ColumnState(width=64, height=64, cell_m=0.02,
                         mass_areal=np.full((64, 64), 50.0))
        # a real grade -> real slip, but below the T-03 sinkage-resolved entrapment threshold so the
        # slip-coupled yaw degradation (not full entrapment) is what the test exercises.
        ramp = np.tile(np.linspace(0.0, 0.30, 64)[None, :], (64, 1))
        cs.datum = cs.datum + ramp - cs.derive_height() + cs.derive_height() * 0  # raise surface
        cs.datum[:, :] = ramp - (cs.derive_height() - cs.datum)
        return cs

    # default path unchanged (zero-regression bar)
    a = drive.drive_step(fresh(), (32.0, 20.0), 0.0, 0.25, 0.4, dt=0.2)
    b = drive.drive_step(fresh(), (32.0, 20.0), 0.0, 0.25, 0.4, dt=0.2)
    assert a[1] == b[1]                                   # deterministic baseline
    # skid-steer truth (T-05 per-side terramechanics, supersedes the old scalar omega=(1-slip)*omega_cmd):
    # on the slope, achieved yaw under-achieves the commanded yaw — yaw authority degrades with traction.
    rc, yaw_t, telem = drive.drive_step(fresh(), (32.0, 20.0), 0.0, 0.25, 0.4, dt=0.2,
                                        skid_steer=True, track_m=ix.SKID_STEER_TRACK_M)
    assert telem["slip"] > 0.05                           # the grade produces real slip
    assert telem["omega_achieved"] < telem["omega_cmd"]   # yaw under-achieves under traction loss
    assert "slip_left" in telem and "slip_right" in telem  # per-side breakdown present (T-05)
    assert abs(yaw_t) < abs(a[1]) or telem["slip"] == 0.0  # yaw under-achieves vs the ideal path


def test_t03_contact_length_grows_with_sinkage_and_wheel_radius():
    """T-03: the contact-patch length must be DERIVED from wheel radius and sinkage, not a fixed 0.10 m
    rectangle. For a rigid wheel sunk by z, the contact chord length L = 2*sqrt(r*z - z^2/4) grows with
    both sinkage and wheel radius. Assert the helper is monotone in each, bounded by the chord, and
    matches the closed form."""
    r = 0.18
    # monotone in sinkage
    L_shallow = drive.contact_length_from_sinkage(r, 0.005)
    L_deep = drive.contact_length_from_sinkage(r, 0.05)
    assert L_deep > L_shallow > 0.0
    # monotone in wheel radius at fixed sinkage
    L_small = drive.contact_length_from_sinkage(0.10, 0.02)
    L_big = drive.contact_length_from_sinkage(0.30, 0.02)
    assert L_big > L_small
    # matches the rigid-wheel chord closed form
    z = 0.02
    expected = 2.0 * math.sqrt(r * z - 0.25 * z * z)
    assert math.isclose(drive.contact_length_from_sinkage(r, z), expected, rel_tol=1e-9)


def test_t03_larger_wheel_reduces_sinkage_via_contact_patch():
    """T-03: a wheel with a LARGER radius spreads the same normal load over a longer sinkage-dependent
    contact patch, so it sinks LESS (lower Bekker pressure). With the old fixed rectangle the wheel
    radius never entered the contact area, so two wheels of different radius sank identically. The
    resolved contact length is reported in telemetry."""
    cs = _ramp(20.0)
    _, _, t_small = drive.drive_step(cs, (48.0, 20.0), 0.0, 0.2, 0.0, dt=0.1, wheel_radius_m=0.10)
    cs2 = _ramp(20.0)
    _, _, t_big = drive.drive_step(cs2, (48.0, 20.0), 0.0, 0.2, 0.0, dt=0.1, wheel_radius_m=0.30)
    assert "contact_len_m" in t_small                     # resolved patch reported
    assert t_big["contact_len_m"] > t_small["contact_len_m"]   # bigger wheel -> longer patch
    assert t_big["sinkage_m"] < t_small["sinkage_m"]      # bigger wheel sinks less


def test_t01_entrapment_zeros_forward_and_yaw_motion():
    """T-01: when the slip-sinkage equilibrium reports ENTRAPPED, a step must produce ZERO forward
    translation and ZERO yaw change (a discrete stuck state), not creep forward at (1-s_max)*v_cmd
    and slowly spin. Before the fix v_ach = (1-0.99)*v_cmd moved the rover ~0.01*v_cmd/step and
    omega_ach likewise, so repeated commands under unchanged conditions translated and rotated it."""
    cs = _ramp(58.0)                                    # steep enough to entrap a 30 kg rover
    rc0, yaw0 = (48.0, 20.0), 0.3
    rc, yaw, telem = drive.drive_step(cs, rc0, yaw0, 0.2, 0.4, dt=0.2)
    assert telem["entrapped"] is True                   # the precondition: we are stuck
    assert telem["v_achieved"] == 0.0                   # no forward creep while entrapped
    assert telem["omega_achieved"] == 0.0               # no yaw authority while entrapped
    assert rc == rc0                                     # pose did not translate
    assert yaw == yaw0                                   # pose did not rotate


def test_t01_entrapment_no_terrain_self_improvement_no_escape():
    """T-01: repeated identical commands under an unchanged entrapped condition must not let the rover
    translate or self-improve terrain into an escape. The mass field (which carving ruts would change)
    must be byte-identical across repeated stuck steps, and the rover must stay put."""
    cs = _ramp(58.0)
    rc, yaw = (48.0, 20.0), 0.0
    rc, yaw, t0 = drive.drive_step(cs, rc, yaw, 0.2, 0.0, dt=0.2)
    assert t0["entrapped"] is True
    mass_after_first = cs.mass_areal.copy()
    density_after_first = cs.density.copy()
    rc_stuck = rc
    for _ in range(20):                                 # hammer the same command 20 more times
        rc, yaw, t = drive.drive_step(cs, rc, yaw, 0.2, 0.0, dt=0.2)
        assert t["entrapped"] is True
    assert rc == rc_stuck                               # never escaped by numerical creep
    # terrain did not self-improve: no rut carving advanced the escape
    assert np.array_equal(cs.mass_areal, mass_after_first)
    assert np.array_equal(cs.density, density_after_first)


def test_t05_lateral_scrub_grows_effective_turn_radius():
    """T-05: a real skid-steer turn must SCRUB laterally — the wheels slide sideways, lateral terramechanics
    resists the yaw moment, so the ACHIEVED turn radius is LARGER than the ideal kinematic v/omega. The old
    scalar model (omega_ach = (1-slip)*omega_cmd) scaled v and omega by the SAME factor, leaving the radius
    r = v/omega exactly the commanded kinematic radius regardless of soil. With per-side lateral scrub the
    yaw under-achieves MORE than the forward speed, so the effective radius grows on weak soil."""
    cs = _flat()
    v_cmd, omega_cmd = 0.2, 0.6
    r_kin = v_cmd / omega_cmd                              # ideal kinematic turn radius
    _, _, t = drive.drive_step(cs, (48.0, 48.0), 0.0, v_cmd, omega_cmd, dt=0.1, skid_steer=True)
    # achieved instantaneous radius from achieved v / achieved omega
    assert t["omega_achieved"] != 0.0
    r_eff = abs(t["v_achieved"] / t["omega_achieved"])
    assert r_eff > r_kin * (1.0 + 1e-6)                    # lateral scrub widens the turn
    # and the yaw is degraded MORE than the forward speed (scrub is an extra yaw-specific loss)
    yaw_frac = abs(t["omega_achieved"]) / abs(omega_cmd)
    v_frac = abs(t["v_achieved"]) / abs(v_cmd)
    assert yaw_frac < v_frac - 1e-6


def test_t05_differential_loading_on_cross_slope_changes_yaw():
    """T-05: on a CROSS-SLOPE the two sides carry different normal load (T-04 lateral transfer), so they
    develop different per-side thrust — a straight command (omega=0) should NOT yaw symmetrically, and a
    turn outcome must differ from the same turn on flat ground. A single scalar longitudinal slip cannot
    express per-side differential loading. Here: the achieved yaw of a turn on a cross-slope differs from
    the achieved yaw of the identical command on flat ground."""
    flat = _flat()
    cross = _ramp(18.0, grid=96, cell=0.02)               # +col grade; at yaw=pi/2 forward is +row -> cross-slope
    cmd = (0.2, 0.5)
    _, yaw_flat, tf = drive.drive_step(flat, (48.0, 48.0), math.pi / 2, *cmd, dt=0.1, skid_steer=True)
    _, yaw_cross, tc = drive.drive_step(cross, (48.0, 48.0), math.pi / 2, *cmd, dt=0.1, skid_steer=True)
    # the per-side differential loading on the cross-slope changes the achieved yaw rate vs flat
    assert not math.isclose(tc["omega_achieved"], tf["omega_achieved"], rel_tol=1e-6, abs_tol=1e-9)


def test_t05_per_side_speeds_reported_in_telemetry():
    """T-05: the telemetry must expose the per-side commanded/achieved speeds and per-side slip so a
    consumer can convert to wheel commands and see the differential. The old model carried only a single
    scalar slip and no per-side breakdown."""
    cs = _flat()
    _, _, t = drive.drive_step(cs, (48.0, 48.0), 0.0, 0.2, 0.5, dt=0.1, skid_steer=True)
    assert "v_left_cmd" in t and "v_right_cmd" in t       # per-side commanded speeds
    assert "v_left_ach" in t and "v_right_ach" in t       # per-side achieved speeds
    # the turn commands the two sides at different speeds (the differential that makes a skid-steer turn)
    assert t["v_left_cmd"] != t["v_right_cmd"]


def test_terra01_scrub_telemetry_carries_its_evidence_status():
    """TERRA-01: the lateral-scrub interpolation that throttles yaw (scrub_factor) is a MODELING CHOICE,
    not a soil law derived from Janosi-Hanamoto lateral shear or calibrated against measured skid-steer
    data. The code formerly commented 'no invented coefficient' / 'no fabricated coefficients', which
    OVERCLAIMS its provenance. A consumer must be able to read the evidence status off the telemetry so a
    downstream report never presents the modelled turn radius as a calibrated number."""
    cs = _flat()
    _, _, t = drive.drive_step(cs, (48.0, 48.0), 0.0, 0.2, 0.5, dt=0.1, skid_steer=True)
    assert t.get("scrub_evidence") == "ASSUMPTION"        # honest provenance, exposed alongside scrub_factor
    assert "scrub_factor" in t                             # the value it qualifies is present
    # a straight-line drive (no skid-steer turn block) carries no scrub claim at all
    _, _, t_straight = drive.drive_step(cs, (48.0, 48.0), 0.0, 0.2, 0.0, dt=0.1, skid_steer=False)
    assert "scrub_evidence" not in t_straight


def test_a02_vehicle_mass_geometry_propagates_into_drive():
    """A-02: a 30 kg IPEx and a 65 kg RASSOR-2, driven IDENTICALLY through the exact runtime
    call (drive_step(**twin.drive_context())), must produce DIFFERENT slip/sinkage/position.

    The drive model must consume the RESOLVED vehicle mass + wheel count (not the K.* module
    globals), so the heavier vehicle puts more load per wheel and therefore slips/sinks more on
    the same grade. Before the fix drive_context() omitted mass/n_wheels and drive.py used
    K.ROVER_MASS_DRY_KG, so the two were byte-identical."""
    import numpy as np

    from stewie.physics import drive
    from stewie.physics.column_state import ColumnState
    from stewie.specs.vehicle_twin import VehicleTwin

    ipex = VehicleTwin.assemble("ip", vehicle="ipex", body="moon")
    rassor2 = VehicleTwin.assemble("r2", vehicle="rassor2", body="moon")
    assert ipex.mass_kg < rassor2.mass_kg          # 30 kg vs 65 kg -- the sourced difference

    def fresh():
        cs = ColumnState(width=64, height=64, cell_m=0.02, mass_areal=np.full((64, 64), 50.0))
        # a moderate grade (~9 deg) so both vehicles develop real, distinct slip without either
        # saturating into entrapment (the T-03 sinkage-resolved contact patch makes the heavier
        # vehicle's deeper rut a LONGER patch, so slip ordering is now load-and-soil nuanced).
        cs.datum[:, :] = np.tile(np.linspace(0.0, 0.20, 64)[None, :], (64, 1)) - (cs.derive_height() - cs.datum)
        return cs

    _, _, t_light = drive.drive_step(fresh(), (32.0, 20.0), 0.0, 0.25, 0.0, dt=0.2,
                                     **ipex.drive_context())
    _, _, t_heavy = drive.drive_step(fresh(), (32.0, 20.0), 0.0, 0.25, 0.0, dt=0.2,
                                     **rassor2.drive_context())
    # the heavier vehicle puts more load per wheel -> it sinks DEEPER on the identical grade
    # (the robust, analytically-expected ordering that proves mass propagated end to end).
    assert t_heavy["sinkage_m"] > t_light["sinkage_m"]
    # the resolved per-vehicle contact geometry differs (different wheel radius + sinkage -> patch)
    assert t_heavy["contact_len_m"] != t_light["contact_len_m"]
    # the two vehicles produce DISTINCT slip and therefore DISTINCT achieved motion (propagation works)
    assert t_heavy["slip"] != t_light["slip"]
    assert t_heavy["v_achieved"] != t_light["v_achieved"]


def test_h10_drive_context_propagates_skid_steer_to_runtime():
    """Audit H-10 (2026-06-13): VehicleTwin.drive_context() must carry the skid-steer drivetrain model
    (flag + lateral track) so the RUNTIME drive loop (process._twist -> drive_step(**ctx)) slip-couples
    yaw instead of keeping full commanded yaw authority. IPEx is a 4-wheel skid-steer; on a high-slip
    grade the achieved yaw under-achieves like (1-slip)."""
    import numpy as np

    from stewie.physics import drive
    from stewie.physics.column_state import ColumnState
    from stewie.specs.vehicle_twin import VehicleTwin

    ctx = VehicleTwin.assemble("t", vehicle="ipex", body="moon").drive_context()
    assert ctx["skid_steer"] is True and ctx["track_m"] > 0.0        # the drivetrain model is propagated
    cs = ColumnState(width=64, height=64, cell_m=0.02, mass_areal=np.full((64, 64), 50.0))
    # a real grade below the T-03 entrapment threshold so yaw is degraded (not fully stalled).
    cs.datum[:, :] = np.tile(np.linspace(0.0, 0.30, 64)[None, :], (64, 1)) - (cs.derive_height() - cs.datum)
    _, _, telem = drive.drive_step(cs, (32.0, 20.0), 0.0, 0.25, 0.4, dt=0.2, **ctx)   # exactly the runtime call
    assert telem["slip"] > 0.05                                      # the grade produces real slip
    assert telem["track_m"] is not None                             # skid-steer telemetry active (propagated)
    assert telem["omega_achieved"] < telem["omega_cmd"]             # yaw degraded by the traction deficit
