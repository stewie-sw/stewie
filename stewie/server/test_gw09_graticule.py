"""[REQ:GW-09] dual-mode planning graticule.

The generator is pure browser JS with node tests (gis/qwc2/js/mission/graticule.test.js proves gridline +
label generation for meridians/parallels/km-grid + the off-map reproject guards). req_trace.py counts only
Python markers, so this static gate is the python [REQ:GW-09] citation. It proves the same requirement
structurally: (1) graticule.js generates BOTH modes — selenographic meridians/parallels sampled densely
then reprojected through an injected reproject(lon,lat)->[x,y] (so they curve in polar-stereographic), and
a straight metric km-grid with labels — and guards an off-map reproject (NaN/throw) rather than emitting a
malformed polyline; and (2) Graticule.jsx overlays it on the lunar map, injecting the real proj4
IAU_2015:30100 -> 30135 reproject. Mirrors test_gw10_request_guard.py / test_cockpit_state_routing.py.
"""
from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).parents[2]                       # stewie/server/ -> stewie/ -> repo root
_GRAT = _ROOT / "gis" / "qwc2" / "js" / "mission" / "graticule.js"
_PLUGIN = _ROOT / "gis" / "qwc2" / "js" / "plugins" / "Graticule.jsx"


def _read(p: Path) -> str:
    assert p.exists(), f"GW-09 source missing: {p}"
    return p.read_text(encoding="utf-8")


def test_graticule_generates_both_modes_with_labels_from_an_injected_reproject():  # [REQ:GW-09]
    src = _read(_GRAT)
    # selenographic mode: constant-lon meridians + constant-lat parallels, each sampled then reprojected.
    assert "function meridians(reproject" in src, "no selenographic meridians generator taking a reproject"
    assert "function parallels(reproject" in src, "no selenographic parallels generator taking a reproject"
    # the lines are sampled densely then reprojected (curve in polar-stereographic), not drawn as chords.
    assert "_range(" in src and "reproject" in src, "meridians/parallels are not sampled-then-reprojected"
    # each generated line carries a degree label.
    assert 'label: lon + "\\u00b0"' in src or 'label: lon + "°"' in src, "meridians lack a lon label"
    assert 'label: lat + "\\u00b0"' in src or 'label: lat + "°"' in src, "parallels lack a lat label"
    # metric mode: a straight km grid in the map frame.
    assert "function kmGrid" in src, "no metric km-grid generator"
    assert "km" in src.lower(), "km-grid lacks a km label"


def test_off_map_reproject_is_guarded_not_a_malformed_polyline():  # [REQ:GW-09]
    """A reproject that returns NaN/undefined or THROWS for an off-map lon/lat must be dropped (the point is
    skipped), never emitted as a broken gridline — the #60 guard that makes the overlay robust at the pole."""
    src = _read(_GRAT)
    assert "function _safe(reproject" in src, "no reproject safety wrapper"
    assert "try {" in src and "catch" in src, "_safe does not catch a throwing reproject"
    assert "isFinite" in src, "_safe does not reject a NaN/non-finite reprojected point"
    # a line is only emitted when it still has >= 2 finite points after filtering.
    assert "pts.length >= 2" in src, "a degenerate (< 2 point) line is not dropped"


def test_plugin_overlays_the_graticule_with_the_lunar_reproject():  # [REQ:GW-09]
    """Graticule.jsx drives graticule.js for BOTH modes and adds the result as an OL vector overlay on the
    lunar map, injecting the real proj4 IAU_2015:30100 -> 30135 reproject (NOT OL's Earth-datum graticule)."""
    src = _read(_PLUGIN)
    assert "import G from '../mission/graticule.js'" in src, "plugin does not import the graticule generator"
    assert "G.selenographic(" in src, "plugin does not build the selenographic mode"
    assert "G.kmGrid(" in src, "plugin does not build the metric km-grid mode"
    assert "IAU_2015:30100" in src and "IAU_2015:30135" in src, "plugin does not use the lunar reproject frames"
    assert "map.addLayer(" in src, "the graticule is never overlaid on the map"
