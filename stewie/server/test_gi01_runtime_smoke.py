"""[REQ:GI-01] Production GIS runtime gate -- the transport-level slice.

GI-01's full acceptance is a desktop+mobile GPU browser smoke against the DEPLOYED origin
(app.stewie.space). That leg stays gated (live deploy reachable from the test host + a GPU Cesium
render + a real sign-in). The closeable slice verified here: the SAME check functions the origin
smoke (scripts/gi01_origin_smoke.py) runs against a live origin pass against the local app --
the index shell wires the self-hosted Cesium bundle after its config, the globe container, the
Contents-tree layer switcher, the terrain-exaggeration control and the sign-in form;
cesium-config.js parses (CESIUM_BASE_URL -> /cesium/); bodies.json carries the Moon/Mars/Earth
globe products with real g + Bekker moduli; the GIS layer routes render from the real DEM; and the
3D-Tiles route answers from the backend. A negative control proves the checks are non-vacuous, and
the production edge contract that serves /cesium/ under the CSP is pinned (deploy/nginx.conf +
deploy/Dockerfile.frontend). NOT asserted here (honest gate): the live-origin fetch itself, the
in-browser GPU render, mobile viewports, and a real sign-in.
"""
import importlib
import importlib.util
import os
import re

import pytest
from fastapi.testclient import TestClient

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_HERE))
_SMOKE = os.path.join(_REPO, "scripts", "gi01_origin_smoke.py")


def _smoke():
    spec = importlib.util.spec_from_file_location("gi01_origin_smoke", _SMOKE)
    assert spec and spec.loader, f"cannot load {_SMOKE}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def client():
    import stewie.server.server as srv
    importlib.reload(srv)
    return TestClient(srv.app)


def _app_fetch(mod, client, prefix=""):
    """Adapt the in-process TestClient to the smoke script's Fetch signature."""
    def fetch(path):
        r = client.get(prefix + path)
        return mod.Resp(r.status_code, {k.lower(): v for k, v in r.headers.items()}, r.content)
    return fetch


def test_gi01_app_checks_pass_against_local_app(client):
    """[REQ:GI-01] every APP-level origin-smoke check passes against the real local app (index shell
    + cesium-config + Moon/Mars/Earth bodies + layer legend/globe products/PNG + tiles route)."""
    mod = _smoke()
    failures = mod.run_checks(mod.APP_CHECKS, _app_fetch(mod, client))
    assert failures == [], "GI-01 app checks failed: " + "; ".join(failures)


def test_gi01_app_checks_cover_the_acceptance_legs():
    """The check list itself covers the row's acceptance legs (guards against gutting a check)."""
    mod = _smoke()
    names = {n for n, _fn in mod.APP_CHECKS}
    assert {"index_shell", "cesium_config", "bodies_globe_products", "layers_legend",
            "globe_products", "globe_layer_png", "tiles_route"} <= names
    edge = {n for n, _fn in mod.EDGE_CHECKS}
    assert {"csp_header", "cesium_bundle", "cesium_widgets_css"} <= edge


def test_gi01_app_checks_fail_on_a_broken_origin(client):
    """Negative control (non-vacuity): pointed at the app's real 404 surface (a bogus path root on
    the SAME server -- no fabricated responses), every APP check must fail."""
    mod = _smoke()
    fetch = _app_fetch(mod, client, prefix="/gi01-no-such-root")
    failures = mod.run_checks(mod.APP_CHECKS, fetch)
    failed = {f.split(":", 1)[0] for f in failures}
    assert failed == {n for n, _fn in mod.APP_CHECKS}, \
        f"checks that PASSED on a broken origin (vacuous): {({n for n, _ in mod.APP_CHECKS}) - failed}"


def test_gi01_edge_contract_pins_cesium_and_csp():
    """The production transport contract the origin smoke's EDGE checks exercise live: nginx serves
    /cesium/ statically under a CSP whose script-src is same-origin without 'unsafe-inline', and the
    frontend image vendors the pinned Cesium build into that path."""
    conf = open(os.path.join(_REPO, "deploy", "nginx.conf")).read()
    m = re.search(r'Content-Security-Policy\s+"([^"]+)"', conf)
    assert m, "deploy/nginx.conf must send a Content-Security-Policy header"
    script_src = re.search(r"script-src ([^;]*)", m.group(1))
    assert script_src and "'self'" in script_src.group(1)
    assert "'unsafe-inline'" not in script_src.group(1), "script-src must not allow 'unsafe-inline'"
    assert re.search(r"location /cesium/", conf), "nginx must serve the /cesium/ bundle statically"
    docker = open(os.path.join(_REPO, "deploy", "Dockerfile.frontend")).read()
    assert "cesium-1.119.0.tgz" in docker, "the frontend image must vendor the pinned Cesium build"
    assert "/usr/share/nginx/html/cesium" in docker, "Cesium must land at the nginx /cesium/ root"
