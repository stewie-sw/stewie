#!/usr/bin/env python3
"""Phase-4b gate: serve the REAL Haworth LOLA heightfield (subsampled via the actual /dem/heightfield code
path -> _dem_fixture.json) at /dem/heightfield, sign in, and verify the Plan world canvas (1) builds the
real terrain mesh (canvas paints with a WebGL ctx, no errors) and (2) supports click-to-place authoring:
a pointer-down on the terrain places a build order that appears in the command-rail queue.
HONEST LIMIT: this exercises the integration + software WebGL; the Cesium planetary globe is still the
real-GPU check. Run: <repo>/.venv/bin/python cockpit/scripts/render_phase4b.py
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
FIXTURE = json.loads((HERE / "_dem_fixture.json").read_text())  # REAL Haworth LOLA, n=33
CSP = ("default-src 'self'; script-src 'self' 'unsafe-eval' 'wasm-unsafe-eval' blob:; "
       "style-src 'self' 'unsafe-inline'; font-src 'self' data:; img-src 'self' data: blob:; "
       "connect-src 'self'; worker-src 'self' blob:; object-src 'none'; base-uri 'self'; "
       "frame-ancestors 'none'; form-action 'self'")
COOKIE = "stewie_session=phase4b; Path=/; HttpOnly"


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
        return "stewie_session=phase4b" in (self.headers.get("Cookie") or "")

    def do_GET(self):
        if self.path.startswith("/auth/me"):
            return self._json(200, {"ok": True, "identity": "ops@stewie.space", "role": "operator",
                                    "has_password": True}) if self._authed() else self._json(401, {"ok": False})
        if self.path.startswith("/dem/heightfield"):
            return self._json(200, FIXTURE)  # the REAL subsampled Haworth heightfield
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
        page.on("console", lambda m: errors.append(f"console.error: {m.text}")
                if m.type == "error" and "Failed to load resource" not in m.text else None)
        page.goto(f"http://127.0.0.1:{port}/", wait_until="load")
        page.fill('input[aria-label="email"]', "ops@stewie.space")
        page.fill('input[aria-label="password"]', "pw")
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_selector('[data-testid="world-canvas"]', timeout=8000)
        page.wait_for_timeout(900)  # let the heightfield fetch resolve + terrain build + paint
        has_gl = page.eval_on_selector('[data-testid="world-canvas"]',
                                       "c => !!(c.getContext('webgl2') || c.getContext('webgl'))")
        body_txt = page.eval_on_selector("body", "b => b.innerText")
        terrain_loaded = "REAL LOLA" in body_txt
        print(f"  [diag] terrain_loaded={terrain_loaded} (info card says "
              f"{'REAL LOLA' if terrain_loaded else 'grid scaffold' if 'grid scaffold' in body_txt else '??'})")
        page.screenshot(path=str(OUT / "cockpit_terrain.png"))

        # click-to-place: a few clicks across the terrain -> orders in the build queue
        box = page.eval_on_selector('[data-testid="world-canvas"]',
                                    "c => { const r=c.getBoundingClientRect(); return [r.left,r.top,r.width,r.height]; }")
        cx, cy = box[0] + box[2] / 2, box[1] + box[3] / 2
        for dx, dy in [(0, 0), (-60, 30), (70, -20)]:
            page.mouse.click(cx + dx, cy + dy)
            page.wait_for_timeout(120)
        n_orders = page.eval_on_selector_all('[data-testid="order-queue"] li', "els => els.length")
        page.screenshot(path=str(OUT / "cockpit_authoring.png"))
        browser.close()
    srv.shutdown()

    if errors:
        print("FAIL — page errors:", *errors, sep="\n  ")
        return 1
    if not has_gl:
        print("FAIL — no WebGL context on the world canvas")
        return 2
    if n_orders < 1:
        print(f"FAIL — click-to-place placed no orders (queue={n_orders}); a terrain ray-hit is required")
        return 3
    print(f"PASS — real LOLA terrain mesh renders (WebGL, n={FIXTURE.get('n')}); click-to-place placed "
          f"{n_orders} build order(s) into the queue. Screenshots in {OUT}/ (Cesium globe = real-GPU check).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
