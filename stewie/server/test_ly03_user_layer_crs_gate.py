"""[REQ:LY-03] user-created/imported layers with an Earth-CRS reject gate.

The gate is pure browser JS with node tests (gis/qwc2/js/mission/userLayers.test.js proves the runtime
behavior: validateLayerCrs rejects an Earth CRS and accepts a lunar IAU frame). req_trace.py counts only
Python markers, so this static gate is the python [REQ:LY-03] citation. It proves the same requirement
structurally: (1) userLayers.validateLayerCrs REJECTS the Earth CRSs LY-03 names (EPSG:4326/3857/CRS84/
WGS84, + 2056/generic-EPSG) with a legible reason and ACCEPTS the lunar frame (IAU_2015:30135/30100), and
(2) MissionUserLayer.jsx runs that gate and BLOCKS (returns) on a failed validation BEFORE the layer
touches the map (map.addLayer) — so an Earth-CRS import can never misplace features on the lunar map or be
promoted planning-eligible. Mirrors test_cockpit_state_routing.py / test_gw10_request_guard.py.
"""
from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).parents[2]                       # stewie/server/ -> stewie/ -> repo root
_LAYERS = _ROOT / "gis" / "qwc2" / "js" / "mission" / "userLayers.js"
_PLUGIN = _ROOT / "gis" / "qwc2" / "js" / "plugins" / "MissionUserLayer.jsx"


def _read(p: Path) -> str:
    assert p.exists(), f"LY-03 source missing: {p}"
    return p.read_text(encoding="utf-8")


def test_validate_layer_crs_rejects_earth_and_accepts_lunar():  # [REQ:LY-03]
    src = _read(_LAYERS)
    assert "function validateLayerCrs" in src, "the CRS validator is gone"
    # split the validator body so the assertions bind to its actual reject/accept branches, not a comment.
    body = src.split("function validateLayerCrs", 1)[1]
    lunar_branch = body.split("isLunar: true", 1)[0]
    earth_branch = body.split("isEarth: true", 1)[0]
    # ACCEPT branch (isLunar: true) keys off the lunar frame ids.
    for tok in ('"IAU"', '"MOON"', '"30135"', '"30100"'):
        # tokens appear as upper.indexOf("IAU") etc.; assert the frame id is what gates the lunar-accept.
        assert tok.strip('"') in lunar_branch, f"lunar-accept branch does not key off {tok}"
    assert "isLunar: true" in body and "ok: true" in body
    # REJECT branch (isEarth: true) keys off the Earth CRSs LY-03 names + a legible reason (ok: false).
    for tok in ("WGS", "4326", "3857", "CRS84", "2056", "EPSG"):
        assert tok in earth_branch, f"Earth-reject branch does not catch {tok}"
    assert "isEarth: true" in body
    # the Earth branch returns ok:false (a legible rejection), in the same object literal as isEarth:true.
    earth_at = body.find("isEarth: true")
    earth_obj = body[body.rfind("return {", 0, earth_at):earth_at]
    assert "ok: false" in earth_obj, "the Earth-CRS branch must reject (ok:false)"
    assert "IAU_2015" in body, "the reject reason must point the user at the lunar frame"


def test_plugin_blocks_an_invalid_crs_before_the_layer_touches_the_map():  # [REQ:LY-03]
    """MissionUserLayer.jsx must run parseUserLayer + validateLayerCrs and RETURN on a failure BEFORE
    map.addLayer — the 'rejected before it touches the map' clause. Assert the guard exists and precedes
    the map insertion in source order (an Earth-CRS import cannot reach the OL vector layer)."""
    src = _read(_PLUGIN)
    assert "import UL from '../mission/userLayers'" in src, "plugin does not import the CRS validator"
    assert "UL.parseUserLayer(" in src and "UL.validateLayerCrs(" in src, "plugin does not run the gate"
    validate_pos = src.find("UL.validateLayerCrs(")
    addlayer_pos = src.find("map.addLayer(")
    assert validate_pos >= 0 and addlayer_pos >= 0, "expected both the CRS gate and the map insertion"
    assert validate_pos < addlayer_pos, "the CRS gate must run BEFORE map.addLayer"
    # the failure branch returns (blocks) rather than falling through to the map insertion.
    guard = src[validate_pos:addlayer_pos]
    assert "if (!v.ok)" in guard and "return" in guard, "an invalid CRS is not blocked before the map add"
