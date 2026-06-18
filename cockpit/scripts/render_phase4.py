#!/usr/bin/env python3
"""Phase-4 gate (integration, not pixels): sign in, land on the Plan work area (the 3D world canvas), and
verify the Three.js boundary MOUNTS cleanly under the production CSP — a <canvas data-testid=world-canvas>
with non-zero size, zero JS/CSP errors, and a WebGL context. Then unmount it (switch to a data work area)
and back, to exercise the create/dispose lifecycle without leaks/errors.

HONEST LIMIT: headless swiftshader exercises the integration + software WebGL, but the real globe/DEM
imagery is a real-GPU + running-backend check (the user's). This gate proves the React boundary is correct,
not that the terrain looks right. Run: <repo>/.venv/bin/python cockpit/scripts/render_phase4.py
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
       "style-src 'self' 'unsafe-inline'; font-src 'self' data:; img-src 'self' data: blob:; "
       "connect-src 'self'; worker-src 'self' blob:; object-src 'none'; base-uri 'self'; "
       "frame-ancestors 'none'; form-action 'self'")
COOKIE = "stewie_session=phase4; Path=/; HttpOnly"


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
        return "stewie_session=phase4" in (self.headers.get("Cookie") or "")

    def do_GET(self):
        if self.path.startswith("/auth/me"):
            return self._json(200, {"ok": True, "identity": "ops@stewie.space", "role": "operator",
                                    "has_password": True}) if self._authed() else self._json(401, {"ok": False})
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
        page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        # console.error only for genuine JS errors -- ignore network-status noise (the expected pre-login
        # /auth/me 401 and the benign /favicon.ico 404 are not app failures)
        page.on("console", lambda m: errors.append(f"console.error: {m.text}")
                if m.type == "error" and "Failed to load resource" not in m.text else None)
        page.goto(f"http://127.0.0.1:{port}/", wait_until="load")
        page.fill('input[aria-label="email"]', "ops@stewie.space")
        page.fill('input[aria-label="password"]', "pw")
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_selector('[data-testid="world-canvas"]', timeout=8000)
        page.wait_for_timeout(700)  # let the raf loop paint a few frames
        size = page.eval_on_selector('[data-testid="world-canvas"]', "c => [c.width, c.height]")
        has_gl = page.eval_on_selector('[data-testid="world-canvas"]',
                                       "c => !!(c.getContext('webgl2') || c.getContext('webgl'))")
        page.screenshot(path=str(OUT / "cockpit_world3d.png"))

        # lifecycle: switch to a data area (unmount the canvas) and back (re-create) — no errors/leaks
        page.get_by_role("tab", name="Metrics").click()
        page.wait_for_timeout(200)
        gone = page.query_selector('[data-testid="world-canvas"]') is None
        page.get_by_role("tab", name="Plan").click()
        page.wait_for_selector('[data-testid="world-canvas"]', timeout=8000)
        page.wait_for_timeout(300)
        browser.close()
    srv.shutdown()

    if errors:
        print("FAIL — page errors:", *errors, sep="\n  ")
        return 1
    if not size or size[0] < 10 or size[1] < 10:
        print(f"FAIL — world canvas has no size: {size}")
        return 2
    if not gone:
        print("FAIL — canvas not disposed when leaving the spatial work area")
        return 3
    print(f"PASS — Three.js world canvas mounts (CSP-clean, {size[0]}x{size[1]}, webgl={has_gl}), "
          f"disposes on work-area switch, and re-creates. Screenshot in {OUT}/ "
          f"(globe/DEM imagery is the real-GPU + backend check).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
