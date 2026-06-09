"""Item 5: the bundled deterministic sample missions plan as documented on the real Haworth DEM
(feasible tutorials 1-2; the infeasible tutorial 3 demonstrates failure handling). No synthetic data."""
import glob
import json
import os

import pytest

from lode import mission_planner as MP

_DIR = os.path.join(os.path.dirname(__file__), "sample_missions")
_SAMPLES = sorted(glob.glob(os.path.join(_DIR, "*.json")))


def test_three_samples_present():
    assert len(_SAMPLES) == 3


@pytest.mark.parametrize("path", _SAMPLES, ids=lambda p: os.path.basename(p))
def test_sample_mission_plans_deterministically(path):
    dem = MP.load_haworth_dem(); o = MP.flattest_anchor(dem)
    m = MP.mission_from_dict(json.load(open(path)))
    _, _, _, _, t1 = MP.plan_and_simulate(m, dem=dem, dem_origin=o)
    _, _, _, _, t2 = MP.plan_and_simulate(m, dem=dem, dem_origin=o)
    assert t1["distance_m"] == t2["distance_m"]                 # deterministic
    expect_feasible = "infeasible" not in os.path.basename(path).lower()
    assert t1["feasible"] is expect_feasible
    if expect_feasible:
        assert any(r["reached"] and len(r["waypoints"]) >= 2 for r in t1["routes"])
    else:
        assert t1["blocked_legs"] >= 1 and any(not r["reached"] for r in t1["routes"])


def test_sample_mission_endpoints():
    # item 5: the browser can list + load the bundled sample missions (no path traversal).
    from fastapi.testclient import TestClient

    from stewie.server.server import app
    c = TestClient(app)
    lst = c.get("/sample_missions").json()
    assert lst["ok"] and len(lst["samples"]) == 3
    name = lst["samples"][0]["name"]
    m = c.get("/sample_mission/" + name).json()
    assert "orders" in m and m["body"] == "moon"            # a real loadable mission payload
    assert c.get("/sample_mission/../server").status_code == 404   # allowlisted -> no traversal
    assert c.get("/sample_mission/nope").status_code == 404
