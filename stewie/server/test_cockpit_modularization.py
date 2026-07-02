"""FS-24: front-end module organization. The cockpit is split out of one monolith into pure ES modules
loaded BEFORE cockpit.js -- the app-shell remainder -- so the split follows the FS-24 taxonomy (typed API
adapters, route/state store, domain view-models, shared visualization components, work-area/HUD views,
diagnostics). This python gate LOCKS three properties of that split so it cannot silently regress:

  1. index.html has NO inline <script> body (every <script> loads an external src). This is the
     precondition the deployed CSP relies on (nginx `script-src 'self'`, no inline; enforced by
     test_deploy_hardening::test_web01_nginx_csp_keeps_script_self_and_allowlists_tiles [REQ:FS-11]).
  2. each split module loads BEFORE cockpit.js, exports its `window.STEWIE_*` namespace, and carries a
     sibling node `.test.js` (the browser-JS tier CI runs, PO-04).
  3. purity, at the honest tier each module actually occupies:
       - the pure formatters/adapters/state modules touch NO `document.` and do NO network (`fetch(`);
       - `rover_hud` is the one SHARED-VISUALIZATION renderer: it does no network and never reaches for a
         live node by global lookup (`document.getElementById`/`querySelector`), but it DOES build detached
         nodes (`document.createElement`) and write into the rail element the app shell passes it. Its
         `.test.js` node-tests it against a stubbed `document`. Claiming it is DOM-free would be false, so
         the gate holds it to fetch-free + no-global-lookup, not to pure-formatter purity.

The per-module HTML/logic is unit-tested in each `*.test.js`; this is the fast static gate that the split
+ CSP-no-inline invariant hold together. Run:
    PYTHONNOUSERSITE=1 PYTHONPATH=. <venv>/bin/python -m pytest stewie/server/test_cockpit_modularization.py -q
"""
from __future__ import annotations

import os
import re

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_INDEX = os.path.join(_ROOT, "stewie", "server", "index.html")
_ASSETS = os.path.join(_ROOT, "stewie", "server", "web", "assets")

# the FS-24 split modules that must load before the cockpit.js app shell. Pure formatters/adapters/state
# (document- and fetch-free) + the one shared-viz renderer (rover_hud), held to its honest tier below.
_PURE_MODULES = [
    "world_state_html", "regolith_estimate", "scorecard_chips", "terrain_memory_html", "nav_stats_html",
    "adapters", "cockpit_state", "geofmt", "htmlesc", "role_rank", "navplot", "evidence_html",
]
_SHARED_VIZ_MODULES = ["rover_hud"]
_ALL_MODULES = _PURE_MODULES + _SHARED_VIZ_MODULES

_SCRIPT_TAG = re.compile(r"<script\b([^>]*)>(.*?)</script>", re.IGNORECASE | re.DOTALL)
_STEWIE_EXPORT = re.compile(r"\.STEWIE_[A-Za-z0-9_]+\s*=")


def _read(p: str) -> str:
    with open(p, encoding="utf-8") as f:
        return f.read()


def test_index_has_no_inline_script_body():  # [REQ:FS-24]
    html = _read(_INDEX)
    for attrs, body in _SCRIPT_TAG.findall(html):
        if body.strip():
            raise AssertionError(f"inline <script> body present (CSP no-inline violated): <script{attrs}>"
                                 f" ... {body.strip()[:60]!r}")
        assert "src=" in attrs.lower(), f"a <script> tag has neither src nor a body: <script{attrs}>"


def test_every_split_module_loads_before_cockpit_and_has_a_test():  # [REQ:FS-24]
    html = _read(_INDEX)
    i_cockpit = html.find("/assets/cockpit.js")
    assert i_cockpit != -1, "cockpit.js (the app shell) is not loaded by index.html"
    for m in _ALL_MODULES:
        js = os.path.join(_ASSETS, f"{m}.js")
        assert os.path.isfile(js), f"{m}.js is missing (split module not extracted)"
        i_mod = html.find(f"/assets/{m}.js")
        assert i_mod != -1, f"{m}.js is not loaded by index.html"
        assert i_mod < i_cockpit, f"{m}.js must load BEFORE cockpit.js (it is the app shell)"
        assert _STEWIE_EXPORT.search(_read(js)), f"{m}.js does not export a window.STEWIE_* namespace"
        assert os.path.isfile(os.path.join(_ASSETS, f"{m}.test.js")), f"{m}.js has no sibling {m}.test.js"


def test_pure_modules_are_dom_free_and_do_no_network():  # [REQ:FS-24]
    for m in _PURE_MODULES:
        src = _read(os.path.join(_ASSETS, f"{m}.js"))
        assert "document." not in src, f"{m}.js touches the DOM (document.) -- not a pure formatter"
        assert "fetch(" not in src and "XMLHttpRequest" not in src, \
            f"{m}.js does network I/O -- the fetch stays in the cockpit.js app shell"


def test_shared_viz_module_does_no_network_and_no_global_dom_lookup():  # [REQ:FS-24]
    # rover_hud renders into a caller-provided element; it may create detached nodes but must not reach for
    # a live node by global lookup, and must not do network I/O.
    src = _read(os.path.join(_ASSETS, "rover_hud.js"))
    assert "fetch(" not in src and "XMLHttpRequest" not in src, "rover_hud.js does network I/O"
    assert "document.getElementById" not in src and "document.querySelector" not in src, \
        "rover_hud.js reaches for a live node by global lookup -- the app shell must pass elements in"
