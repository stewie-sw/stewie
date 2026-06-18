#!/usr/bin/env python3
"""Phase-2 gate: sign in (director), then exercise the data-light areas + FS-20 chrome against stubbed
data routes under the production CSP. Verifies: (1) Admin panel renders the operator roster + the FS-19
event timeline; (2) the Metrics work area renders the event timeline; (3) Settings toggles the theme
(.ds-root gains `light`). Route shapes verbatim from the routers. Exits non-zero on failure.
Run: <repo>/.venv/bin/python cockpit/scripts/render_phase2.py
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
       "connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'")
COOKIE = "stewie_session=phase2; Path=/; HttpOnly"
EVENTS = [{"ts": 1718000000, "actor": "director@stewie.space", "action": "auth.login", "target": "password"},
          {"ts": 1718000100, "actor": "ops@stewie.space", "action": "mission.publish", "target": "haworth-1"}]
OPERATORS = [{"email": "director@stewie.space", "role": "director", "status": "active", "created_at": 1},
             {"email": "ops@stewie.space", "role": "operator", "status": "active", "created_at": 2}]


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
        return "stewie_session=phase2" in (self.headers.get("Cookie") or "")

    def do_GET(self):
        if self.path.startswith("/auth/me"):
            return self._json(200, {"ok": True, "identity": "director@stewie.space", "role": "director",
                                    "has_password": True}) if self._authed() else self._json(401, {"ok": False})
        if self.path.startswith("/events"):
            return self._json(200, {"ok": True, "events": EVENTS}) if self._authed() else self._json(403, {"ok": False})
        if self.path.startswith("/admin/operators"):
            return self._json(200, {"ok": True, "operators": OPERATORS}) if self._authed() else self._json(403, {"ok": False})
        if self.path.startswith("/healthz"):
            return self._json(200, {"status": "ok", "version": "0.0.0-test", "uptime_s": 123,
                                    "audit": {"degraded": False}, "revocation": {"degraded": False}})
        if self.path.startswith("/metrics"):
            return self._json(200, {"uptime_s": 123, "latency": {}})
        return super().do_GET()

    def do_POST(self):
        if self.path.startswith("/auth/login"):
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            return self._json(200, {"ok": True, "operator": "director@stewie.space", "role": "director",
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
        page.goto(f"http://127.0.0.1:{port}/", wait_until="networkidle")
        page.fill('input[aria-label="email"]', "director@stewie.space")
        page.fill('input[aria-label="password"]', "pw")
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_selector(".ds-modebar", timeout=8000)

        # 1) Admin chrome -> operators + events
        page.get_by_role("button", name="Profile menu").click()
        page.get_by_role("menuitem", name="Admin").click()
        page.wait_for_selector('[data-testid="operators-table"]', timeout=8000)
        page.wait_for_selector('[data-testid="events-table"]', timeout=8000)
        n_ops = page.eval_on_selector_all('[data-testid="operators-table"] tbody tr', "els => els.length")
        n_ev = page.eval_on_selector_all('[data-testid="events-table"] tbody tr', "els => els.length")
        page.screenshot(path=str(OUT / "cockpit_admin.png"))
        page.get_by_role("button", name="Close").click()

        # 2) Metrics work area -> event timeline
        page.get_by_role("tab", name="Metrics").click()
        page.wait_for_selector('[data-testid="events-table"]', timeout=8000)

        # 3) Settings -> toggle Light theme
        page.get_by_role("button", name="Profile menu").click()
        page.get_by_role("menuitem", name="Settings").click()
        page.get_by_role("button", name="Light", exact=True).click()
        page.wait_for_timeout(150)
        light = page.eval_on_selector(".ds-root", "el => el.classList.contains('light')")
        page.screenshot(path=str(OUT / "cockpit_settings_light.png"))
        browser.close()
    srv.shutdown()

    if errors:
        print("FAIL — page errors:", *errors, sep="\n  ")
        return 1
    if n_ops < 2 or n_ev < 2:
        print(f"FAIL — Admin tables underfilled (operators={n_ops}, events={n_ev})")
        return 2
    if not light:
        print("FAIL — Settings did not apply the light theme to .ds-root")
        return 3
    print(f"PASS — Admin roster+audit ({n_ops} ops, {n_ev} events); Metrics timeline; Settings theme toggle. "
          f"Screenshots in {OUT}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
