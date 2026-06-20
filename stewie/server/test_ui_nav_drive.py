"""FS-05 X: the Navigation pane's end-to-end DRIVE PREVIEW -- the product-path surface of the connected
nav spine (route_leg -> plan_local -> track_plan -> recovery via POST /nav/run).

CI-safe regression guard (no browser): asserts the SERVED cockpit (index.html + /assets/cockpit.js) carries
the drive-preview wiring -- the `#navdriveplot` canvas + `#navdrive` control in the Navigation pane, the
`navDriveRun` handler that POSTs to `/nav/run`, and the `navDrawDrive` renderer that draws the planned route
vs the executed trajectory + start/goal + recovery markers. The live behavior was Playwright-verified against
a desktop-mode sidecar (the route+drive overlay renders bright pixels on the real Haworth DEM). UI rows track
via the cockpit's named-element + named-test convention, not the §7 [REQ:] matrix.
"""
from fastapi.testclient import TestClient

from stewie.server.server import app

client = TestClient(app)


def _cockpit_js() -> str:
    r = client.get("/assets/cockpit.js")
    assert r.status_code == 200 and "javascript" in r.headers.get("content-type", "")
    return r.text


def test_drive_preview_elements_are_in_the_served_page():
    html = client.get("/").text
    for el in ('id="navdriveplot"', 'id="navdrive"', 'id="navdsx"', 'id="navdgx"'):
        assert el in html, f"FS-05 drive preview: {el} missing from the served cockpit page"
    # the cache-buster moved with the cockpit.js change (deploy cache trap)
    assert "cockpit.js?v=38674a6da369" in html


def test_drive_preview_handler_calls_nav_run():
    js = _cockpit_js()
    assert "function navDriveRun(" in js and '"/nav/run"' in js          # the handler hits the end-to-end route
    assert "$(\"navdrive\").onclick = navDriveRun" in js                 # the Run-drive button is wired


def test_drive_renderer_draws_route_vs_executed_and_recovery():
    js = _cockpit_js()
    assert "function navDrawDrive(" in js and '"navdriveplot"' in js      # the renderer + its canvas
    assert "res.waypoints" in js and "res.trajectory" in js              # planned route vs executed path
    assert "res.recovery_events" in js and "e.xy" in js                  # recovery backups marked on the path
