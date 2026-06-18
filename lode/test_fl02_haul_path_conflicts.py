"""FL-02: continuous moving HAUL-PATH crossing detection -- two vehicles whose drive legs pass within a
safe-separation radius at OVERLAPPING times. Reported as `haul_path_conflicts` in the fleet totals,
complementing same-site (`_vehicle_conflicts`), shared-charger, and stationary-crowding (`_temporal_conflicts`)
detection. Pure geometry; a reported fleet-safety metric (re-sequencing on a crossing is future MV work)."""
import copy

import lode.mission_planner as MP


def test_seg_seg_min_dist_basic():
    assert MP._seg_seg_min_dist((-1, 0), (1, 0), (0, -1), (0, 1)) < 1e-9      # crossing at origin -> ~0
    assert abs(MP._seg_seg_min_dist((0, 0), (10, 0), (0, 5), (10, 5)) - 5.0) < 1e-9   # parallel, 5 m apart
    assert abs(MP._seg_seg_min_dist((0, 0), (0, 0), (3, 4), (3, 4)) - 5.0) < 1e-9     # degenerate point-point


def _veh(segs):
    return {"tl": [{"kind": "drive", "x0": s[0], "y0": s[1], "x1": s[2], "y1": s[3],
                    "t0": s[4], "t1": s[5]} for s in segs]}


def test_crossing_paths_overlapping_time_is_a_conflict():
    pv = [_veh([(-10, 0, 10, 0, 0.0, 100.0)]),          # W->E through origin, t 0..100
          _veh([(0, -10, 0, 10, 50.0, 150.0)])]         # S->N through origin, t 50..150 (overlaps)
    assert MP._haul_path_conflicts(pv) == 1


def test_same_paths_disjoint_time_is_clear():
    pv = [_veh([(-10, 0, 10, 0, 0.0, 100.0)]),
          _veh([(0, -10, 0, 10, 200.0, 300.0)])]        # crosses in space but NOT in time
    assert MP._haul_path_conflicts(pv) == 0


def test_far_apart_paths_clear():
    pv = [_veh([(-10, 0, 10, 0, 0.0, 100.0)]),
          _veh([(-10, 500, 10, 500, 0.0, 100.0)])]      # parallel, 500 m apart, same time
    assert MP._haul_path_conflicts(pv) == 0


def test_same_vehicle_legs_never_conflict():
    pv = [_veh([(-10, 0, 10, 0, 0.0, 100.0), (0, -10, 0, 10, 50.0, 150.0)])]
    assert MP._haul_path_conflicts(pv) == 0              # one vehicle cannot collide with itself


def test_stationary_drive_segments_ignored():
    pv = [_veh([(5, 5, 5, 5, 0.0, 100.0)]), _veh([(5, 5, 5, 5, 0.0, 100.0)])]
    assert MP._haul_path_conflicts(pv) == 0              # zero-length legs are not haul paths


_ORDERS = [
    {"action": "cutA", "kind": "cut", "x": 20.0, "y": 0.0, "footprint_m2": 9.0, "depth_m": 0.2},
    {"action": "cutB", "kind": "cut", "x": -20.0, "y": 0.0, "footprint_m2": 9.0, "depth_m": 0.2},
    {"action": "fillA", "kind": "fill", "x": 40.0, "y": 0.0, "footprint_m2": 9.0, "depth_m": 0.2},
    {"action": "fillB", "kind": "fill", "x": -40.0, "y": 0.0, "footprint_m2": 9.0, "depth_m": 0.2},
]


def _mk():
    return MP.mission_from_dict({"name": "S", "body": "moon", "charger": [0, 0], "orders": copy.deepcopy(_ORDERS)})


def test_plan_multi_reports_haul_path_conflicts():  # [REQ:FL-02]
    tot = MP.plan_and_simulate(_mk(), vehicles=2)[4]
    assert "haul_path_conflicts" in tot and isinstance(tot["haul_path_conflicts"], int)
    assert tot["haul_path_conflicts"] >= 0


def test_single_vehicle_has_no_haul_path_conflicts_key():
    tot = MP.plan_and_simulate(_mk())[4]
    assert "haul_path_conflicts" not in tot              # single-vehicle never enters plan_multi -> byte-identical
