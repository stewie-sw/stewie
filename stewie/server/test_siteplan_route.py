"""POST /siteplan/analyze: the validate-and-advise site-plan route. A set of REAL placed structures is
posted; the route returns the base-wide mass economy, source<->sink routing, inter-structure clearances,
build order, and advisories (leap.siteplan). Auth-gated (operational read, not director): no key -> 401.
An unknown structure name -> 400. Real store + the FastAPI app via a TestClient; nothing synthetic.

Run: <venv>/bin/python -m pytest stewie/server/test_siteplan_route.py -q
"""
import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_API_KEY", "test-key")
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    from stewie.server import operators as OPS
    importlib.reload(OPS)
    import stewie.server.server as srv
    importlib.reload(srv)
    yield TestClient(srv.app), "test-key"
    monkeypatch.undo()
    importlib.reload(srv)


def test_analyze_requires_auth(client):
    c, _key = client
    r = c.post("/siteplan/analyze", json={"placements": [{"name": "borrow_pit", "x": 0, "y": 0}]})
    assert r.status_code == 401, r.text


def test_analyze_returns_base_wide_report(client):
    c, key = client
    # a cut-only borrow pit (pure source) beside a self-balancing crater fill -> positive net surplus
    payload = {"placements": [
        {"name": "borrow_pit", "x": -30, "y": 0},
        {"name": "crater_fill", "x": 20, "y": 0},
    ]}
    r = c.post("/siteplan/analyze", headers={"X-API-Key": key}, json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["total_cut_mass_kg"] > 0.0
    assert body["net_mass_kg"] > 0.0                       # the standalone borrow pit is surplus
    assert isinstance(body["build_order"], list) and body["build_order"]
    assert any("surplus" in a.lower() or "route" in a.lower() for a in body["advisories"])


def test_analyze_flags_overlap(client):
    c, key = client
    payload = {"placements": [
        {"name": "landing_pad", "x": 0, "y": 0},
        {"name": "solar_pad", "x": 0, "y": 0},
    ], "min_gap_m": 2.0}
    r = c.post("/siteplan/analyze", headers={"X-API-Key": key}, json=payload)
    assert r.status_code == 200, r.text
    assert any(c2["overlap"] for c2 in r.json()["clearances"])


def test_analyze_unknown_structure_400(client):
    c, key = client
    r = c.post("/siteplan/analyze", headers={"X-API-Key": key},
               json={"placements": [{"name": "not_a_structure", "x": 0, "y": 0}]})
    assert r.status_code == 400, r.text
    assert r.json()["ok"] is False
