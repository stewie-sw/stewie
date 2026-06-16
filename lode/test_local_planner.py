"""NV-03: the local constant-curvature trajectory planner. The arc geometry + keep-out / rock feasibility
+ goal-progress selection are pure geometry (problem inputs, not fabricated terrain). The terrain
integration test drives the planner off the REAL LOLA Haworth slope map -- no synthetic DEM."""
import math
import os

import numpy as np
import pytest

from lode import local_planner as LP


# --- arc geometry --------------------------------------------------------------------------------
def test_straight_arc_goes_dead_ahead():
    a = LP.constant_curvature_arc(0.0, 0.0, 0.0, 0.0, 10.0, n_pts=11)
    assert a[-1, 0] == pytest.approx(10.0) and a[-1, 1] == pytest.approx(0.0)
    assert a[-1, 2] == pytest.approx(0.0)                          # heading unchanged on a straight arc


def test_left_arc_curves_left_and_turns_heading():
    a = LP.constant_curvature_arc(0.0, 0.0, 0.0, 0.2, 10.0, n_pts=21)
    assert a[-1, 1] > 0.0                                          # +kappa from heading 0 bends +y (left)
    assert a[-1, 2] == pytest.approx(0.2 * 10.0)                   # theta = th0 + kappa*length
    steps = np.hypot(np.diff(a[:, 0]), np.diff(a[:, 1]))
    assert np.allclose(steps, steps[0], rtol=0.02)                # equal arc-length spacing (chord~arc)


def test_curvature_fan_is_symmetric_and_includes_straight():
    fan = LP.curvature_fan(max_kappa=0.3, n=7)
    assert 0.0 in fan and min(fan) == pytest.approx(-0.3) and max(fan) == pytest.approx(0.3)
    assert sorted(fan) == fan and all(abs(-k) in [abs(x) for x in fan] for k in fan)   # symmetric


# --- planning ------------------------------------------------------------------------------------
def test_picks_straight_toward_a_dead_ahead_goal_when_clear():
    out = LP.plan_local((0.0, 0.0), 0.0, (20.0, 0.0))
    assert out["feasible"] and abs(out["curvature"]) < 1e-9        # straight is optimal toward a dead-ahead goal
    assert out["progress_m"] > 0 and out["n_feasible"] == out["n_sampled"]


def test_steers_around_a_keepout_blocking_the_straight_path():
    out = LP.plan_local((0.0, 0.0), 0.0, (20.0, 0.0), keepouts=[(8.0, 0.0, 2.0)],
                        horizon_m=10.0, clearance_m=0.5)
    assert out["feasible"] and abs(out["curvature"]) > 0.0         # had to curve off the blocked straight line
    for x, y, _th in out["arc"]:                                   # and the chosen arc actually clears it
        assert math.hypot(x - 8.0, y - 0.0) > 2.0 + 0.5 - 1e-6


def test_reports_infeasible_when_every_arc_is_blocked():
    out = LP.plan_local((0.0, 0.0), 0.0, (20.0, 0.0), is_blocked=lambda x, y: True)
    assert out["feasible"] is False and out["n_feasible"] == 0 and "blocked" in out["reason"]


def test_rejects_nonphysical_inputs():
    with pytest.raises(ValueError):
        LP.constant_curvature_arc(0.0, 0.0, 0.0, 0.0, 10.0, n_pts=1)     # need >= 2 samples
    with pytest.raises(ValueError):
        LP.constant_curvature_arc(0.0, 0.0, 0.0, 0.0, -1.0)             # negative arc length
    with pytest.raises(ValueError):
        LP.curvature_fan(max_kappa=0.0)                                 # non-positive curvature bound


