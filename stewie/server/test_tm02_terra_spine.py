"""[REQ:TM-02] the terramechanics spine (/physics/terramechanics-spine): the terms the conserved tier2_numpy
solver computes, each inspectable (unit/symbol/description/calibration) and BOUND to the real solver callable
that produces it. The anti-synthetic guarantee: every computed term's `source` resolves to the live
stewie.physics function, so the spine cannot list a term the solver doesn't actually compute."""
import importlib

from fastapi.testclient import TestClient

from stewie.server.server import app


def test_tm02_spine_lists_the_real_terms(monkeypatch):  # [REQ:TM-02]
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")
    c = TestClient(app, base_url="http://127.0.0.1")
    j = c.get("/physics/terramechanics-spine").json()
    by = {t["id"]: t for t in j["terms"]}
    for term in ("slope", "roughness", "regolith_density", "contact_pressure",
                 "sinkage", "slip", "traction", "compaction_resistance", "drive_energy"):
        assert term in by, f"spine is missing {term}"
        assert by[term]["unit"] and by[term]["backend"] == "tier2_numpy" and by[term]["calibration"]
    # the load-bearing computed terms name the real solver functions (not a fabricated catalog)
    assert by["sinkage"]["source"] == "stewie.physics.sinkage.bekker_sinkage"
    assert by["slip"]["source"] == "stewie.physics.slip.slip_for_demand"
    assert by["traction"]["source"] == "stewie.physics.slip.traction_budget"
    # honest calibration: slope is measured off the DEM; the Bekker-derived terms are calibrated
    assert by["slope"]["calibration"] == "measured"
    assert by["sinkage"]["calibration"] == "calibrated"


def test_tm02_drive_power_term_is_honestly_labeled_as_power():  # [REQ:TM-02] task #53 Finding 3
    """drive_energy's source is bekker_drive_power_w -- a steady-state POWER (Watts), not an energy
    total. Its unit must stay W and its description must not claim to be an energy-per-traverse
    quantity (the mislabel the physics council flagged)."""
    from stewie.specs.terramechanics_spine import TERRA_SPINE

    by_source = {t["source"]: t for t in TERRA_SPINE}
    term = by_source["stewie.physics.slip.bekker_drive_power_w"]
    assert term["unit"] == "W"
    desc = term["description"].lower()
    assert "energy per traverse" not in desc
    assert "energy" not in desc


def test_tm02_computed_terms_defer_to_the_real_solver():  # [REQ:TM-02]
    from stewie.specs.terramechanics_spine import TERRA_SOLVERS
    assert TERRA_SOLVERS, "no computed terms bound"
    for tid, fn in TERRA_SOLVERS.items():
        assert callable(fn), tid
        # the bound callable IS the real physics function (import-resolvable), never a stub
        resolved = getattr(importlib.import_module(fn.__module__), fn.__name__)
        assert resolved is fn, tid
        assert fn.__module__.startswith("stewie.physics."), tid
