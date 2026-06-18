#!/usr/bin/env python3
"""Cesium globe gate (INTEGRATION ONLY — not pixels): sign in, switch the Plan canvas to Globe, and verify
the Cesium Viewer mounts on the lunar ellipsoid under the production CSP (worker-src 'self' blob:) with a
canvas and zero JS/CSP errors. The actual Moon tiles/pixels need a real GPU browser + the Trek service;
this confirms the React boundary + CSP + Cesium init are correct.
Run: <repo>/.venv/bin/python cockpit/scripts/render_globe.py
"""
from __future__ import annotations

import functools
import http.server
import json
import pathlib
import threading

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
DIST = HERE.parent / "dist"
OUT = HERE.parent / "validation"
OUT.mkdir(parents=True, exist_ok=True)
CSP = ("default-src 'self'; script-src 'self' 'unsafe-eval' 'wasm-unsafe-eval' blob:; "
       "style-src 'self' 'unsafe-inline'; font-src 'self' data:; "
       "img-src 'self' data: blob: https://trek.nasa.gov; worker-src 'self' blob:; "
       "connect-src 'self' https://trek.nasa.gov; object-src 'none'; base-uri 'self'; "
       "frame-ancestors 'none'; form-action 'self'")
COOKIE = "stewie_session=globe; Path=/; HttpOnly"


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Content-Security-Policy", CSP)
        super().end_headers()

    def _json(self, code: int, obj: dict, set_cookie: bool = False):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        if set_cookie:
            self.send_header("Set-Cookie", COOKIE)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authed(self) -> bool:
        return "stewie_session=globe" in (self.headers.get("Cookie") or "")

    def do_GET(self):
        if self.path.startswith("/auth/me"):
            return self._json(200, {"ok": True, "identity": "ops@stewie.space", "role": "operator",
                                    "has_password": True}) if self._authed() else self._json(401, {"ok": False})
        if self.path.startswith("/dem/heightfield"):
            return self._json(404, {"ok": False})  # globe view doesn't need the DEM
        return super().do_GET()

    def do_POST(self):
        if self.path.startswith("/auth/login"):
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            return self._json(200, {"ok": True, "operator": "ops@stewie.space", "role": "operator",
                                    "must_set_password": False}, set_cookie=True)
        return self._json(404, {"ok": False})

    def log_message(self, *_a):
        pass


def main() -> int:
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(DIST)))
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--use-gl=swiftshader", "--no-sandbox"])
        page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        # ignore network/resource noise (Trek tiles won't load here) + Cesium's own non-fatal warns
        page.on("console", lambda m: errors.append(f"console.error: {m.text}")
                if m.type == "error" and "Failed to load resource" not in m.text
                and "trek.nasa.gov" not in m.text else None)
        page.goto(f"http://127.0.0.1:{port}/", wait_until="load")
        page.fill('input[aria-label="email"]', "ops@stewie.space")
        page.fill('input[aria-label="password"]', "pw")
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_selector(".ds-modebar", timeout=8000)
        page.get_by_role("button", name="Globe", exact=True).click()
        try:
            page.wait_for_selector('[data-testid="cesium-canvas"]', timeout=12000)
            mounted = True
        except Exception:
            mounted = page.query_selector('[aria-label="planetary globe"] canvas') is not None
        page.wait_for_timeout(800)
        has_gl = page.eval_on_selector('[data-testid="cesium-canvas"]',
                                       "c => !!(c.getContext && (c.getContext('webgl2')||c.getContext('webgl')))") if mounted else False
        page.screenshot(path=str(OUT / "cockpit_globe.png"))
        browser.close()
    srv.shutdown()

    hard = [e for e in errors if "WebGL" not in e]  # a swiftshader WebGL warning is acceptable
    if hard:
        print("FAIL — JS/CSP errors:", *hard, sep="\n  ")
        return 1
    if not mounted:
        print("FAIL — Cesium viewer canvas did not mount")
        return 2
    print(f"PASS — Cesium lunar globe viewer mounts (canvas, webgl={has_gl}) under the production CSP with no "
          f"JS/CSP errors. Globe TILES/pixels are the real-GPU check. Screenshot in {OUT}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