def test_runs_on_real_haworth_slope_as_the_obstacle_oracle():
    """[REQ:NV-03] Drive the planner with a terrain predicate built from the REAL LOLA Haworth slope map (no
    synthetic DEM). From the FLATTEST cell the fan yields a feasible arc; the planner consumes real DEM data."""
    from stewie.terrain.site_dem import slope_deg_map
    dem_dir = os.path.join(os.path.dirname(__file__), os.pardir, "samples", "lunar_dem", "haworth_10km_5m")
    hm, meta = os.path.join(dem_dir, "heightmap.rf32"), os.path.join(dem_dir, "metadata.json")
    if not (os.path.exists(hm) and os.path.exists(meta)):
        pytest.skip(f"real LOLA backbone absent: {dem_dir}")
    import json
    with open(meta) as fh:
        g = json.load(fh)["grid"]
    h, w = int(g["height"]), int(g["width"])
    cell_m = 5.0
    Z = np.fromfile(hm, dtype="<f4").reshape(h, w)
    # a small real patch around the tile centre
    r0, c0 = h // 2, w // 2
    patch = Z[r0:r0 + 60, c0:c0 + 60]
    slope = slope_deg_map(patch, cell_m)                          # REAL per-cell slope (degrees)
    cap = 20.0

    def is_blocked(x, y):                                         # world (m) -> patch cell -> real slope
        c, r = int(round(x / cell_m)), int(round(y / cell_m))
        if not (0 <= r < slope.shape[0] and 0 <= c < slope.shape[1]):
            return True                                           # off-patch = unsafe (NV-01: never leave the map)
        return bool(slope[r, c] > cap)

    fr, fc = np.unravel_index(int(np.argmin(slope)), slope.shape)  # flattest real cell = the start
    start = (fc * cell_m, fr * cell_m)
    goal = (start[0] + 30.0, start[1])
    out = LP.plan_local(start, 0.0, goal, is_blocked=is_blocked, horizon_m=8.0, clearance_m=0.0)
    assert out["n_sampled"] == len(LP.curvature_fan())            # consumed the real predicate without error
    assert out["feasible"] is True                               # the flattest start admits at least one safe arc


# --- NV-04: path tracker -------------------------------------------------------------------------
def test_bounded_twist_is_linear_capped_on_a_gentle_arc():
    v, w = LP.bounded_twist(0.05, v_max=0.30, omega_max=0.20)     # 0.05*0.30=0.015 < 0.20 -> v not yaw-bound
    assert v == pytest.approx(0.30) and w == pytest.approx(0.05 * 0.30)


def test_bounded_twist_is_yaw_capped_on_a_sharp_turn():
    v, w = LP.bounded_twist(2.0, v_max=0.30, omega_max=0.20)      # 0.30*2=0.6 > 0.20 -> slows to v=0.20/2=0.10
    assert v == pytest.approx(0.10) and abs(w) == pytest.approx(0.20)


def test_track_arc_reports_bounded_command_speed_and_duration():
    """[REQ:NV-04] a trajectory -> a bounded twist command with expected speed + progress."""
    out = LP.track_arc(0.0, 6.0, v_max=0.30, omega_max=0.20)
    assert out["v_cmd"] == pytest.approx(0.30) and out["omega_cmd"] == pytest.approx(0.0)
    assert out["expected_speed_ms"] == pytest.approx(0.30) and out["duration_s"] == pytest.approx(20.0)
    assert out["arc_length_m"] == pytest.approx(6.0)


def test_track_arc_slip_derate_slows_and_lengthens():
    nom = LP.track_arc(0.0, 6.0)
    der = LP.track_arc(0.0, 6.0, speed_scale=0.5)                 # (1 - slip) = 0.5
    assert der["expected_speed_ms"] == pytest.approx(nom["expected_speed_ms"] * 0.5)
    assert der["duration_s"] == pytest.approx(nom["duration_s"] * 2.0)


def test_track_plan_consumes_an_nv03_plan():
    plan = LP.plan_local((0.0, 0.0), 0.0, (20.0, 0.0))
    out = LP.track_plan(plan)
    assert out["v_cmd"] > 0 and out["duration_s"] > 0 and out["arc_length_m"] > 0
    assert "progress_m" in out


def test_track_plan_refuses_an_infeasible_plan():
    plan = LP.plan_local((0.0, 0.0), 0.0, (20.0, 0.0), is_blocked=lambda x, y: True)
    with pytest.raises(ValueError, match="infeasible"):
        LP.track_plan(plan)


def test_track_arc_rejects_bad_speed_scale():
    with pytest.raises(ValueError):
        LP.track_arc(0.0, 6.0, speed_scale=1.5)
