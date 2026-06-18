#!/usr/bin/env python3
"""Phase-3 gate: sign in, open the Navigation/Autonomy work area, and verify it renders the FS-05
navigation contract from a stubbed /nav/contract — the stage readiness table with the live-planner-binary
shown as the gated tier, and the on-host-complete badge. Route shape verbatim from routers/nav.py +
lode.planner_routing.navigation_contract. Exits non-zero on failure.
Run: <repo>/.venv/bin/python cockpit/scripts/render_phase3.py
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
COOKIE = "stewie_session=phase3; Path=/; HttpOnly"
STAGES = [
    {"stage": "global_route", "present": True, "seam": "route_leg", "note": ""},
    {"stage": "local_trajectory", "present": True, "seam": "local_planner.plan_local", "note": ""},
    {"stage": "tracker", "present": True, "seam": "track_plan", "note": ""},
    {"stage": "recovery", "present": True, "seam": "recovery.recovery_needed", "note": ""},
    {"stage": "negative_obstacles", "present": True, "seam": "negative_obstacle_mask", "note": ""},
    {"stage": "ros_action_lowering", "present": True, "seam": "bridge.plan_lowering.lower_plan_ir", "note": ""},
    {"stage": "live_planner_binary", "present": False, "seam": "autoware/nav2", "note": "gated: needs a ROS/Space ROS host"},
]


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
        return "stewie_session=phase3" in (self.headers.get("Cookie") or "")

    def do_GET(self):
        if self.path.startswith("/auth/me"):
            return self._json(200, {"ok": True, "identity": "ops@stewie.space", "role": "operator",
                                    "has_password": True}) if self._authed() else self._json(401, {"ok": False})
        if self.path.startswith("/nav/contract"):
            return self._json(200, {"ok": True, "version": "1.0", "on_host_complete": True, "stages": STAGES})
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
        page.goto(f"http://127.0.0.1:{port}/", wait_until="networkidle")
        page.fill('input[aria-label="email"]', "ops@stewie.space")
        page.fill('input[aria-label="password"]', "pw")
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_selector(".ds-modebar", timeout=8000)

        page.get_by_role("tab", name="Navigation").click()
        page.wait_for_selector('[data-testid="nav-stages"]', timeout=8000)
        n_rows = page.eval_on_selector_all('[data-testid="nav-stages"] tbody tr', "els => els.length")
        gated = page.eval_on_selector_all('[data-testid="nav-stages"] tbody tr',
                                          "els => els.filter(r => /gated/.test(r.textContent)).length")
        badge = page.text_content('[data-testid="onhost-badge"]') or ""
        page.screenshot(path=str(OUT / "cockpit_navigation.png"))
        browser.close()
    srv.shutdown()

    if errors:
        print("FAIL — page errors:", *errors, sep="\n  ")
        return 1
    if n_rows < 7 or gated < 1:
        print(f"FAIL — nav contract underfilled (rows={n_rows}, gated={gated})")
        return 2
    if "wired" not in badge:
        print(f"FAIL — on-host badge wrong: {badge!r}")
        return 3
    print(f"PASS — Navigation contract renders {n_rows} stages ({gated} gated tier) + on-host badge "
          f"({badge!r}). Screenshot in {OUT}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
