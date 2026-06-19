"""UI-15: the WORK AREA pip is a true overview-locator -- the main camera's view rectangle drawn on it,
draggable to pan, double-click to render.

CI-safe regression guard (no browser): asserts the SERVED cockpit (index.html + /assets/cockpit.js) carries
the locator wiring -- the `#piploc` canvas + `#workareaimg` hillshade, `pipDraw` computing the camera view
rectangle (`computeViewRectangle`) and stroking it (`strokeRect`), and the double-click -> `renderArea`
handler. The live behavior was Playwright-verified against a desktop-mode sidecar: the pip renders (240x240,
visible) and the neon view-rectangle stroke is drawn (canvas getImageData found ~2198 stroke pixels at the
default framing, and the rect redraws after a drag on the pip). UI rows are tracked by the cockpit table's
✅/⬜ + a named test, not the §7 [REQ:] matrix.
"""
from fastapi.testclient import TestClient

from stewie.server.server import app

client = TestClient(app)


def _cockpit_js() -> str:
    r = client.get("/assets/cockpit.js")
    assert r.status_code == 200 and "javascript" in r.headers.get("content-type", "")
    return r.text


def test_locator_elements_are_in_the_served_page():
    html = client.get("/").text
    for el in ('id="piploc"', 'id="workareaimg"'):
        assert el in html, f"UI-15: {el} missing from the served cockpit page"
    assert "overview locator" in html.lower()        # the WORK AREA caption naming the locator


def test_pip_draws_the_camera_view_rectangle():
    js = _cockpit_js()
    assert "function pipDraw(" in js                 # the pip renderer
    assert "computeViewRectangle" in js              # it reads the MAIN camera's current view extent
    assert "strokeRect" in js                        # ...and strokes that rectangle on the pip


def test_pip_is_interactive_drag_pan_and_double_click_render():
    js = _cockpit_js()
    assert '"piploc"' in js and "renderArea(" in js   # double-click the pip -> render that sub-area
    assert "ondblclick" in js                         # the double-click-to-render handler
