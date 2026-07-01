"""FS-03: front-end information architecture -- the cockpit's work areas (Plan, Fleet,
Navigation, Perception, Construction, Models, Security/Operators, Reports) are first-class
routable views, each carries an explicit EPISTEMIC provenance label from the fixed vocabulary
{truth, belief, forecast, live} (one reusable component, web/assets/provenance_label.js), and
the mobile breakpoint applies at phone widths (390px falls inside the 860px phone block).

Served-cockpit test: the HTML is fetched from the REAL FastAPI app (dev-open loopback, the
test_dev_open_index.py pattern), and the pane data sources behind the labels (/fleet,
/construction, /models) are asserted live -- the labels annotate real served channels, they are
not decoration over dead panes. The LIVE kind is stream-bound (set by startRcStream when the
SSE EventSource actually opens, cleared by stopRcStream), never claimed statically.

The interactive drag/zoom render at a real 390px viewport is exercised by the Playwright
harnesses (scripts/cockpit_render.py / cockpit_interactive_check.py); this is the fast served
static guard, per the house pattern in test_panel_layout_chrome.py.  [REQ:FS-03]
"""
from __future__ import annotations

import os
import re

from fastapi.testclient import TestClient

_HERE = os.path.dirname(os.path.abspath(__file__))
_COCKPIT = os.path.join(_HERE, "web", "assets", "cockpit.js")
_MODULE = os.path.join(_HERE, "web", "assets", "provenance_label.js")

EPISTEMIC_KINDS = {"truth", "belief", "forecast", "live"}

#: work area -> (the served-HTML anchor its pane starts at, the anchor the pane ends before).
#: Navigation + Perception are the Validate sub-views (navview / renderpanel panes); Security/
#: Operators is the director Admin surface (operator accounts, pane-admin).
WORK_AREA_SLICES = {
    "plan": ('id="ctx-plan"', 'id="ctx-nav"'),
    "fleet": ('id="pane_fleet"', 'id="pane_construction"'),
    "navigation": ('id="navview"', 'id="execview"'),
    "perception": ('id="renderpanel"', 'id="navview"'),
    "construction": ('id="pane_construction"', 'id="pane_models"'),
    "models": ('id="pane_models"', 'id="pane_trainer"'),
    "security_operators": ('id="pane-admin"', 'id="authmodal"'),
    "reports": ('id="pane-report"', 'id="pane_rehearse"'),
}


def _client(monkeypatch, tmp_path) -> TestClient:
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("STEWIE_API_KEY", raising=False)
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")
    import stewie.server.server as SRV
    return TestClient(SRV.app)


def _served_html(monkeypatch, tmp_path) -> str:
    r = _client(monkeypatch, tmp_path).get("/")
    assert r.status_code == 200
    return r.text


def _read(p: str) -> str:
    with open(p) as f:
        return f.read()


def _slice(html: str, area: str) -> str:
    start_anchor, end_anchor = WORK_AREA_SLICES[area]
    i = html.find(start_anchor)
    assert i != -1, f"{area}: served cockpit has no {start_anchor}"
    j = html.find(end_anchor, i)
    assert j != -1, f"{area}: no closing anchor {end_anchor} after {start_anchor}"
    return html[i:j]


def test_work_areas_are_first_class_views(monkeypatch, tmp_path):
    """[REQ:FS-03] every named work area is routable: a .vtab/.profitem data-view (setView keys
    on data-view), with Navigation + Perception first-class sub-views of the Validate spine slot
    (data-sub buttons + their own VIEW_PANE entries, so setView('nav'/'perception') is a real view
    switch, not a scroll)."""
    html = _served_html(monkeypatch, tmp_path)
    for view in ("plan", "fleet", "construction", "models", "report"):
        assert re.search(r'class="vtab[^"]*"[^>]*data-view="%s"' % view, html) or \
            re.search(r'data-view="%s"[^>]*class="vtab' % view, html), \
            f"no first-class work-area tab for data-view={view!r}"
    # Security/Operators: the role-gated Admin surface routes through the same setView machinery
    assert re.search(r'class="profitem"[^>]*data-view="admin"', html), \
        "no routable Security/Operators (admin) menu item"
    # Navigation + Perception: the Validate spine tab + its sub-tab strip
    assert 'data-view="validate"' in html, "no Validate spine tab"
    assert 'data-sub="nav"' in html and 'data-sub="perception"' in html, \
        "Validate sub-tab strip is missing the Navigation/Perception routes"
    js = _read(_COCKPIT)
    m = re.search(r"const VIEW_PANE = \{.*?\};", js, re.S)
    assert m, "cockpit.js lost the VIEW_PANE view->pane registry"
    for view, pane in (("nav", "navview"), ("perception", "renderpanel"),
                       ("fleet", "pane_fleet"), ("construction", "pane_construction"),
                       ("models", "pane_models"), ("report", "pane-report"),
                       ("admin", "pane-admin")):
        assert f'{view}: "{pane}"' in m.group(0), \
            f"VIEW_PANE does not route {view!r} to its own pane (not first-class)"


