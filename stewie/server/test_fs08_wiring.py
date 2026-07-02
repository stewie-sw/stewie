"""FS-08 backend-to-frontend wiring gate: every autonomy capability the cockpit surfaces must ship the
full chain -- a TYPED API (its shape on /contracts/schema), a COCKPIT STATE BINDING (an adapters.js
normalizer over that shape), LOADING/ERROR/EMPTY states per data pane, and a REAL-BROWSER regression that
runs at DESKTOP *and* MOBILE widths. The individual pieces are tested elsewhere (FS-02 schema, FS-15/FS-18
adapter parity, the a11y smokes); this test is the one place that asserts they form a single coherent chain
so the requirement is non-vacuous -- delete or drift any leg and this reds.

adapters.js / index.html / the two eval scripts are JS/HTML/harness code (not importable here), so -- exactly
like test_adapter_contract_parity -- they are read as TEXT and asserted against the live typed source of
truth (the /contracts/schema payload) and against each other. The heavy Playwright harnesses themselves
(scripts/ui_eval.py desktop, scripts/ux_a11y_smoke.py mobile) need Chrome + a running server + a vendored
Cesium build, so they run on demand, not in CI; here we assert they EXIST and pin the two viewports so a
viewport regression (losing the desktop or the mobile leg) breaks this test.

Run: <venv>/bin/python -m pytest stewie/server/test_fs08_wiring.py -q
"""
from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from stewie import contracts as C

_HERE = Path(__file__).parent
_ADAPTERS_JS = _HERE / "web" / "assets" / "adapters.js"
_INDEX_HTML = _HERE / "index.html"
_UI_EVAL = _HERE.parent.parent / "scripts" / "ui_eval.py"
_UX_A11Y = _HERE.parent.parent / "scripts" / "ux_a11y_smoke.py"

# the onboard-autonomy spine contracts the cockpit binds against (must match routers/schema.py::_SPINE).
_SPINE = ("EphemerisObservation", "VehicleState", "FleetState", "ResourceReservation", "WorldState",
          "BeliefState", "PlanResult", "ExecutionEvent", "NavFactor", "ModelArtifact", "ConstructionSkill")


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_API_KEY", "test-key")
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    import stewie.server.server as srv
    importlib.reload(srv)
    yield TestClient(srv.app)
    monkeypatch.undo()
    importlib.reload(srv)


