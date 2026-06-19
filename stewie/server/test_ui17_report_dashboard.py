"""UI-17: the REPORT pane is a mission dashboard -- totals strip + ROUTE HERO + ACTIVITY GANTT.

CI-safe regression guard (no browser): asserts the SERVED cockpit (index.html + /assets/cockpit.js) carries
the dashboard wiring -- the `#dashboards` row with the `#routehero` canvas (the authored plan view enlarged
from `#plancanvas`) and the `#gantt` canvas, the `drawGantt` renderer (phase lanes + per-bar [t0,t1] +
battery curve), and the dashboard chip strip. The live behavior was Playwright-verified against a desktop-mode
sidecar: after planning a real cut->fill mission, the route hero draws the plan view and `#gantt` goes from
0 to ~27.8k bright pixels (DRIVE/DIG/CHARGE lane bars + the BATT curve over a 0..320 h axis). UI rows are
tracked by the cockpit table's ✅/⬜ + a named test, not the §7 [REQ:] matrix.
"""
from fastapi.testclient import TestClient

from stewie.server.server import app

client = TestClient(app)


def _cockpit_js() -> str:
    r = client.get("/assets/cockpit.js")
    assert r.status_code == 200 and "javascript" in r.headers.get("content-type", "")
    return r.text


def test_report_dashboard_elements_are_in_the_served_page():
    html = client.get("/").text
    for el in ('id="dashboards"', 'id="routehero"', 'id="gantt"'):
        assert el in html, f"UI-17: {el} missing from the served cockpit page"


def test_activity_gantt_renderer_is_wired():
    js = _cockpit_js()
    assert "function drawGantt(" in js and '"gantt"' in js          # the Gantt renderer + its canvas
    # it lays phase lanes with bars at [t0, t1] and a battery curve under them
    assert "p.phase" in js and "p.t0" in js and "p.t1" in js
    assert "batt0_frac" in js and "batt1_frac" in js                # the battery curve


def test_route_hero_draws_the_plan_view():
    js = _cockpit_js()
    # the route hero copies the authored plan canvas into the report, enlarged
    assert '"routehero"' in js and '"plancanvas"' in js and "drawImage" in js
    assert "drawGantt(" in js and "timeline" in js                  # fed from the plan's timeline frames
