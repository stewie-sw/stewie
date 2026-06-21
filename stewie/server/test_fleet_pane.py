"""FS-03 wiring guard: the Fleet work area exists end-to-end -- the Fleet tab + #pane_fleet in the
served page, the fleet_render.js module loaded, and GET /fleet returning the REAL vehicle registry
(not a placeholder shell). The pure HTML builders are unit-tested in fleet_render.test.js (node:test);
the live signed-in render is exercised by scripts/cockpit_render.py. This is the fast static+route guard
that the wiring is present and the endpoint serves real data."""
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


def test_fleet_tab_and_pane_in_served_page():
    html = _read(_INDEX)
    assert 'data-view="fleet"' in html, "no Fleet tab in the work-area tab bar"
    assert 'id="pane_fleet"' in html, "no #pane_fleet container"
    assert 'data-minrole="operator"' in html, "Fleet tab is not operator-gated (data-minrole)"
    # the pure renderer module is loaded BEFORE cockpit.js (it sets window.STEWIE_FLEET_RENDER)
    i_mod = html.find("/assets/fleet_render.js")
    i_cockpit = html.find("/assets/cockpit.js")
    assert i_mod != -1, "fleet_render.js is not loaded by index.html"
    assert i_mod < i_cockpit, "fleet_render.js must load before cockpit.js (provides STEWIE_FLEET_RENDER)"


def test_cockpit_wires_the_fleet_view():
    js = _read(_COCKPIT)
    assert 'fleet: "pane_fleet"' in js, "VIEW_PANE has no fleet -> pane mapping"
    assert "function loadFleet" in js, "no loadFleet() renderer"
    assert "fleetRosterHTML" in js and "fleetPlanHTML" in js, "loadFleet does not call the renderers"
    assert "data-minrole" in js, "gateChrome does not role-gate the minrole tabs"


def test_fleet_endpoint_serves_the_real_vehicle_registry(client):
    r = client.get("/fleet")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] is True
    # REAL registry: ipex is the flight excavator; the count matches specs/vehicles.py.
    from stewie.specs import vehicles as VH
    assert j["count"] == len(VH.VEHICLES), "fleet count does not match the registry"
    ids = {v["id"] for v in j["vehicles"]}
    assert "ipex" in ids, "the IPEx flight excavator is missing from the roster"
    assert j["default_vehicle"] == VH.DEFAULT_VEHICLE
    ipex = next(v for v in j["vehicles"] if v["id"] == "ipex")
    # real spec values (not a placeholder): IPEx carries a real dry mass, drum, drive power, capabilities.
    assert ipex["dry_mass_kg"] > 0 and ipex["drum_capacity_kg"] > 0 and ipex["drive_power_w"] > 0
    assert "excavate" in ipex["capabilities"] and ipex["can_dig"] is True
    assert ipex["onboard_power"] and ipex["onboard_power"][0]["capacity_j"] > 0
    assert "vehicles_detail" in j["live_allocation_source"], "live-allocation source not declared"


def test_fleet_endpoint_is_operator_gated(monkeypatch):
    # no key configured and NOT dev-open -> the privileged route is locked (fail-closed 503).
    monkeypatch.delenv("STEWIE_API_KEY", raising=False)
    monkeypatch.delenv("STEWIE_DEV_OPEN", raising=False)
    locked = TestClient(SRV.app)
    r = locked.get("/fleet")
    assert r.status_code in (401, 403, 503), f"fleet route is not auth-gated (got {r.status_code})"
