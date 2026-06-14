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
    """ARGUS T1.2: with skid_steer=True, yaw comes from DIFFERENTIAL thrust over the documented
    0.5207 m track -- the same slip that robs forward progress robs the speed differential, so
    omega under-achieves on low-traction slopes exactly as v does. Default path: byte-identical."""
    import numpy as np

    from stewie.physics import drive
    from stewie.physics.column_state import ColumnState
    from stewie.specs import ipex_specs as ix

    def fresh():
        cs = ColumnState(width=64, height=64, cell_m=0.02,
                         mass_areal=np.full((64, 64), 50.0))
        ramp = np.tile(np.linspace(0.0, 0.55, 64)[None, :], (64, 1))   # a steep grade -> real slip
        cs.datum = cs.datum + ramp - cs.derive_height() + cs.derive_height() * 0  # raise surface
        cs.datum[:, :] = ramp - (cs.derive_height() - cs.datum)
        return cs

    # default path unchanged (zero-regression bar)
    a = drive.drive_step(fresh(), (32.0, 20.0), 0.0, 0.25, 0.4, dt=0.2)
    b = drive.drive_step(fresh(), (32.0, 20.0), 0.0, 0.25, 0.4, dt=0.2)
    assert a[1] == b[1]                                   # deterministic baseline
    # skid-steer truth: on the slope, achieved yaw < commanded yaw, scaled like (1-slip)
    rc, yaw_t, telem = drive.drive_step(fresh(), (32.0, 20.0), 0.0, 0.25, 0.4, dt=0.2,
                                        skid_steer=True, track_m=ix.SKID_STEER_TRACK_M)
    assert telem["slip"] > 0.05                           # the grade produces real slip
    assert telem["omega_achieved"] == telem["omega_cmd"] * (1.0 - telem["slip"])
    assert abs(yaw_t) < abs(a[1]) or telem["slip"] == 0.0  # yaw under-achieves vs the ideal path


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
    cs.datum[:, :] = np.tile(np.linspace(0.0, 0.55, 64)[None, :], (64, 1)) - (cs.derive_height() - cs.datum)
    _, _, telem = drive.drive_step(cs, (32.0, 20.0), 0.0, 0.25, 0.4, dt=0.2, **ctx)   # exactly the runtime call
    assert telem["slip"] > 0.05                                      # the grade produces real slip
    assert telem["track_m"] is not None                             # skid-steer telemetry active (propagated)
    assert telem["omega_achieved"] < telem["omega_cmd"]             # yaw degraded by the traction deficit
