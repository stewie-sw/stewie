"""#161: return-to-lander feasibility -- at its furthest excursion the rover must retain enough charge to
drive back to the lander, plus an ADJUSTABLE buffer. Pure + parametric (the planner supplies the reach,
the energy already spent, the battery, and the grounded drive J/m), so this is a numerical-method test."""
import pytest

from lode import lander_return as LR


def test_furthest_reach_is_the_max_distance_from_the_lander():
    lander = (10.0, 10.0)
    pts = [(10.0, 10.0), (13.0, 14.0), (10.0, 40.0)]      # distances 0, 5, 30
    assert LR.furthest_reach_from_lander_m(lander, pts) == pytest.approx(30.0)
    assert LR.furthest_reach_from_lander_m(lander, []) == 0.0


def test_feasible_when_remaining_charge_covers_the_buffered_return():
    # 50 m back at 135 J/m = 6750 J; +20% buffer = 8100 J; 30000 J battery, 10000 J spent -> 20000 remain
    r = LR.return_to_lander_feasible(furthest_reach_m=50.0, energy_spent_at_reach_j=10000.0,
                                     battery_j=30000.0, drive_j_per_m=135.0, return_buffer_frac=0.20)
    assert r["feasible"] is True
    assert r["return_energy_J"] == pytest.approx(6750.0)
    assert r["reserve_with_buffer_J"] == pytest.approx(8100.0)
    assert r["remaining_J"] == pytest.approx(20000.0)
    assert r["margin_J"] == pytest.approx(11900.0)


def test_infeasible_when_too_far_or_too_drained():
    r = LR.return_to_lander_feasible(furthest_reach_m=200.0, energy_spent_at_reach_j=10000.0,
                                     battery_j=30000.0, drive_j_per_m=135.0, return_buffer_frac=0.20)
    assert r["feasible"] is False and r["margin_J"] < 0      # 200 m return (32400 J buffered) > 20000 J remaining


def test_larger_buffer_demands_more_reserve_and_can_flip_feasibility():
    kw = dict(furthest_reach_m=120.0, energy_spent_at_reach_j=10000.0, battery_j=30000.0, drive_j_per_m=135.0)
    lo = LR.return_to_lander_feasible(**kw, return_buffer_frac=0.0)    # bare return = 16200 J <= 20000 remain
    hi = LR.return_to_lander_feasible(**kw, return_buffer_frac=0.5)    # +50% = 24300 J > 20000 remain
    assert hi["reserve_with_buffer_J"] > lo["reserve_with_buffer_J"]
    assert lo["feasible"] is True and hi["feasible"] is False          # the adjustable buffer flips it


def test_rejects_nonphysical_inputs():
    base = dict(furthest_reach_m=10.0, energy_spent_at_reach_j=0.0, battery_j=30000.0, drive_j_per_m=135.0)
    for bad in [{"furthest_reach_m": -1.0}, {"battery_j": 0.0}, {"drive_j_per_m": 0.0},
                {"return_buffer_frac": -0.1}]:
        with pytest.raises(ValueError):
            LR.return_to_lander_feasible(**{**base, **bad})
