"""[REQ:LY-04] the four PRD-named "missing layer kinds" -> real-producer-or-explicitly-unavailable.

PRD §7.B LY-04 (extends LY-01): the missing layer kinds (ice-probability, localization-confidence,
sensor-coverage, digital-twin-difference) EACH either register in the LY-01 catalog with a REAL backend
producer + provenance/eligibility, OR are explicitly marked UNAVAILABLE (no fabricated drape). This test
asserts each of the four is typed + registered-with-a-real-producer (that actually renders on the real DEM)
OR explicitly absent -- no kind may be silently missing and none may be a fabricated raster.

Screened status (each confirmed against real code, not fabricated):
  - digital-twin-difference: REAL producer = the LY-07 signed as-built-minus-base drape (render_globe
    "changed_terrain"), the visual producer for the catalog rows map.changed_terrain + evidence.before_after_dem.
  - ice-probability: UNAVAILABLE -- terrain.thermal is catalog-only (no Diviner/thermal ice raster); the real
    ice-relevant proxy is terrain.psr (a distinct cold-trap classification, not a per-cell ice probability).
  - localization-confidence: UNAVAILABLE -- robot.covariance / map.uncertainty are belief/live channels with
    no per-cell producer over the fixed prior DEM (no live SLAM/EKF on the static-prior GIS server).
  - sensor-coverage: UNAVAILABLE -- robot.sensor_frustums is live/sim/replay; the horizon-marched LOS producer
    for terrain.los/terrain.comms is tracked as the still-unbuilt LY-06.
"""
from __future__ import annotations

import importlib
import json
import os

import numpy as np
import pytest
from fastapi.testclient import TestClient

H = {"X-API-Key": "test-key"}

# the four kinds the PRD row names, exactly (hyphenated) -- no more, no fewer.
_PRD_KINDS = {"ice-probability", "localization-confidence", "sensor-coverage", "digital-twin-difference"}

# a conserved cut+fill on the REAL Haworth build frame (the SD-01 path) so the digital-twin-difference
# producer demonstrably renders a NON-transparent change on the real DEM (mirrors test_ly07).
_CUT_FILL = [
    {"kind": "cut", "x": 12.0, "y": 12.0, "action": "dig pad", "footprint_m2": 36.0, "depth_m": 0.5},
    {"kind": "fill", "x": 45.0, "y": 45.0, "action": "build berm", "footprint_m2": 25.0, "depth_m": 0.4},
]


def _catalog_ids() -> set[str]:
    root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    with open(os.path.join(root, "stewie", "server", "layer_catalog.json"), encoding="utf-8") as fh:
        return {row["id"] for row in json.load(fh)["layers"]}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    """A fresh app over a fresh per-test data dir (empty TerrainMemory) -- the test_ly07 fixture shape."""
    monkeypatch.setenv("STEWIE_API_KEY", "test-key")
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")
    from stewie.server import state as S
    monkeypatch.setattr(S, "_TWIN", None)
    monkeypatch.setattr(S, "_WSS", None)
    import stewie.server.server as srv
    importlib.reload(srv)
    yield TestClient(srv.app)
    monkeypatch.undo()
    importlib.reload(srv)


def test_ly04_exactly_the_four_prd_kinds_each_typed():  # [REQ:LY-04]
    """The registry names EXACTLY the four PRD-row kinds, each typed (kind:str + available:bool) -- no kind
    silently missing, none extra."""
    from stewie.server.gis_layers import missing_layer_kinds
    reg = missing_layer_kinds()
    kinds = {e["kind"] for e in reg}
    assert kinds == _PRD_KINDS, f"registry kinds {kinds} != PRD kinds {_PRD_KINDS}"
    for e in reg:
        assert isinstance(e["kind"], str) and isinstance(e["available"], bool)
        assert e["catalog_ids"] and all(isinstance(c, str) for c in e["catalog_ids"])


