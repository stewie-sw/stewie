#!/usr/bin/env python3
"""GI-01 origin smoke -- verify a LIVE STEWIE origin serves the GIS runtime, at the transport level.

Hits the deployed origin (default https://app.stewie.space; any compose stack / dev-server URL works)
and asserts what a browser needs BEFORE the first GPU frame: the index shell wires the self-hosted
Cesium bundle AFTER its config, the globe container, the Contents-tree layer switcher, the
terrain-exaggeration control and the sign-in form; /assets/cesium-config.js parses
(CESIUM_BASE_URL -> /cesium/); /bodies.json carries the Moon/Mars/Earth globe products with real
g + Bekker moduli; the GIS layer routes render (/layers/legend, /layers/globe/{kind}/bbox + .png);
and the 3D-Tiles route answers from the BACKEND (fail-closed auth / absent tileset both count --
an edge 502/HTML error page does not). EDGE checks additionally require the nginx-served /cesium/
bundle + the production CSP header, which only exist on a built frontend image / live origin --
pass --app-only against a bare uvicorn dev server.

Deliberately NOT covered (the gated GI-01 leg): the in-browser GPU Cesium render, mobile viewports,
and a real sign-in -- scripts/web01_csp_smoke.py holds the headless-Chrome CSP leg. The APP checks
below are run in-process against the local app by stewie/server/test_gi01_runtime_smoke.py.

Usage: python scripts/gi01_origin_smoke.py [--origin https://app.stewie.space] [--app-only]
Exits non-zero on any failure.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from typing import Callable, NamedTuple


class Resp(NamedTuple):
    status: int
    headers: dict          # lower-cased header names
    body: bytes


Fetch = Callable[[str], Resp]


def http_fetch(origin: str, timeout: float = 60.0) -> Fetch:
    """A Fetch over real HTTP(S) against `origin` (non-2xx returned, not raised)."""
    base = origin.rstrip("/")

    def fetch(path: str) -> Resp:
        req = urllib.request.Request(base + path, headers={"User-Agent": "stewie-gi01-smoke"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return Resp(r.status, {k.lower(): v for k, v in r.headers.items()}, r.read())
        except urllib.error.HTTPError as e:
            return Resp(e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, e.read())
    return fetch


def _ok(resp: Resp, path: str) -> Resp:
    assert resp.status == 200, f"{path}: HTTP {resp.status}"
    return resp


def _ctype(resp: Resp) -> str:
    return resp.headers.get("content-type", "")


# ---- APP checks: served by the FastAPI backend, so they hold on the origin AND the local app ------

def check_index_shell(fetch: Fetch) -> None:
    """The cockpit shell wires the GIS runtime: self-hosted Cesium loaded AFTER cesium-config.js,
    the #cesium globe container, the Contents-tree layer switcher, the GIS-WA2 terrain-exaggeration
    control, and the sign-in form."""
    r = _ok(fetch("/"), "/")
    assert "text/html" in _ctype(r), f"/: content-type {_ctype(r)!r}"
    html = r.body.decode("utf-8", errors="replace")
    for frag in ('src="/cesium/Cesium.js"', 'src="/assets/cesium-config.js"', 'id="cesium"',
                 'id="contents-tree"', 'id="layer"', 'id="exec3dvex"', 'id="auth-do-login"'):
        assert frag in html, f"index shell missing {frag}"
    assert html.index('src="/assets/cesium-config.js"') < html.index('src="/cesium/Cesium.js"'), \
        "cesium-config.js must load BEFORE Cesium.js (CESIUM_BASE_URL ordering)"


def check_cesium_config(fetch: Fetch) -> None:
    """cesium-config.js serves as JS and parses: CESIUM_BASE_URL points Cesium at the self-hosted
    same-origin /cesium/ path (WEB-01)."""
    r = _ok(fetch("/assets/cesium-config.js"), "/assets/cesium-config.js")
    assert "javascript" in _ctype(r), f"cesium-config.js: content-type {_ctype(r)!r}"
    m = re.search(r'window\.CESIUM_BASE_URL\s*=\s*"([^"]+)"', r.body.decode("utf-8", errors="replace"))
    assert m, "cesium-config.js does not set window.CESIUM_BASE_URL"
    assert m.group(1) == "/cesium/", f"CESIUM_BASE_URL {m.group(1)!r} != '/cesium/'"


def check_bodies_globe_products(fetch: Fetch) -> None:
    """bodies.json carries the Moon/Mars/Earth globe products with the real sourced surface gravity
    and Bekker moduli (the layer switcher's per-body basemap config)."""
    r = _ok(fetch("/bodies.json"), "/bodies.json")
    bodies = json.loads(r.body)
    for name, g in (("moon", 1.62), ("mars", 3.71), ("earth", 9.81)):
        assert name in bodies, f"bodies.json missing {name!r}"
        b = bodies[name]
        assert abs(float(b["g"]) - g) < 0.1, f"{name}: g={b['g']} (expected ~{g})"
        assert "k_phi" in b.get("bekker", {}), f"{name}: no Bekker moduli"


def check_layers_legend(fetch: Fetch) -> None:
    """The layer-switcher legend route answers with the physics-derived layer set."""
    r = _ok(fetch("/layers/legend"), "/layers/legend")
    legend = json.loads(r.body)
    assert legend.get("ok") is True, f"/layers/legend: {legend!r}"
    for kind in ("slope", "hazard", "illumination", "psr", "dem"):
        assert kind in legend, f"legend missing layer {kind!r}"


def check_globe_products(fetch: Fetch) -> None:
    """The globe drape products exist: dem + slope bboxes resolve to a real geographic footprint."""
    for kind in ("dem", "slope"):
        r = _ok(fetch(f"/layers/globe/{kind}/bbox"), f"/layers/globe/{kind}/bbox")
        bb = json.loads(r.body)
        assert bb.get("ok") is True, f"globe {kind} bbox: {bb!r}"
        assert bb["south"] < bb["north"] and bb["west"] < bb["east"], f"degenerate bbox: {bb!r}"
        assert -90.0 <= bb["south"] and bb["north"] <= 90.0, f"bbox off the globe: {bb!r}"


def check_globe_layer_png(fetch: Fetch) -> None:
    """A globe drape actually renders (real reprojected PNG bytes, not an error envelope)."""
    r = _ok(fetch("/layers/globe/slope.png"), "/layers/globe/slope.png")
    assert "image/png" in _ctype(r), f"slope.png: content-type {_ctype(r)!r}"
    assert r.body[:8] == b"\x89PNG\r\n\x1a\n" and len(r.body) > 1000, "not a real PNG render"


def check_tiles_route(fetch: Fetch) -> None:
    """The 3D-Tiles namespace answers from the backend: a served tileset (200), fail-closed auth
    (401/503 mentioning the key/auth posture), or an honest 'no tile' 404 -- never an edge error."""
    r = fetch("/tiles/twin/tileset.json")
    assert r.status in (200, 401, 404, 503), f"/tiles/twin/tileset.json: HTTP {r.status}"
    payload = json.loads(r.body)                     # backend JSON, not an nginx/HTML error page
    if r.status == 404:
        assert str(payload.get("error", "")).startswith("no tile"), f"foreign 404: {payload!r}"
    elif r.status in (401, 503):
        err = str(payload.get("error", ""))
        assert "API key" in err or "auth" in err.lower(), f"foreign {r.status}: {payload!r}"


# ---- EDGE checks: only a built frontend image / live origin serves these (nginx + Dockerfile) -----

def check_csp_header(fetch: Fetch) -> None:
    """The production CSP rides on the page: script-src is same-origin without 'unsafe-inline'."""
    r = _ok(fetch("/"), "/")
    csp = r.headers.get("content-security-policy", "")
    assert csp, "no Content-Security-Policy header at the edge"
    m = re.search(r"script-src ([^;]*)", csp)
    assert m and "'self'" in m.group(1), f"script-src not same-origin: {csp!r}"
    assert "'unsafe-inline'" not in m.group(1), "script-src must not allow 'unsafe-inline' (ARCH-02)"


def check_cesium_bundle(fetch: Fetch) -> None:
    """The self-hosted Cesium bundle serves same-origin (vendored at image build; WEB-01)."""
    r = _ok(fetch("/cesium/Cesium.js"), "/cesium/Cesium.js")
    assert "javascript" in _ctype(r), f"Cesium.js: content-type {_ctype(r)!r}"
    assert len(r.body) > 1_000_000, f"Cesium.js only {len(r.body)} bytes -- not the real bundle"
    assert b"Cesium" in r.body, "bundle does not look like CesiumJS"


def check_cesium_widgets_css(fetch: Fetch) -> None:
    """The Cesium widgets stylesheet (linked from the index shell) serves same-origin."""
    r = _ok(fetch("/cesium/Widgets/widgets.css"), "/cesium/Widgets/widgets.css")
    assert "css" in _ctype(r), f"widgets.css: content-type {_ctype(r)!r}"


APP_CHECKS = [
    ("index_shell", check_index_shell),
    ("cesium_config", check_cesium_config),
    ("bodies_globe_products", check_bodies_globe_products),
    ("layers_legend", check_layers_legend),
    ("globe_products", check_globe_products),
    ("globe_layer_png", check_globe_layer_png),
    ("tiles_route", check_tiles_route),
]

EDGE_CHECKS = [
    ("csp_header", check_csp_header),
    ("cesium_bundle", check_cesium_bundle),
    ("cesium_widgets_css", check_cesium_widgets_css),
]


def run_checks(checks, fetch: Fetch) -> list:
    """Run every check; a transport error is a failure, not a crash. Returns ['name: why', ...]."""
    failures = []
    for name, fn in checks:
        try:
            fn(fetch)
            print(f"  PASS {name}")
        except AssertionError as e:
            print(f"  FAIL {name}: {e}")
            failures.append(f"{name}: {e}")
        except Exception as e:                        # URLError/timeout/bad JSON -> a real smoke failure
            print(f"  FAIL {name}: {type(e).__name__}: {e}")
            failures.append(f"{name}: {type(e).__name__}: {e}")
    return failures


def main() -> int:
    ap = argparse.ArgumentParser(description="GI-01 transport-level GIS runtime smoke against a live origin")
    ap.add_argument("--origin", default="https://app.stewie.space", help="origin to smoke (scheme://host[:port])")
    ap.add_argument("--app-only", action="store_true",
                    help="skip the nginx-edge checks (CSP header + /cesium/ bundle) for a bare dev server")
    ap.add_argument("--timeout", type=float, default=60.0)
    args = ap.parse_args()
    checks = list(APP_CHECKS) + ([] if args.app_only else list(EDGE_CHECKS))
    print(f"GI-01 origin smoke against {args.origin} ({len(checks)} checks)")
    failures = run_checks(checks, http_fetch(args.origin, args.timeout))
    print(f"GI-01 ORIGIN SMOKE {'PASS' if not failures else 'FAIL'} "
          f"({len(checks) - len(failures)}/{len(checks)} passed)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
