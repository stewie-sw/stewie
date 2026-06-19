"""UI-14: the build queue is an inspectable ATTRIBUTE TABLE + authoring undo.

CI-safe regression guard (no browser): asserts the SERVED cockpit (index.html + /assets/cockpit.js) carries
the queue-table wiring -- the `#qtable` element + add/undo controls, `renderQueue` building a column header
row (kind/action/x/y/footprint/depth) with click-to-sort (`QSORT`), and the `undoAuthoring` history stack.
The live behavior (adding two orders renders two sortable rows with per-row locate/reorder/delete controls,
clicking a header sorts with a ▲/▼ indicator, and Undo pops the last add) was Playwright-verified against a
desktop-mode sidecar. UI rows are tracked by the cockpit table's ✅/⬜ + a named test, not the §7 [REQ:] matrix.
"""
from fastapi.testclient import TestClient

from stewie.server.server import app

client = TestClient(app)


def _cockpit_js() -> str:
    r = client.get("/assets/cockpit.js")
    assert r.status_code == 200 and "javascript" in r.headers.get("content-type", "")
    return r.text


def test_queue_table_elements_are_in_the_served_page():
    html = client.get("/").text
    for el in ('id="qtable"', 'id="qadd"', 'id="qundo"'):
        assert el in html, f"UI-14: {el} missing from the served cockpit page"


def test_queue_renders_as_a_sortable_attribute_table():
    js = _cockpit_js()
    assert "function renderQueue(" in js and '"qtable"' in js
    # the column header set (the attribute table, not a bare list)
    for col in ("kind", "action", "depth", "footprint_m2"):
        assert col in js, f"UI-14: queue column {col!r} missing from renderQueue"
    # click-to-sort: a sort key/dir that re-renders on a header click
    assert "QSORT" in js and "renderQueue()" in js


def test_authoring_undo_is_wired():
    js = _cockpit_js()
    assert "function undoAuthoring(" in js and "HISTORY" in js   # the undo history stack
    assert '"qundo"' in js                                        # the Undo button drives it (+ Ctrl+Z)
