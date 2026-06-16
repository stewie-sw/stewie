"""#96 (SN-10 tie-in B): the relocalization-stop scheduler. Pure + deterministic; the drift model and
the per-fix cost are grounded (autonomy.ODOM_DRIFT_FRAC; the ARGUS fix = arm_raise_lift_energy_j + an
~8 s articulation maneuver) but passed in, so this is a numerical-method test, not fabricated data."""
import pytest

from lode import relocalization as R


def test_no_fix_needed_when_drift_stays_under_tolerance():
    # a short traverse: cumulative drift never reaches the tolerance -> zero fixes, drift reported < tol
    s = R.schedule_relocalization_stops(5.0, drift_tol_m=0.5, drift_frac=0.05)
    assert s["n_fixes"] == 0 and s["fix_distances_m"] == []
    assert s["max_drift_m"] == pytest.approx(0.25)        # 0.05/m * 5 m
    assert s["max_drift_m"] <= 0.5
    assert s["total_time_s"] == 0.0 and s["total_energy_J"] == 0.0


def test_fixes_inserted_every_tol_over_drift_frac_metres():
    # 0.5 m tol / 0.05 per-m -> a fix every 10 m; 100 m -> 9 interior fixes (10 segments of 10 m)
    s = R.schedule_relocalization_stops(100.0, drift_tol_m=0.5, drift_frac=0.05,
                                        fix_maneuver_s=8.0, per_fix_energy_j=100.0)
    assert s["max_run_m"] == pytest.approx(10.0)
    assert s["n_fixes"] == 9
    assert s["fix_distances_m"] == [10, 20, 30, 40, 50, 60, 70, 80, 90]
    assert s["total_time_s"] == pytest.approx(72.0)       # 9 * 8 s
    assert s["total_energy_J"] == pytest.approx(900.0)    # 9 * 100 J
    assert s["max_drift_m"] <= 0.5 + 1e-9                 # schedule holds drift under tol


def test_schedule_holds_drift_under_tolerance_across_distances_and_rates():
    for D in (0.0, 9.99, 10.0, 37.0, 250.0):
        for tol, frac in [(0.5, 0.05), (0.2, 0.05), (1.0, 0.08)]:
            s = R.schedule_relocalization_stops(D, drift_tol_m=tol, drift_frac=frac)
            assert s["max_drift_m"] <= tol + 1e-9, (D, tol, frac, s)
            # every fix sits strictly inside the traverse, in increasing order
            assert all(0 < d < D for d in s["fix_distances_m"])
            assert s["fix_distances_m"] == sorted(s["fix_distances_m"])


def test_residual_widens_the_run_and_must_be_below_tolerance():
    # a non-zero post-fix residual leaves less drift budget per run -> shorter runs / more fixes
    base = R.schedule_relocalization_stops(100.0, drift_tol_m=0.5, drift_frac=0.05, fix_residual_m=0.0)
    res = R.schedule_relocalization_stops(100.0, drift_tol_m=0.5, drift_frac=0.05, fix_residual_m=0.2)
    assert res["max_run_m"] < base["max_run_m"]           # (0.5-0.2)/0.05 = 6 m < 10 m
    assert res["n_fixes"] >= base["n_fixes"]
    with pytest.raises(ValueError):
        R.schedule_relocalization_stops(50.0, drift_tol_m=0.2, drift_frac=0.05, fix_residual_m=0.2)


def test_rejects_nonphysical_inputs():
    with pytest.raises(ValueError):
        R.schedule_relocalization_stops(-1.0, drift_tol_m=0.5, drift_frac=0.05)
    with pytest.raises(ValueError):
        R.schedule_relocalization_stops(10.0, drift_tol_m=0.5, drift_frac=0.0)
