"""#161-B: the planner carries the lander + an adjustable return buffer, and every plan's totals report
the return-to-lander feasibility (mission_from_dict parse + the _return_to_lander block). Real grounded
constants (BATTERY_J, RESERVE_FRAC, DRIVE_J_PER_M); no fabricated values."""
import pytest

from lode import mission_planner as MP
from lode import relocalization as REL


def _payload(lander=None, return_buffer_frac=None):
    p = {"name": "RTL", "body": "moon", "charger": [0, 0],
         "orders": [{"action": "Level pad", "kind": "cut", "x": 40, "y": 30, "footprint_m2": 36, "depth_m": 0.04}]}
    if lander is not None:
        p["lander"] = lander
    if return_buffer_frac is not None:
        p["return_buffer_frac"] = return_buffer_frac
    return p


def test_mission_from_dict_parses_lander_and_buffer():
    m = MP.mission_from_dict(_payload(lander=[120, 0], return_buffer_frac=0.35))
    assert m.lander == (120.0, 0.0)
    assert m.return_buffer_frac == 0.35


def test_lander_defaults_to_charger_when_absent():
    m = MP.mission_from_dict(_payload())                       # no lander given
    assert m.lander is None
    assert MP._return_to_lander(m)["lander_xy"] == [0.0, 0.0]  # falls back to the charger (0,0)


def test_return_to_lander_block_shape_and_buffer_effect():
    lo = MP._return_to_lander(MP.mission_from_dict(_payload(lander=[0, 0], return_buffer_frac=0.0)))
    hi = MP._return_to_lander(MP.mission_from_dict(_payload(lander=[0, 0], return_buffer_frac=0.5)))
    for blk in (lo, hi):
        assert {"feasible", "return_distance_m", "reserve_with_buffer_J", "margin_J", "lander_xy"} <= set(blk)
    assert lo["return_distance_m"] == pytest.approx(50.0)      # furthest order (40,30) is 50 m from (0,0)
    assert hi["reserve_with_buffer_J"] > lo["reserve_with_buffer_J"]   # a bigger buffer demands more reserve
    assert hi["margin_J"] < lo["margin_J"]


def test_plan_totals_include_return_to_lander():
    m = MP.mission_from_dict(_payload(lander=[10, 0]))
    *_rest, totals = MP.plan(m).as_tuple()
    assert "return_to_lander" in totals and "feasible" in totals["return_to_lander"]


def test_plan_totals_include_relocalization_with_bounded_drift():
    # #96: every plan reports scheduled SN-10 parallax relocalization stops; the schedule holds the
    # dead-reckoned drift under the tolerance by construction, and each fix carries a grounded energy.
    m = MP.mission_from_dict(_payload())
    *_rest, totals = MP.plan(m).as_tuple()
    rl = totals["relocalization"]
    assert {"n_fixes", "fix_distances_m", "max_drift_m", "total_energy_J", "max_run_m"} <= set(rl)
    assert rl["max_drift_m"] <= MP.RELOCALIZE_DRIFT_TOL_M + 1e-9
    assert rl["max_run_m"] == pytest.approx(MP.RELOCALIZE_DRIFT_TOL_M / REL.DEFAULT_DRIFT_FRAC)


def test_negative_buffer_rejected_at_parse():
    with pytest.raises(ValueError):
        MP.mission_from_dict(_payload(return_buffer_frac=-0.1))
