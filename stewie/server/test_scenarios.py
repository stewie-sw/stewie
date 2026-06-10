"""B4.1 + P1.4: the training scenario library executes under the REAL closed loop.

Each authored scenario must (a) load through the mission grammar, (b) run as a SESSION on the real
Haworth DEM with its declared link profile, and (c) exhibit its TEACHING POINT measurably (a battery
emergency recharges; a comm-dropout profile loses legs; the shadowed traverse routes longer than the
crow flies). Scenarios are training assets, not gate evidence.
"""
import json
import os

import pytest

from lode import mission_planner as MP
from stewie.server import session as SES

SCEN = os.path.join(os.path.dirname(__file__), "scenarios")
_DEM = None


def _dem():
    global _DEM
    if _DEM is None:
        dem = MP.load_haworth_dem()
        _DEM = (dem, MP.flattest_anchor(dem))
    return _DEM


def _run(name):
    doc = json.load(open(os.path.join(SCEN, name)))
    profile = doc.pop("profile", "ideal")
    teach = doc.pop("teaching_point")
    mission = MP.mission_from_dict(doc)
    dem, origin = _dem()
    return SES.Session.run(mission, profile=profile, dem=dem, dem_origin=origin), teach


def test_scenario_files_carry_teaching_points():
    names = sorted(os.listdir(SCEN))
    assert len(names) >= 4
    for n in names:
        doc = json.load(open(os.path.join(SCEN, n)))
        assert doc.get("teaching_point"), f"{n} must state its teaching point"
        assert "[ASSUMPTION]" in doc.get("provenance", "") or doc.get("provenance"), \
            f"{n} must carry provenance"


def test_nominal_traverse_completes_cleanly():
    s, _ = _run("nominal_traverse.json")
    assert s.record["completed"] and s.link.stats["dropped"] == 0


def test_battery_emergency_forces_recharges():
    s, _ = _run("battery_emergency.json")
    assert s.record["recharges"] >= 1, "the emergency scenario must actually stress the battery"


def test_comm_dropout_loses_legs_for_the_operator():
    s, _ = _run("comm_dropout.json")
    assert len(s.operator_legs) < len(s.record["legs"]), \
        "the dropout profile must visibly cost the operator telemetry"
    assert s.link.stats["dropped"] >= 1


def test_shadowed_traverse_routes_around():
    s, _ = _run("shadowed_traverse.json")
    assert s.record["completed"]
    # the keep-outs (standing in for unlit/uncharacterized terrain) must have shaped the plan:
    # at least one leg pays more true energy than its flat nominal
    assert any(leg["true_J"] > leg["nominal_J"] for leg in s.record["legs"])


@pytest.mark.parametrize("name", ["nominal_traverse.json", "battery_emergency.json",
                                  "comm_dropout.json", "shadowed_traverse.json"])
def test_every_scenario_serves_operator_and_debrief_views(name):
    s, _ = _run(name)
    op = s.operator_view(); db = s.debrief_view()
    assert op["n_legs_total"] == db["n_legs_total"] > 0
    for leg in op["legs"]:
        assert "true_J" not in leg and "slip" not in leg
