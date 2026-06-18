#!/usr/bin/env python3
"""Phase-4c gate: the Plan solve. Sign in, place a build order on the real terrain, pick Cut, click
"Simulate plan", and verify the cockpit POSTs /plan and renders the returned PlanResult (feasibility +
makespan/energy/mass totals). /plan + /dem/heightfield shapes verbatim from the routers. Exits non-zero
on failure. Run: <repo>/.venv/bin/python cockpit/scripts/render_phase4c.py
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
FIXTURE = json.loads((HERE / "_dem_fixture.json").read_text())
CSP = ("default-src 'self'; script-src 'self' 'unsafe-eval' 'wasm-unsafe-eval' blob:; "
       "style-src 'self' 'unsafe-inline'; font-src 'self' data:; img-src 'self' data: blob:; "
       "connect-src 'self'; worker-src 'self' blob:; object-src 'none'; base-uri 'self'; "
       "frame-ancestors 'none'; form-action 'self'")
COOKIE = "stewie_session=phase4c; Path=/; HttpOnly"
# a realistic PlanResult (the shape /plan returns: top-level feasible + totals + plan_ir)
PLAN = {"ok": True, "feasible": True,
        "totals": {"makespan_s": 612.0, "energy_actual_kj": 2040.0, "mass_moved_kg": 118.0},
        "plan_ir": {"plan_id": "plan-ab12", "actions": [{}, {}, {}, {}]}}


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
        return "stewie_session=phase4c" in (self.headers.get("Cookie") or "")

    def do_GET(self):
        if self.path.startswith("/auth/me"):
            return self._json(200, {"ok": True, "identity": "ops@stewie.space", "role": "operator",
                                    "has_password": True}) if self._authed() else self._json(401, {"ok": False})
        if self.path.startswith("/dem/heightfield"):
            return self._json(200, FIXTURE)
        return super().do_GET()

    def do_POST(self):
        if self.path.startswith("/auth/login"):
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            return self._json(200, {"ok": True, "operator": "ops@stewie.space", "role": "operator",
                                    "must_set_password": False}, set_cookie=True)
        if self.path.startswith("/plan"):
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            return self._json(200, PLAN)
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
        page.wait_for_timeout(800)

        page.get_by_role("button", name="Cut", exact=True).click()  # place mode
        box = page.eval_on_selector('[data-testid="world-canvas"]',
                                    "c => { const r=c.getBoundingClientRect(); return [r.left,r.top,r.width,r.height]; }")
        page.mouse.click(box[0] + box[2] / 2, box[1] + box[3] / 2)
        page.wait_for_selector('[data-testid="order-queue"]', timeout=4000)
        page.get_by_role("button", name="Simulate plan").click()
        page.wait_for_selector('[data-testid="plan-result"]', timeout=8000)
        res_txt = page.text_content('[data-testid="plan-result"]') or ""
        page.screenshot(path=str(OUT / "cockpit_plan_result.png"))
        browser.close()
    srv.shutdown()

    if errors:
        print("FAIL — page errors:", *errors, sep="\n  ")
        return 1
    if "feasible" not in res_txt or "10.2" not in res_txt:  # 612 s -> 10.2 min
        print(f"FAIL — plan result missing feasibility/makespan: {res_txt!r}")
        return 2
    print(f"PASS — Simulate posted /plan and rendered the PlanResult ({res_txt.strip()[:90]}…). "
          f"Screenshot in {OUT}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