def test_ly04_available_kinds_bind_a_real_registered_producer():  # [REQ:LY-04]
    """Every AVAILABLE kind names a producer that is (a) an allow-listed globe drape with a legend, and
    (b) whose catalog rows carry real provenance/eligibility from the committed catalog (never fabricated)."""
    from stewie.server.gis_layers import missing_layer_kinds
    from stewie.server.routers.layers import _GLOBE_KINDS, layers_legend
    cat_ids = _catalog_ids()
    legend = layers_legend()
    avail = [e for e in missing_layer_kinds() if e["available"]]
    assert avail, "at least one kind (digital-twin-difference) must bind a real producer"
    for e in avail:
        assert e.get("producer"), f"{e['kind']} available but names no producer"
        assert e["producer"] in _GLOBE_KINDS, f"{e['kind']} producer {e['producer']!r} not an allow-listed drape"
        assert legend.get(e["producer"], {}).get("text"), f"{e['kind']} producer has no legend"
        assert e["catalog_ids"] and set(e["catalog_ids"]) <= cat_ids, "producer's catalog rows must be registered"
        # provenance/eligibility is READ from the real catalog rows, not fabricated
        for cid, prov in e["provenance"].items():
            assert cid in cat_ids
            assert set(prov) == {"source_class", "planning_eligible", "release_execute_eligible"}
            assert isinstance(prov["planning_eligible"], bool) and prov["source_class"]


def test_ly04_unavailable_kinds_are_explicitly_absent_no_fabricated_drape():  # [REQ:LY-04]
    """Every UNAVAILABLE kind is EXPLICITLY absent: available False, a non-empty honest reason, NO producer,
    and NOT an allow-listed drape (no fabricated raster). Its catalog_ids are real catalog rows (typed)."""
    from stewie.server.gis_layers import missing_layer_kinds
    from stewie.server.routers.layers import _GLOBE_KINDS
    cat_ids = _catalog_ids()
    unavail = [e for e in missing_layer_kinds() if not e["available"]]
    assert {e["kind"] for e in unavail} == _PRD_KINDS - {"digital-twin-difference"}
    for e in unavail:
        assert "producer" not in e, f"{e['kind']} is unavailable but claims a producer"
        assert e["kind"] not in _GLOBE_KINDS, f"{e['kind']} unavailable but is an allow-listed drape (fabricated?)"
        assert isinstance(e.get("reason"), str) and len(e["reason"]) > 20, "an honest, specific gap reason"
        assert set(e["catalog_ids"]) <= cat_ids, f"{e['kind']} catalog_ids must be real catalog rows (typed)"
    # ice-probability's honest reason must name the REAL available proxy (terrain.psr) and the missing dataset.
    ice = next(e for e in unavail if e["kind"] == "ice-probability")
    assert "terrain.psr" in ice["catalog_ids"] and "psr" in _GLOBE_KINDS, "PSR is the real ice-relevant proxy"
    assert "Diviner" in ice["reason"] or "thermal" in ice["reason"]


def test_ly04_digital_twin_difference_producer_renders_on_the_real_dem(client):  # [REQ:LY-04]
    """The one AVAILABLE kind's producer is not vacuous: after a conserved cut+fill on the REAL Haworth DEM,
    render_globe('changed_terrain') returns a real geographic RGBA + bbox carrying the twin versions and a
    NON-transparent worked change (the LY-07 drape is genuinely the digital-twin-difference producer)."""
    from stewie.server import gis_layers as GL
    entry = next(e for e in GL.missing_layer_kinds() if e["kind"] == "digital-twin-difference")
    producer = entry["producer"]

    r = client.post("/executive/run", headers=H, json={"orders": _CUT_FILL, "site": "haworth"})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True

    out = GL.render_globe(producer, site="haworth")
    assert out is not None, "the digital-twin-difference producer must render on the real DEM"
    rgba, bbox = out
    assert rgba.ndim == 3 and rgba.shape[2] == 4 and rgba.dtype == np.uint8
    assert {"south", "north", "west", "east"} <= set(bbox)
    assert bbox["as_built_version"] >= 1 and "twin_version" in bbox, "drape carries its twin versions"
    assert int(rgba[..., 3].max()) > 0, "the worked change must render non-transparent (a real diff, not a stub)"


def test_ly04_status_is_served_on_the_layer_catalog_endpoint(monkeypatch):  # [REQ:LY-04]
    """The LY-04 status is REGISTERED in the LY-01 catalog surface: /world/layer-catalog serves the same
    missing_layer_kinds registry (so the four kinds' producer-or-unavailable status is discoverable), and the
    LY-01 count is untouched."""
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")
    from stewie.server.gis_layers import missing_layer_kinds
    from stewie.server.server import app
    c = TestClient(app, base_url="http://127.0.0.1")
    j = c.get("/world/layer-catalog").json()
    assert j["count"] == 68 and len(j["layers"]) == 68, "LY-01 catalog count untouched"
    served = j.get("missing_layer_kinds")
    assert served == missing_layer_kinds(), "the served catalog must carry the LY-04 registry"
    assert {e["kind"] for e in served} == _PRD_KINDS
