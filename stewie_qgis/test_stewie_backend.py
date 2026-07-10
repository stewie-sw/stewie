"""[REQ:QG-01] Pure-logic CI gate for the STEWIE QGIS Processing backend layer — runs WITHOUT a QGIS runtime
(no qgis.* import in this test path; it is in the CI testpaths per pyproject.toml). The fixtures are real
curls of the live backend (artemis.stewie.space/api, 2026-07-08), not synthetic. It proves the QGIS-free
stewie_backend fetch+parse (url builders + terramechanics/point normalization + honest errors) AND — by
reading the provider source, still qgis-free — that the STEWIE Processing provider registers the two named
algorithms (StewieTerramechanics/StewieSamplePoint). The algorithms themselves are exercised on the host via
a headless pyQGIS smoke, not here.
"""
from pathlib import Path

import pytest

from stewie_qgis import stewie_backend as B

SPINE = {   # GET /world/terramechanics-layers?site=haworth (verbatim shape)
    "ok": True, "backend": "tier2_numpy", "derived_layers": [
        {"layer": "terrain.slope", "from_terms": ["slope"], "backend": "tier2_numpy", "computed_terms": []},
        {"layer": "physics.bearing", "from_terms": ["contact_pressure"], "backend": "tier2_numpy", "computed_terms": ["contact_pressure"]},
    ],
}
POINT = {   # GET /world/point?site=haworth&lon=...&lat=... (verbatim shape)
    "ok": True, "site": "haworth", "cell": {"row": 1395, "col": 835, "cell_m": 5.0},
    "attributes": [
        {"id": "base.dem", "label": "Elevation", "unit": "m", "value": 1101.0847, "available": True},
        {"id": "terrain.slope", "label": "Slope", "unit": "deg", "value": 3.8963, "available": True},
        {"id": "hazard.slope_nogo", "label": "Slope no-go", "unit": "", "value": False, "available": True},
    ],
}


def test_url_builders_encode_the_site():
    assert B.spine_url("http://x:8000", "shackleton_rim") == "http://x:8000/world/terramechanics-layers?site=shackleton_rim"
    assert B.point_url("http://x:8000/", "haworth", -26.6384, -86.1152) == "http://x:8000/world/point?site=haworth&lon=-26.6384&lat=-86.1152"


def test_terramechanics_rows_normalizes_the_spine():
    rows = B.terramechanics_rows(SPINE)
    assert len(rows) == 2
    bearing = next(r for r in rows if r["layer"] == "physics.bearing")
    assert bearing["group"] == "physics"
    assert bearing["terms"] == "contact_pressure"
    assert bearing["computes"] == "contact_pressure"
    assert bearing["backend"] == "tier2_numpy"
    slope = next(r for r in rows if r["layer"] == "terrain.slope")
    assert slope["computes"] == ""   # a raw term computes nothing


def test_terramechanics_rows_errors_honestly():
    with pytest.raises(ValueError):
        B.terramechanics_rows({"ok": False, "error": "no dem for site"})


def test_point_attributes_carries_values_and_units():
    pa = B.point_attributes(POINT)
    assert pa["site"] == "haworth"
    assert pa["cell"]["cell_m"] == 5.0
    assert len(pa["attributes"]) == 3
    elev = pa["attributes"][0]
    assert elev["id"] == "base.dem" and elev["value"] == 1101.0847 and elev["unit"] == "m"
    nogo = pa["attributes"][2]
    assert nogo["value"] is False   # a boolean attribute passes through unchanged


def test_point_attributes_errors_honestly():
    with pytest.raises(ValueError):
        B.point_attributes({"ok": False, "error": "422 out of bounds"})


def test_provider_registers_the_two_named_processing_algorithms():  # [REQ:QG-01]
    """The STEWIE Processing provider registers StewieTerramechanics + StewieSamplePoint as QGIS Processing
    algorithms (runnable from the GUI / qgis_process CLI / batch / Models). qgis.* is not importable in CI, so
    assert the registration from the provider SOURCE (loadAlgorithms adds both) — no qgis runtime needed."""
    root = Path(__file__).parent
    provider = (root / "stewie_provider.py").read_text(encoding="utf-8")
    algos = (root / "stewie_algorithms.py").read_text(encoding="utf-8")
    # the provider's loadAlgorithms registers BOTH algorithms.
    assert "def loadAlgorithms" in provider
    assert "self.addAlgorithm(StewieTerramechanicsAlgorithm())" in provider
    assert "self.addAlgorithm(StewieSamplePointAlgorithm())" in provider
    # each is a real QgsProcessingAlgorithm (the GUI/CLI/batch/Models Processing contract).
    assert "class StewieTerramechanicsAlgorithm(QgsProcessingAlgorithm)" in algos
    assert "class StewieSamplePointAlgorithm(QgsProcessingAlgorithm)" in algos