def test_fs08_full_wiring_chain(client):  # [REQ:FS-08]
    """The FS-08 chain end to end: typed API -> cockpit state binding -> loading/error/empty per pane ->
    a desktop AND a mobile real-browser regression. Every leg asserted against the real committed source so
    the requirement cannot go vacuous."""

    # -- LEG 1: TYPED API. Every spine capability exposes its typed shape via /contracts/schema (the fixture
    # FS-08 requires the cockpit + browser tests to build against). Live route, real JSON Schema per contract.
    r = client.get("/contracts/schema")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["spine_version"] == C.SPINE_VERSION      # the typed API is pinned to the real contract version
    schemas = body["schemas"]
    for name in _SPINE:
        assert name in schemas, f"{name} missing from /contracts/schema (typed-API leg)"
        assert schemas[name]["type"] == "object", f"{name} schema is not a JSON Schema object"
        # a typed shape is non-empty: it declares properties the cockpit binds to
        assert schemas[name].get("properties"), f"{name} schema exposes no properties"

    # -- LEG 2: COCKPIT STATE BINDING. Every spine contract has a normalizer function in adapters.js that
    # maps the typed payload -> the view model a pane renders (schema <-> binding tie). If a new capability
    # ships a route/schema but no adapter, the cockpit would consume raw backend JSON (the FS-15 violation).
    adapters = _ADAPTERS_JS.read_text()
    binding = {
        "EphemerisObservation": "normalizeEphemeris", "VehicleState": "normalizeVehicle",
        "FleetState": "normalizeFleet", "ResourceReservation": "normalizeFleet",
        "WorldState": "normalizeWorld", "BeliefState": "normalizeBelief",
        "PlanResult": "normalizePlanResult", "ExecutionEvent": "normalizeExecutionEvent",
        "NavFactor": "normalizeNavFactor", "ModelArtifact": "normalizeModelArtifact",
        "ConstructionSkill": "normalizeSkill",
    }
    assert set(binding) == set(_SPINE), "the schema<->binding map drifted from the spine contract set"
    for contract, fn in binding.items():
        assert re.search(rf"\bfunction {re.escape(fn)}\b", adapters), \
            f"{contract} has no {fn}() state-binding normalizer in adapters.js"
        assert re.search(rf"\b{re.escape(fn)}\b", adapters.split("var API")[1]), \
            f"{fn} is defined but not exported from adapters.js (the cockpit could not bind it)"

    # -- LEG 3a: LOADING/ERROR/EMPTY. The single fetch-outcome -> UI-state mapping (toViewState) must resolve
    # ALL FOUR states, so every data pane routes loading/error/empty/ok through one place (not ad-hoc per pane).
    for state in ("loading", "error", "empty", "ok"):
        assert re.search(rf'state:\s*"{state}"', adapters), \
            f"toViewState does not map the {state!r} state (loading/error/empty leg)"

    # -- LEG 3b: each cockpit DATA pane renders an EMPTY state. Assert the real index.html carries an empty
    # placeholder for every data-bearing pane + the report loading placeholder, so a data pane cannot ship
    # with no empty/loading affordance.
    html = _INDEX_HTML.read_text()
    empty_ids = set(re.findall(r'id="([a-z0-9]+empty)"', html))
    required_empty = {
        "rpempty", "panoempty", "pcempty", "navempty", "execempty", "reportempty", "rehearseempty",
        "fleetrosterempty", "fleetplanempty", "constructioncatalogempty", "modelsregistriesempty",
    }
    missing = required_empty - empty_ids
    assert not missing, f"data panes missing an empty-state placeholder in index.html: {sorted(missing)}"
    assert 'id="reportloading"' in html, "the report pane has no loading placeholder"
    # each empty placeholder is a real rendered element (the .empty class the CSS styles), not a bare hook
    assert html.count('class="empty"') >= len(required_empty), \
        "fewer .empty rendered elements than required data panes"

    # -- LEG 4 + 5: a REAL-BROWSER regression at DESKTOP *and* MOBILE widths. The two harnesses must both
    # exist and pin their viewports, so dropping either the desktop or the mobile leg reds this test.
    assert _UI_EVAL.is_file(), "the desktop browser regression harness scripts/ui_eval.py is missing"
    assert _UX_A11Y.is_file(), "the mobile browser regression harness scripts/ux_a11y_smoke.py is missing"
    ui_eval = _UI_EVAL.read_text()
    ux_a11y = _UX_A11Y.read_text()
    # desktop leg: ui_eval drives a real headless browser at 1440x900 and asserts panes render w/o JS errors
    assert 'sync_playwright' in ui_eval, "ui_eval.py is not a real-browser (Playwright) harness"
    assert re.search(r'"width":\s*1440,\s*"height":\s*900', ui_eval), \
        "ui_eval.py does not pin the desktop 1440x900 viewport"
    assert 'pageerror' in ui_eval, "ui_eval.py does not assert on page (JS) errors"
    # mobile leg: ux_a11y sets a real phone viewport (390x844) and checks touch/layout at that width
    assert 'sync_playwright' in ux_a11y, "ux_a11y_smoke.py is not a real-browser (Playwright) harness"
    assert re.search(r'"width":\s*390,\s*"height":\s*844', ux_a11y), \
        "ux_a11y_smoke.py does not exercise the mobile 390x844 viewport"
    assert 'pageerror' in ux_a11y, "ux_a11y_smoke.py does not assert on page (JS) errors"
