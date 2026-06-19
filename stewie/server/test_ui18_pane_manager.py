"""UI-18: the sidebar pane manager -- user-rearrangeable, resizable, persisted layout (FS-21).

CI-safe regression guard (no browser): asserts the SERVED cockpit.js carries the FS-21 pane-manager wiring
-- `wirePanelLayout` with the `STEWIE_PANEL_LAYOUT` store, the draggable `⠿` pane grips (HTML5 dragstart/
dragend), persistence of the pane order to localStorage, and a reset-to-default. This is a VIEW-only
reorder (panes keep their ids/handlers/role gates as they move). UI-18's remaining slice -- multiple NAMED
saved layouts -- is not claimed here (the row stays 🟡); this locks the shipped rearrange+persist core so a
refactor can't silently drop it. UI rows track via the cockpit table's ✅/🟡/⬜ + a named test.
"""
from fastapi.testclient import TestClient

from stewie.server.server import app

client = TestClient(app)


def _cockpit_js() -> str:
    r = client.get("/assets/cockpit.js")
    assert r.status_code == 200 and "javascript" in r.headers.get("content-type", "")
    return r.text


def test_pane_manager_is_wired():
    js = _cockpit_js()
    assert "wirePanelLayout" in js and "STEWIE_PANEL_LAYOUT" in js   # the layout manager + its store
    assert "pane-grip" in js and 'setAttribute("draggable"' in js    # the draggable reorder handles
    assert '"dragstart"' in js and '"dragend"' in js                 # HTML5 drag-to-reorder


def test_pane_order_persists_and_resets():
    js = _cockpit_js()
    assert "localStorage.setItem(L.KEY" in js                        # the reordered layout persists per operator
    assert "localStorage.getItem(L.KEY" in js                        # ...and is re-applied on load
    # FS-21: a reset-to-default that restores the build order is always available
    assert "reset" in js.lower() and "mergeOrder" in js
