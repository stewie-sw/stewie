"""Task #25 slice 1: the BERM RE-HAZARD rule (Aaron: "everything is precision ops on the moon --
a high berm traversed incorrectly will flip the rover").

The closed loop's leg slopes came from the PRIOR DEM -- terrain BUILT mid-mission was invisible to
later legs. Physical grounding: a fresh loose-regolith berm edge stands at the REPOSE angle (the
bodies registry's measured value, ~35 deg lunar) -- above the 20-deg tested traverse envelope. So
a leg whose path crosses a previously-EXECUTED cut/fill footprint is flagged.
"""
from lode import autonomy as AUT
from lode import mission_planner as MP


def _mission(orders):
    return MP.mission_from_dict({"name": "berm", "body": "moon", "charger": [0, 0],
                                 "orders": orders})


def test_leg_crossing_a_fresh_berm_is_flagged():
    # build a berm at (20, 0) FIRST (precedence), then a goto that drives straight through it
    m = _mission([
        {"action": "borrow", "kind": "cut", "x": 10, "y": 0, "footprint_m2": 36, "depth_m": 0.3},
        {"action": "berm", "kind": "fill", "x": 20, "y": 0, "footprint_m2": 36, "depth_m": 0.3},
        {"action": "far side", "kind": "goto", "x": 40, "y": 0},
    ])
    m = type(m)(**{**m.__dict__, "precedence": [["berm", "far side"]]})
    out = AUT.run_closed_loop(m)
    v = out["hazard_violations"]
    assert any("far side" in x["leg"] for x in v), v       # the through-berm leg flags
    assert all(x["slope_deg"] > 20.0 for x in v)           # repose-edge slope above the envelope


def test_leg_avoiding_the_berm_does_not_flag():
    m = _mission([
        {"action": "borrow", "kind": "cut", "x": 10, "y": 40, "footprint_m2": 36, "depth_m": 0.3},
        {"action": "berm", "kind": "fill", "x": 20, "y": 40, "footprint_m2": 36, "depth_m": 0.3},
        {"action": "clear south", "kind": "goto", "x": 40, "y": -30},
    ])
    m = type(m)(**{**m.__dict__, "precedence": [["berm", "clear south"]]})
    out = AUT.run_closed_loop(m)
    assert not any("clear south" in x["leg"] for x in out["hazard_violations"])
