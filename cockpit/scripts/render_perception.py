#!/usr/bin/env python3
"""Perception gate: sign in, open the Perception work area, and verify it renders the /evidence comparison
(ARGUS vs the cited baselines) -- the modality-precision tiles + the per-approach accuracy panels -- from
a stub serving the REAL /evidence output (_evidence_fixture.json). The live stereo/depth render is the
gated tier. Run: <repo>/.venv/bin/python cockpit/scripts/render_perception.py
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
EVIDENCE = json.loads((HERE / "_evidence_fixture.json").read_text())  # the REAL /evidence output
CSP = ("default-src 'self'; script-src 'self' 'unsafe-eval' 'wasm-unsafe-eval' blob:; "
       "style-src 'self' 'unsafe-inline'; font-src 'self' data:; img-src 'self' data: blob:; "
       "connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'")
COOKIE = "stewie_session=perc; Path=/; HttpOnly"


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
        return "stewie_session=perc" in (self.headers.get("Cookie") or "")

    def do_GET(self):
        if self.path.startswith("/auth/me"):
            return self._json(200, {"ok": True, "identity": "ops@stewie.space", "role": "operator",
                                    "has_password": True}) if self._authed() else self._json(401, {"ok": False})
        if self.path.startswith("/evidence"):
            return self._json(200, EVIDENCE)
        if self.path.startswith("/dem/heightfield"):
            return self._json(404, {"ok": False})
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
        page.wait_for_selector(".ds-modebar", timeout=8000)
        page.get_by_role("tab", name="Perception").click()
        page.wait_for_timeout(500)
        body = page.eval_on_selector("body", "b => b.innerText")
        page.screenshot(path=str(OUT / "cockpit_perception.png"))
        browser.close()
    srv.shutdown()

    if errors:
        print("FAIL — page errors:", *errors, sep="\n  ")
        return 1
    if "ARGUS" not in body or "Modality precision" not in body:
        print(f"FAIL — Perception missing ARGUS / modality precision: {body[:160]!r}")
        return 2
    print("PASS — Perception renders the /evidence comparison (ARGUS + baselines + modality precision). "
          f"Screenshot in {OUT}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