def test_each_work_area_carries_an_epistemic_label(monkeypatch, tmp_path):
    """[REQ:FS-03] every work-area pane carries at least one data-epistemic placeholder whose
    kind is in the fixed vocabulary, rendered by the ONE reusable component."""
    html = _served_html(monkeypatch, tmp_path)
    for area in WORK_AREA_SLICES:
        kinds = re.findall(r'data-epistemic="([a-z]+)"', _slice(html, area))
        assert kinds, f"work area {area!r} carries no epistemic provenance label"
        bad = [k for k in kinds if k not in EPISTEMIC_KINDS]
        assert not bad, f"work area {area!r} uses kinds outside the vocabulary: {bad}"
    # ONE reusable component: the module loads before cockpit.js and cockpit applies it
    i_mod = html.find("/assets/provenance_label.js")
    i_cockpit = html.find("/assets/cockpit.js")
    assert i_mod != -1, "provenance_label.js is not loaded by the served cockpit"
    assert i_mod < i_cockpit, "provenance_label.js must load before cockpit.js"
    mod = _read(_MODULE)
    for kind in EPISTEMIC_KINDS:
        assert f'"{kind}"' in mod or f"{kind}:" in mod, f"the component does not define {kind!r}"
    assert "applyProvenanceLabels" in _read(_COCKPIT), \
        "cockpit.js never applies the provenance-label component"


def test_labelled_panes_are_fed_by_live_backend_data(monkeypatch, tmp_path):
    """[REQ:FS-03] the labels annotate real served data channels: the registry endpoints behind
    the truth-labelled Fleet/Construction/Models panes answer on the same served app."""
    c = _client(monkeypatch, tmp_path)
    for ep, key in (("/fleet", "vehicles"), ("/construction", "templates"), ("/models", "profiles")):
        r = c.get(ep)
        assert r.status_code == 200, f"{ep} is not served (labelled pane would be decoration)"
        body = r.json()
        assert body.get(key), f"{ep} returned no {key} (empty registry behind the label)"


def test_live_kind_is_stream_bound_not_static(monkeypatch, tmp_path):
    """[REQ:FS-03] the LIVE label is tied to the real SSE telemetry stream: the served page ships
    it idle, startRcStream() turns it on only once the EventSource exists, stopRcStream() clears
    it. A static page must never claim a flowing live feed."""
    html = _served_html(monkeypatch, tmp_path)
    m = re.search(r'<[^>]*data-epistemic="live"[^>]*>', html)
    assert m, "no live-kind provenance placeholder in the served cockpit"
    assert 'data-live="idle"' in m.group(0), "the live label must ship IDLE (nothing streams yet)"
    js = _read(_COCKPIT)
    start = js.split("async function startRcStream")[1].split("\nfunction ")[0]
    stop = js.split("function stopRcStream")[1].split("\nasync function ")[0]
    assert "setLiveState" in start, "startRcStream never activates the live provenance label"
    i_es = start.find("rcStream = es")
    i_on = start.find("setLiveState")
    assert i_es != -1 and i_on > i_es, \
        "the live label must activate only AFTER the EventSource is actually open"
    assert "setLiveState" in stop, "stopRcStream never returns the live label to idle"


def _media_blocks(html: str) -> list[tuple[int, str]]:
    """Every `@media (max-width: Npx) {...}` block body, brace-walked (CSS nests one level)."""
    out = []
    for m in re.finditer(r"@media \(max-width: (\d+)px\) \{", html):
        depth, i = 1, m.end()
        while depth and i < len(html):
            if html[i] == "{":
                depth += 1
            elif html[i] == "}":
                depth -= 1
            i += 1
        out.append((int(m.group(1)), html[m.end():i]))
    return out


def test_mobile_breakpoint_applies_at_phone_widths(monkeypatch, tmp_path):
    """[REQ:FS-03] a phone layout block covers 390px-wide devices and keeps the epistemic
    chips visible + legible there (unlike the dev .sysb badges, which mobile hides)."""
    html = _served_html(monkeypatch, tmp_path)
    phone = [b for w, b in _media_blocks(html) if w >= 390]
    assert phone, "no media block covering a 390px phone in the served cockpit"
    block = next((b for b in phone if "min-height: 44px" in b), None)
    assert block, "no phone block carries the 44px touch-target floor"
    assert ".epis" in block, "no phone-width legibility rule for the epistemic chips"
    epis_rules = re.findall(r"\.epis[^{]*\{[^}]*\}", block)
    assert epis_rules and all("display: none" not in r for r in epis_rules), \
        "the epistemic chips must stay visible at phone widths"
