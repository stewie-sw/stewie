"""A-06 regression: site/body/time must be carried as real provenance so a non-Haworth plan is not
reported with `haworth_dem`.

The audit found the /plan response hardcoded `terrain_source = "haworth_dem" if dem is not None else
"flat_fallback"` -- so a plan for a different lunar site (or a non-Moon body) that happened to load a
DEM was labeled with Haworth provenance, and a non-Moon body's flat fallback was indistinguishable
from a missing-DEM Moon fallback.

This pins that the reported terrain provenance reflects the ACTUAL site/body the plan used:
 - a Moon plan on the default haworth site reports a haworth-derived source,
 - a non-Moon body (no lunar DEM) is NOT labeled with any haworth/lunar DEM provenance,
 - the response carries the site + body it actually planned on (so the UI can warn on a mismatch).

Run: PYTHONPATH=. <venv>/bin/python -m pytest stewie/server/test_site_provenance.py -q
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from stewie.server import server as SRV


@pytest.fixture()
def client():
    return TestClient(SRV.app)


_ORDERS = [{"action": "cut", "kind": "cut", "x": 40, "y": 30, "footprint_m2": 36, "depth_m": 0.04},
           {"action": "fill", "kind": "fill", "x": 44, "y": 44, "footprint_m2": 14, "depth_m": 0.10}]


def test_moon_haworth_plan_reports_haworth_provenance(client):
    r = client.post("/plan", json={"name": "m", "body": "moon", "site": "haworth",
                                   "charger": [0, 0], "orders": _ORDERS})
    assert r.status_code == 200, r.text
    j = r.json()
    # the terrain source must name the site it used; for haworth that includes 'haworth'
    src = str(j.get("terrain_source", "")).lower()
    assert "haworth" in src, f"haworth plan lost its site provenance: {src!r}"
    # and the body/site context is echoed back (required A-06 context)
    prov = j.get("provenance", {})
    assert j.get("site") == "haworth" or prov.get("site") == "haworth", "no site context in the response (A-06)"
    assert j.get("body") == "moon" or prov.get("body") == "moon", "no body context in the response (A-06)"


def test_non_moon_body_is_not_labeled_with_haworth_dem(client):
    """A Mars plan uses the flat fallback (no lunar DEM). It must NOT be reported as haworth_dem --
    that was the exact A-06 mislabel."""
    r = client.post("/plan", json={"name": "mars-pad", "body": "mars", "charger": [0, 0],
                                   "orders": _ORDERS})
    assert r.status_code == 200, r.text
    j = r.json()
    src = str(j.get("terrain_source", "")).lower()
    assert "haworth" not in src, f"a Mars plan was labeled with Haworth provenance: {src!r}"
    # the body context must say mars (so the report cannot imply lunar terrain)
    prov = j.get("provenance", {})
    assert j.get("body") == "mars" or prov.get("body") == "mars", "Mars plan lost its body context (A-06)"
