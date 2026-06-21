"""FS-21: the customizable workspace. The sidebar panes (the collapsible groups collapseSidebar()
builds from the h3s) can be dragged to reorder, the order persists per operator in localStorage, and
a reset-to-default is always available in Settings. Layout is a VIEW preference only.

The pure order math is unit-tested in panel_layout.test.js (node:test); the live drag is exercised by
scripts/cockpit_render.py in a real browser. This is the fast static guard that the wiring exists.
"""
from __future__ import annotations

import os

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_INDEX = os.path.join(_ROOT, "stewie", "server", "index.html")
_COCKPIT = os.path.join(_ROOT, "stewie", "server", "web", "assets", "cockpit.js")
_LAYOUT = os.path.join(_ROOT, "stewie", "server", "web", "assets", "panel_layout.js")


def _read(p: str) -> str:
    with open(p) as f:
        return f.read()


def test_panel_layout_module_loads_before_cockpit():
    html = _read(_INDEX)
    i_layout = html.find("/assets/panel_layout.js")
    i_cockpit = html.find("/assets/cockpit.js")
    assert i_layout != -1, "panel_layout.js is not loaded by index.html"
    assert i_layout < i_cockpit, "panel_layout.js must load before cockpit.js (it provides STEWIE_PANEL_LAYOUT)"


def test_drag_handle_and_reset_control_present():
    html = _read(_INDEX)
    assert ".pane-grip" in html, "no drag-handle styling for the reorderable panes"
    assert 'id="set-resetlayout"' in html, "no reset-to-default control in Settings"


def test_reorder_glue_wired_and_persists():  # [REQ:FS-21]
    js = _read(_COCKPIT)
    assert "function wirePanelLayout" in js, "no wirePanelLayout() drag glue"
    glue = js.split("function wirePanelLayout")[1].split("\nconst SETTINGS")[0]
    assert "STEWIE_PANEL_LAYOUT" in glue, "the glue does not use the pure layout module"
    assert "pane-grip" in glue and 'setAttribute("draggable"' in glue, "no draggable grip is created"
    assert "L.KEY" in glue and "localStorage.setItem" in glue, "the reordered layout is not persisted"
    assert "window.resetPanelLayout" in glue, "reset-to-default is not exposed"
    # the reset button is wired to the reset function
    assert '$("set-resetlayout").onclick' in js, "the Settings reset button is not wired"


def test_layout_is_view_only_not_an_auth_or_contract_change():
    # FS-21 is a VIEW preference: the drag glue must not touch auth, roles, AG gating, or contracts.
    js = _read(_COCKPIT)
    glue = js.split("function wirePanelLayout")[1].split("\nconst SETTINGS")[0]
    for forbidden in ("AUTH", "role", "apiHeaders", "require", "/rc", "fetch("):
        assert forbidden not in glue, f"the layout glue unexpectedly references {forbidden!r} (must be view-only)"
