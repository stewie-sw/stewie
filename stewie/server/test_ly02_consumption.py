"""[REQ:LY-02] the layer-consumption inspector (/world/layer-consumption): for each LY-01 catalog layer, the
consumers it feeds (display/planner/costmap/rehearsal/release/execute/report/export). The invariant that keeps
it honest: consumption is a faithful projection of the LY-01 eligibility -- a layer feeds the planner only if
planning-eligible, and release/execute only if release/execute-eligible. Real endpoint + derived from the real
catalog, no fabricated map."""
import json
import os

from fastapi.testclient import TestClient

from stewie.server.layer_consumption import consumers_for
from stewie.server.server import app

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def test_ly02_every_layer_has_consumers(monkeypatch):  # [REQ:LY-02]
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")
    c = TestClient(app, base_url="http://127.0.0.1")
    j = c.get("/world/layer-consumption").json()
    by = {r["id"]: r["consumers"] for r in j["layers"]}
    assert len(by) == 66 and all(cons for cons in by.values())  # every layer is consumed somewhere (65 + traffic.compaction)

    # a display-only layer (base.imagery: not planning/release-eligible) never feeds planning or command
    assert "display" in by["base.imagery"]
    assert not ({"planner", "costmap", "release", "execute"} & set(by["base.imagery"]))

    # a planning + release-eligible layer (base.dem) feeds the planner + costmap + release + execute
    assert {"planner", "costmap", "release", "execute"} <= set(by["base.dem"])


def test_ly02_consumption_is_consistent_with_eligibility():  # [REQ:LY-02]
    with open(os.path.join(_ROOT, "stewie", "server", "layer_catalog.json"), encoding="utf-8") as fh:
        cat = json.load(fh)
    for ly in cat["layers"]:
        cons = set(consumers_for(ly))
        if "planner" in cons:
            assert ly["planning_eligible"], f"{ly['id']} feeds planner but is not planning-eligible"
        if {"release", "execute"} & cons:
            assert ly["release_execute_eligible"], f"{ly['id']} feeds release/execute but is not eligible"
        if "costmap" in cons:
            assert "planner" in cons, f"{ly['id']} in costmap must also be a planner input"
