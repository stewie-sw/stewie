"""NV-05: the reactive replan loop. Uses REAL Rock records (dart.rock_taxonomy.classify) as the observed
hazards -- no fabricated obstacle data; the geometry (sensor range, keep-out circles, deviation) is the
problem input. Exercises the detect -> keep-out -> local/global replan decision."""
import pytest

from dart.rock_taxonomy import classify
from lode import reactive_nav as RN


def _rock(diameter_m=1.0):
    """A real Rock record; a 1 m boulder bins to nav-class D/E -> an obstacle the loop must avoid."""
    rk = classify(diameter_m=diameter_m)
    assert rk.is_obstacle                                          # guard: the fixture really is an obstacle
    return rk


def test_no_new_hazard_on_route_does_not_replan():
    out = RN.react((0.0, 0.0), 0.0, (20.0, 0.0), planned_path=[(0.0, 0.0), (20.0, 0.0)],
                   hazards_world=[], deviation_max_m=2.0)
    assert out["replan"] is False and out["scope"] == "none" and out["new_hazards"] == []


def test_discovered_hazard_becomes_keepout_and_triggers_local_replan():
    """[REQ:NV-05] an observed hazard becomes a dynamic keep-out and triggers a local replan around it."""
    rk = _rock(1.0)
    out = RN.react((0.0, 0.0), 0.0, (20.0, 0.0), planned_path=[(0.0, 0.0), (20.0, 0.0)],
                   hazards_world=[(8.0, 0.0, rk)], sensor_range_m=18.0, horizon_m=10.0, clearance_m=0.5)
    assert out["replan"] is True and out["scope"] == "local" and len(out["new_hazards"]) == 1
    ko = out["keepouts"][-1]
    assert ko[0] == 8.0 and ko[1] == 0.0 and ko[2] == pytest.approx(0.5 + 0.5)   # diam/2 + clearance
    assert out["local_plan"]["feasible"] and abs(out["local_plan"]["curvature"]) > 0   # steered off the straight line


def test_hazard_blocking_every_local_arc_escalates_to_global():
    rk = _rock(1.0)
    out = RN.react((0.0, 0.0), 0.0, (20.0, 0.0), planned_path=[(0.0, 0.0), (20.0, 0.0)],
                   hazards_world=[(8.0, 0.0, rk)], is_blocked=lambda x, y: True)
    assert out["replan"] is True and out["scope"] == "global" and out["local_plan"] is None


def test_deviation_off_route_triggers_replan_with_no_hazard():
    out = RN.react((10.0, 9.0), 0.0, (20.0, 0.0), planned_path=[(0.0, 0.0), (20.0, 0.0)],
                   hazards_world=[], deviation_max_m=2.0)
    assert out["replan"] is True and out["deviation_m"] > 2.0 and out["new_hazards"] == []


def test_known_hazard_is_not_rediscovered():
    rk = _rock(1.0)
    out = RN.react((0.0, 0.0), 0.0, (20.0, 0.0), planned_path=[(0.0, 0.0), (20.0, 0.0)],
                   hazards_world=[(8.0, 0.0, rk)], known_hazards=[{"x": 8.0, "y": 0.0}], deviation_max_m=2.0)
    assert out["new_hazards"] == [] and out["replan"] is False     # already known -> not a fresh trigger


def test_out_of_range_hazard_is_not_yet_seen():
    rk = _rock(1.0)
    out = RN.react((0.0, 0.0), 0.0, (60.0, 0.0), planned_path=[(0.0, 0.0), (60.0, 0.0)],
                   hazards_world=[(50.0, 0.0, rk)], sensor_range_m=18.0, deviation_max_m=2.0)
    assert out["new_hazards"] == [] and out["replan"] is False     # 50 m away, beyond the 18 m sensor
