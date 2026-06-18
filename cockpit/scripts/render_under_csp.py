#!/usr/bin/env python3
"""Phase-0 gate: serve the built cockpit dist/ under the EXACT deployed production CSP header and render it
in real headless Chromium. Asserts (1) zero CSP violations / page errors, (2) the design-system shell
mounted (.ds-root + the ModeBar), and (3) the sim-vs-truth invariant works live: switching to OPERATE
disables the truth source layer. Screenshots both states for review. Exits non-zero on any failure.
Run: <repo>/.venv/bin/python cockpit/scripts/render_under_csp.py
"""
from __future__ import annotations

import functools
import http.server
import pathlib
import threading

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
DIST = HERE.parent / "dist"
OUT = HERE.parent / "validation"
OUT.mkdir(parents=True, exist_ok=True)

# verbatim from deploy/nginx.conf:46 (the deployed production policy)
CSP = ("default-src 'self'; script-src 'self' 'unsafe-eval' 'wasm-unsafe-eval' blob: "
       "https://static.cloudflareinsights.com; style-src 'self' 'unsafe-inline'; worker-src 'self' blob:; "
       "img-src 'self' data: blob: https://trek.nasa.gov https://server.arcgisonline.com "
       "https://gibs.earthdata.nasa.gov; connect-src 'self' https://trek.nasa.gov "
       "https://server.arcgisonline.com https://gibs.earthdata.nasa.gov https://cloudflareinsights.com; "
       "font-src 'self' data:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'")


class CSPHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Content-Security-Policy", CSP)
        super().end_headers()

    def log_message(self, *_a):  # quiet
        pass


def main() -> int:
    handler = functools.partial(CSPHandler, directory=str(DIST))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{port}/"

    viol: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--use-gl=swiftshader", "--no-sandbox"])
        page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
        page.on("pageerror", lambda e: viol.append(f"pageerror: {e}"))
        page.on("console", lambda m: viol.append(f"console.error: {m.text}") if m.type == "error" else None)
        # CSP violations surface as a securitypolicyviolation event in the page
        page.add_init_script(
            "window.__csp=[];addEventListener('securitypolicyviolation',e=>"
            "window.__csp.push(e.violatedDirective+' '+e.blockedURI));")
        page.goto(url, wait_until="networkidle")
        page.wait_for_selector(".ds-root .ds-modebar", timeout=8000)
        page.wait_for_timeout(400)
        page.screenshot(path=str(OUT / "cockpit_sim_operate.png"))
        csp_hits = page.evaluate("window.__csp || []")

        # flip to OPERATE -> truth layer must disable (the sim-vs-truth invariant, live in the store)
        page.get_by_role("button", name="OPERATE", exact=True).click()
        page.wait_for_timeout(250)
        page.screenshot(path=str(OUT / "cockpit_operate.png"))
        truth_disabled = page.eval_on_selector('.ds-source__opt[data-src="truth"]', "el => el.disabled")
        browser.close()
    srv.shutdown()

    if viol:
        print("FAIL — page errors:", *viol, sep="\n  ")
        return 1
    if csp_hits:
        print("FAIL — CSP violations under the production policy:", *csp_hits, sep="\n  ")
        return 2
    if not truth_disabled:
        print("FAIL — truth layer not disabled in OPERATE")
        return 3
    print(f"PASS — cockpit renders under the production CSP with zero violations; shell mounted; "
          f"truth disabled in OPERATE. Screenshots in {OUT}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
