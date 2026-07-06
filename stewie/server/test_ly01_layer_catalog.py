"""[REQ:LY-01] the GIS layer catalog registry: the ~65 named layers from the PRD2 catalog table (the single
source of truth) with type/source-class/eligibility. The committed layer_catalog.json stays IN SYNC with the
design-doc table (regen-when-drift), the /world/layer-catalog endpoint serves it, and the eligibility rules hold
(display-only + truth/runtime-evidence layers are NOT planning-eligible; a release-eligible layer carries a
provenance/freshness condition). Config sourced from the design doc, not synthetic data."""
import json
import os

from fastapi.testclient import TestClient

import scripts.gen_layer_catalog as G
from stewie.server.server import app

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def test_ly01_catalog_json_is_in_sync_with_the_prd2_table():  # [REQ:LY-01]
    live = G.build()
    with open(os.path.join(_ROOT, "stewie", "server", "layer_catalog.json"), encoding="utf-8") as fh:
        committed = json.load(fh)
    assert committed["count"] == live["count"] == 66   # 65 + traffic.compaction (TW-11)
    assert committed["layers"] == live["layers"], "layer_catalog.json is stale -- run scripts/gen_layer_catalog.py"


def test_ly01_endpoint_serves_the_catalog_with_eligibility_rules(monkeypatch):  # [REQ:LY-01]
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")
    c = TestClient(app, base_url="http://127.0.0.1")
    j = c.get("/world/layer-catalog").json()
    assert j["count"] == 66 and len(j["layers"]) == 66   # 65 + traffic.compaction (TW-11)
    by = {ly["id"]: ly for ly in j["layers"]}
    # display-only + truth/runtime-evidence layers must NOT be planning-eligible (truth can't drive autonomy)
    assert by["base.imagery"]["planning_eligible"] is False
    assert by["base.hillshade"]["planning_eligible"] is False
    assert by["runtime.gazebo_truth"]["planning_eligible"] is False
    # a release-eligible authoritative layer carries a conditional provenance/freshness release note
    dem = by["base.dem"]
    assert dem["planning_eligible"] is True and dem["release_execute_eligible"] is True
    assert "provenanced" in dem["release_execute_note"] or "fresh" in dem["release_execute_note"]
