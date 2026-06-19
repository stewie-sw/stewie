"""UI-6: the cockpit ships the severity-typed, timestamped ALERT RAIL.

(UI rows are tracked by the cockpit-capability table's ✅/⬜ + a named test, not the §7 [REQ:] matrix.)

A CI-safe regression guard (no browser): it asserts the SERVED cockpit (index.html + the /assets/cockpit.js
the page loads) carries the alert-rail wiring -- the rail + bell + badge elements, the `alertMsg` chokepoint
+ `renderAlerts`, the bell toggle handler, and the REAL alert call sites (plan hazard flags, layer failures,
error-shaped status). The live visual behavior (bell opens the rail, three severities render, the badge
counts the non-info alerts) was Playwright-verified against a desktop-mode sidecar; this locks the wiring so
a refactor that drops the rail fails the gate. PRD UI-6 is shipped on the strength of both.
"""
from fastapi.testclient import TestClient

from stewie.server.server import app

client = TestClient(app)


def _cockpit_js() -> str:
    r = client.get("/assets/cockpit.js")
    assert r.status_code == 200 and "javascript" in r.headers.get("content-type", "")
    return r.text


def test_alert_rail_elements_are_in_the_served_page():
    html = client.get("/").text
    for el in ('id="alertrail"', 'id="alertbtn"', 'id="alertbadge"'):
        assert el in html, f"UI-6: {el} missing from the served cockpit page"


def test_alert_rail_chokepoint_and_toggle_are_wired():
    js = _cockpit_js()
    assert "function alertMsg(" in js and "function renderAlerts(" in js   # the one chokepoint + renderer
    assert '"alertbtn"' in js and ".onclick" in js                         # the bell toggles the rail
    # the badge counts NON-info alerts (severity-typed), the rail is capped
    assert 'a.sev !== "info"' in js and "ALERTS.length > 80" in js


def test_alert_rail_is_fed_real_alert_sources():
    js = _cockpit_js()
    # not a dead widget: real warn/error/info sources land on the rail
    assert 'alertMsg("warn"' in js          # plan hazard flags (repose-edge legs)
    assert 'alertMsg("error"' in js         # a layer/render failure
    assert 'alertMsg("info"' in js          # plan-solved summary
