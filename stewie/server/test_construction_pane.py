"""FS-03 wiring guard: the Construction work area exists end-to-end -- the Construction tab + #pane_construction
in the served page, the construction_render.js module loaded, and GET /construction returning the REAL
structure-template catalog + acceptance criteria (not a placeholder shell). The pure HTML builders are
unit-tested in construction_render.test.js (node:test); the live signed-in render is exercised by
scripts/cockpit_render.py. This is the fast static+route guard that the wiring is present and the endpoint
serves real data."""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

import stewie.server.server as SRV

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_INDEX = os.path.join(_ROOT, "stewie", "server", "index.html")
_COCKPIT = os.path.join(_ROOT, "stewie", "server", "web", "assets", "cockpit.js")


def _read(p: str) -> str:
    with open(p) as f:
        return f.read()


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.delenv("STEWIE_API_KEY", raising=False)
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")            # loopback in-process -> require_auth = dev-open (director)
    return TestClient(SRV.app)


def test_construction_tab_and_pane_in_served_page():
    html = _read(_INDEX)
    assert 'data-view="construction"' in html, "no Construction tab in the work-area tab bar"
    assert 'id="pane_construction"' in html, "no #pane_construction container"
    assert 'id="vtab-construction"' in html and 'data-minrole="operator"' in html, \
        "Construction tab is not operator-gated (data-minrole)"
    # the pure renderer module is loaded BEFORE cockpit.js (it sets window.STEWIE_CONSTRUCTION_RENDER)
    i_mod = html.find("/assets/construction_render.js")
    i_cockpit = html.find("/assets/cockpit.js")
    assert i_mod != -1, "construction_render.js is not loaded by index.html"
    assert i_mod < i_cockpit, "construction_render.js must load before cockpit.js"


def test_cockpit_wires_the_construction_view():
    js = _read(_COCKPIT)
    assert 'construction: "pane_construction"' in js, "VIEW_PANE has no construction -> pane mapping"
    assert "function loadConstruction" in js, "no loadConstruction() renderer"
    assert "constructionCatalogHTML" in js and "constructionAcceptanceHTML" in js, \
        "loadConstruction does not call the renderers"
    assert "LAST_VALIDATION" in js, "the Construction pane does not read the last plan's validation"


def test_construction_endpoint_serves_the_real_catalog_and_acceptance(client):
    r = client.get("/construction")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] is True
    # REAL catalog: the count matches leap.structures.STRUCTURES and the named templates are present.
    from leap import structures as S
    assert j["count"] == len(S.STRUCTURES), "catalog count does not match leap.structures.STRUCTURES"
    ids = {t["id"] for t in j["templates"]}
    assert {"landing_pad", "blast_berm", "borrow_pit"} <= ids, "expected structure templates missing"
    # a balanced structure decomposes to real cut AND fill primitives (not a placeholder shell):
    berm = next(t for t in j["templates"] if t["id"] == "blast_berm")
    assert berm["n_cut"] >= 1 and berm["n_fill"] >= 1 and berm["balanced"] is True
    kinds = {o["kind"] for o in berm["orders"]}
    assert "cut" in kinds and "fill" in kinds and all(o["footprint_m2"] > 0 for o in berm["orders"])
    # REAL acceptance criteria from validate_plan, with the real default tolerances:
    check_ids = {c["id"] for c in j["acceptance"]["checks"]}
    assert {"as_built_flatness", "repose_stability", "bearing_capacity"} <= check_ids
    flat = next(c for c in j["acceptance"]["checks"] if c["id"] == "as_built_flatness")
    assert flat["tol_m"] > 0, "flatness tolerance not read from validate_plan"
    assert "validation" in j["live_acceptance_source"], "live-acceptance source not declared"


def test_construction_endpoint_is_operator_gated(monkeypatch):
    # no key configured and NOT dev-open -> the privileged route is locked (fail-closed).
    monkeypatch.delenv("STEWIE_API_KEY", raising=False)
    monkeypatch.delenv("STEWIE_DEV_OPEN", raising=False)
    locked = TestClient(SRV.app)
    r = locked.get("/construction")
    assert r.status_code in (401, 403, 503), f"construction route is not auth-gated (got {r.status_code})"
