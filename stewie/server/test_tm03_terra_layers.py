"""[REQ:TM-03] the terramechanics spine generates derived LY-01 catalog layers: each physics/traffic/terrain
layer names the TM-02 spine terms it is computed FROM + the producing backend. The anti-fabrication guarantees:
every derived layer id is a REAL LY-01 catalog layer, every source term is a REAL TM-02 spine term, and every
computed source term binds a real solver callable (TERRA_SOLVERS) -- so a slip-risk / traversability / energy
layer is provably built from the terramechanics, not invented. Real endpoint + real catalog + real solver."""
import json
import os

from fastapi.testclient import TestClient

from stewie.server.server import app
from stewie.specs.terramechanics_spine import TERRA_SOLVERS, TERRA_SPINE

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _catalog_ids() -> set[str]:
    with open(os.path.join(_ROOT, "stewie", "server", "layer_catalog.json"), encoding="utf-8") as fh:
        return {ly["id"] for ly in json.load(fh)["layers"]}


def test_tm03_derived_layers_map_to_real_terms_and_catalog(monkeypatch):  # [REQ:TM-03]
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")
    c = TestClient(app, base_url="http://127.0.0.1")
    j = c.get("/world/terramechanics-layers").json()
    rows = j["derived_layers"]
    assert rows and j["backend"] == "tier2_numpy"
    catalog = _catalog_ids()
    spine_ids = {t["id"] for t in TERRA_SPINE}
    for r in rows:
        assert r["layer"] in catalog, f"derived layer {r['layer']} is not a real LY-01 catalog layer"
        assert r["from_terms"] and all(t in spine_ids for t in r["from_terms"]), r["layer"]
        assert r["backend"] == "tier2_numpy"

    by = {r["layer"]: r for r in rows}
    # the load-bearing derived layers come from real computed solver terms (not inputs alone)
    assert "sinkage" in by["physics.sinkage"]["from_terms"]
    assert "slip" in by["physics.slip_risk"]["from_terms"]
    assert "drive_energy" in by["physics.energy_cost"]["from_terms"]
    assert set(by["traffic.traversability"]["from_terms"]) >= {"slip", "traction"}


def test_tm03_computed_terms_are_real_solver_outputs():  # [REQ:TM-03]
    from stewie.specs.terramechanics_spine import terra_derived_layers
    for r in terra_derived_layers():
        for t in r["computed_terms"]:
            assert t in TERRA_SOLVERS and callable(TERRA_SOLVERS[t]), f"{r['layer']} term {t} not a real solver"
        # a physics/traffic derived layer must have at least one COMPUTED (solver) source term, not just inputs
        if r["layer"].startswith(("physics.", "traffic.")):
            assert r["computed_terms"], f"{r['layer']} has no computed terramechanics term"
