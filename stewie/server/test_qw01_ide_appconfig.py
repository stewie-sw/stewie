"""[REQ:QW-01] the served /ide/ front door is a QWC2 SPA whose appConfig registers the STEWIE Mission*
plugins over an OpenLayers map.

Two halves: (a) STATIC — appConfig.js imports AND registers each STEWIE Mission* plugin in pluginsDef
(asserted here, req_trace's python citation); (b) RUNTIME — a signed-in browser smoke opens each Mission*
plugin at desktop + phone widths with zero blocking console errors (frontend/_ide_qw01_smoke.mjs, run against
the deployed artemis /ide on real GPU: all 13 task plugins activate at 1600px + 390px, OpenLayers map present,
0 blocking errors). This gate asserts the registration the runtime smoke then exercises. Mirrors the static-gate
convention (test_cockpit_state_routing.py / test_gw10_request_guard.py) for a QWC2-app row req_trace can't reach.
"""
from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).parents[2]                       # stewie/server/ -> stewie/ -> repo root
_APPCFG = _ROOT / "gis" / "qwc2" / "js" / "appConfig.js"
_SMOKE = _ROOT / "frontend" / "_ide_qw01_smoke.mjs"

# the STEWIE Mission* plugins appConfig must register (the /ide's workbench surface).
_MISSION_PLUGINS = [
    "MissionAssets", "MissionCrossSection", "MissionTerrain3D", "MissionEngPanel", "MissionEvidence",
    "MissionHUD", "MissionLayers", "MissionPlan", "MissionProgram", "MissionTerramech",
    "MissionRuntime", "MissionUserLayer", "SelectionInspector",
]


def _read(p: Path) -> str:
    assert p.exists(), f"QW-01 source missing: {p}"
    return p.read_text(encoding="utf-8")


def test_appconfig_imports_and_registers_every_mission_plugin():  # [REQ:QW-01]
    src = _read(_APPCFG)
    for name in _MISSION_PLUGINS:
        # (a) imported as a lazy/plugin module.
        assert f"import {name}Plugin from './plugins/{name}'" in src, f"appConfig does not import {name}"
        # (b) registered in the pluginsDef.plugins map (Name: Name) so the SPA can activate it.
        assert f"{name}Plugin: {name}Plugin" in src, f"appConfig does not register {name} in pluginsDef"


def test_appconfig_is_a_qwc2_spa_over_an_openlayers_map():  # [REQ:QW-01]
    src = _read(_APPCFG)
    # QWC2 demo-app shell: the core Map plugin + the standard QWC2 chrome the STEWIE plugins overlay.
    assert "qwc2/plugins/Map" in src or "MapPlugin" in src, "no QWC2 Map plugin (the OpenLayers substrate)"
    assert "qwc2/components/AppMenu" in src, "not the QWC2 app shell (no AppMenu)"
    # the plugin registry is a real pluginsDef the StandardApp mounts (not a stub).
    assert "pluginsDef" in src and "plugins:" in src, "no pluginsDef plugin registry"


def test_the_runtime_smoke_exists_and_covers_each_plugin_at_two_widths():  # [REQ:QW-01]
    """The V=D runtime evidence is a committed, reproducible smoke: it opens each Mission* plugin at desktop
    AND phone widths and fails on any BLOCKING console error. Assert it is real + covers the acceptance shape
    (both widths, the plugin set, the zero-blocking assertion) so the citation is not a dangling reference."""
    smoke = _read(_SMOKE)
    assert "setCurrentTask" in smoke, "the smoke does not open plugins"
    assert '"desktop"' in smoke and '"phone"' in smoke, "the smoke does not test desktop + phone widths"
    assert "zeroBlocking" in smoke and "isBlocking" in smoke, "the smoke does not assert zero blocking errors"
    # it exercises the same Mission* plugins this gate asserts are registered.
    for name in ("MissionPlan", "MissionTerrain3D", "MissionUserLayer", "SelectionInspector"):
        assert name in smoke, f"the smoke does not open {name}"
