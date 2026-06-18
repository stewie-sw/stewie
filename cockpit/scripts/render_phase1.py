#!/usr/bin/env python3
"""Phase-1 gate: drive the real auth flow against a session-cookie-aware /auth/* stub, under the production
CSP. Verifies: (1) unauthenticated -> the sign-in screen; (2) POST /auth/login sets a cookie and the cockpit
mounts with the role from /auth/me; (3) the FS-20 profile menu is role-gated (a director sees Admin).
Screenshots the sign-in + authed states. Exits non-zero on any failure. The /auth/me shape is verbatim from
routers/auth.py ({ok, identity, role, has_password}). Run: <repo>/.venv/bin/python cockpit/scripts/render_phase1.py
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
CSP = ("default-src 'self'; script-src 'self' 'unsafe-eval' 'wasm-unsafe-eval' blob: "
       "https://static.cloudflareinsights.com; style-src 'self' 'unsafe-inline'; font-src 'self' data:; "
       "img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; base-uri 'self'; "
       "frame-ancestors 'none'; form-action 'self'")
COOKIE = "stewie_session=phase1; Path=/; HttpOnly"


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):  # CSP on every response (static + json)
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
        return "stewie_session=phase1" in (self.headers.get("Cookie") or "")

    def do_GET(self):
        if self.path.startswith("/auth/me"):
            if self._authed():
                return self._json(200, {"ok": True, "identity": "director@stewie.space",
                                        "role": "director", "has_password": True})
            return self._json(401, {"ok": False, "error": "unauthenticated"})
        return super().do_GET()

    def do_POST(self):
        if self.path.startswith("/auth/login"):
            length = int(self.headers.get("Content-Length") or 0)
            self.rfile.read(length)
            return self._json(200, {"ok": True, "operator": "director@stewie.space",
                                    "role": "director", "must_set_password": False}, set_cookie=True)
        return self._json(404, {"ok": False})

    def log_message(self, *_a):
        pass


def main() -> int:
    handler = functools.partial(Handler, directory=str(DIST))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{port}/"

    errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--use-gl=swiftshader", "--no-sandbox"])
        page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        page.goto(url, wait_until="networkidle")

        # 1) unauthenticated -> sign-in screen
        page.wait_for_selector('input[aria-label="email"]', timeout=8000)
        page.screenshot(path=str(OUT / "cockpit_signin.png"))
        if page.query_selector(".ds-modebar"):
            print("FAIL — cockpit shell visible before sign-in")
            return 1

        # 2) sign in -> cockpit mounts
        page.fill('input[aria-label="email"]', "director@stewie.space")
        page.fill('input[aria-label="password"]', "pw")
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_selector(".ds-root .ds-modebar", timeout=8000)
        page.wait_for_timeout(300)
        page.screenshot(path=str(OUT / "cockpit_authed.png"))

        # 3) FS-20 profile menu is role-gated -> a director sees Admin
        page.get_by_role("button", name="Profile menu").click()
        page.wait_for_timeout(150)
        admin = page.query_selector('[data-chrome="admin"]')
        system = page.query_selector('[data-chrome="system"]')
        browser.close()
    srv.shutdown()

    if errors:
        print("FAIL — page errors:", *errors, sep="\n  ")
        return 2
    if not (admin and system):
        print(f"FAIL — director should see System+Admin chrome (system={bool(system)} admin={bool(admin)})")
        return 3
    print(f"PASS — sign-in gate -> authed cockpit (role from /auth/me); FS-20 menu role-gated "
          f"(director sees System+Admin). Screenshots in {OUT}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
