#!/usr/bin/env python3
"""WEB-01 production-CSP browser smoke -- prove the self-hosted Cesium cockpit initialises under the REAL
production Content-Security-Policy, with no CSP violation.

It reproduces the production edge: it serves stewie/server/index.html with the EXACT CSP header from
deploy/nginx.conf, serves the vendored Cesium bundle same-origin at /cesium/ (the bytes the frontend
image vendors at build time), then drives it in headless Chrome (swiftshader, no GPU needed) and asserts:

  * window.Cesium is defined          -> the self-hosted bundle LOADED under `script-src 'self'`
  * the #cesium canvas was created     -> the Plan canvas (Cesium.Viewer) INITIALISED
  * zero CSP violations / page errors  -> nothing was refused by the policy

NOT a CI unit test (needs google-chrome + playwright + a Cesium build, like ui_eval.py / the Godot evals).
Vendor a Cesium build first, e.g.:
    curl -sL https://registry.npmjs.org/cesium/-/cesium-1.119.0.tgz | tar xz -C /tmp package/Build/Cesium
    <venv>/bin/python scripts/web01_csp_smoke.py --cesium-dir /tmp/package/Build/Cesium
Exits non-zero on any failure.
"""
from __future__ import annotations

import argparse
import http.server
import os
import re
import sys
import threading

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _production_csp() -> str:
    """The exact CSP string the production nginx sends (single source of truth: deploy/nginx.conf)."""
    conf = open(os.path.join(_ROOT, "deploy/nginx.conf")).read()
    m = re.search(r'Content-Security-Policy\s+"([^"]+)"', conf)
    if not m:
        raise SystemExit("could not find the CSP header in deploy/nginx.conf")
    return m.group(1)


def _make_handler(cesium_dir: str, csp: str):
    web = os.path.join(_ROOT, "stewie", "server")

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):           # quiet
            pass

        def _send(self, body: bytes, ctype: str, with_csp: bool):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            if with_csp:                      # match production: the CSP rides on the HTML page
                self.send_header("Content-Security-Policy", csp)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            try:
                if path in ("/", "/index.html", "/app"):
                    self._send(open(os.path.join(web, "index.html"), "rb").read(),
                               "text/html; charset=utf-8", with_csp=True)
                elif path == "/bodies.json":
                    self._send(open(os.path.join(web, "bodies.json"), "rb").read(),
                               "application/json", with_csp=True)
                elif path == "/healthz":
                    self._send(b'{"status":"ok","version":"web01-smoke"}', "application/json", with_csp=True)
                elif path.startswith("/assets/"):     # ARCH-02: the external cockpit + cesium-config scripts
                    abase = os.path.join(web, "web", "assets")
                    full = os.path.normpath(os.path.join(abase, path[len("/assets/"):]))
                    if not full.startswith(os.path.normpath(abase)) or not os.path.isfile(full):
                        self.send_error(404); return
                    ext = os.path.splitext(full)[1].lower()
                    ctype = {".js": "text/javascript", ".css": "text/css"}.get(ext, "application/octet-stream")
                    self._send(open(full, "rb").read(), ctype, with_csp=False)
                elif path.startswith("/cesium/"):
                    rel = path[len("/cesium/"):]
                    full = os.path.normpath(os.path.join(cesium_dir, rel))
                    if not full.startswith(os.path.normpath(cesium_dir)) or not os.path.isfile(full):
                        self.send_error(404); return
                    ext = os.path.splitext(full)[1].lower()
                    ctype = {".js": "text/javascript", ".css": "text/css", ".json": "application/json",
                             ".wasm": "application/wasm", ".png": "image/png", ".jpg": "image/jpeg",
                             ".gif": "image/gif", ".svg": "image/svg+xml"}.get(ext, "application/octet-stream")
                    self._send(open(full, "rb").read(), ctype, with_csp=False)
                else:
                    self.send_error(404)
            except FileNotFoundError:
                self.send_error(404)

    return H


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cesium-dir", default="/tmp/cesium_vendor",
                    help="a Cesium Build dir containing Cesium.js + Workers/ + Assets/ + Widgets/")
    ap.add_argument("--port", type=int, default=8799)
    ap.add_argument("--channel", default="chrome")
    args = ap.parse_args()

    if not os.path.isfile(os.path.join(args.cesium_dir, "Cesium.js")):
        print(f"FAIL: no Cesium.js under {args.cesium_dir} (vendor a Cesium build first)")
        return 2
    csp = _production_csp()
    print("production CSP:", csp)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), _make_handler(args.cesium_dir, csp))
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        from playwright.sync_api import sync_playwright
        viol: list[str] = []
        errs: list[str] = []
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True, channel=args.channel,
                                  args=["--use-gl=swiftshader", "--no-sandbox"])
            pg = b.new_page(viewport={"width": 1440, "height": 900})
            pg.on("pageerror", lambda e: errs.append(str(e)))

            def on_console(m):
                tx = m.text or ""
                if "Content Security Policy" in tx or "Refused to" in tx or "violates the following" in tx:
                    viol.append(tx)
            pg.on("console", on_console)

            pg.goto(f"http://127.0.0.1:{args.port}/", wait_until="domcontentloaded", timeout=40000)
            pg.wait_for_selector("#cesium", timeout=15000)
            # let loadBody("moon") construct the Viewer
            try:
                pg.wait_for_function("() => typeof window.Cesium !== 'undefined' && "
                                     "document.querySelector('#cesium canvas') !== null", timeout=20000)
            except Exception:
                pass
            has_cesium = pg.evaluate("() => typeof window.Cesium !== 'undefined'")
            has_canvas = pg.evaluate("() => document.querySelector('#cesium canvas') !== null")
            base_url = pg.evaluate("() => window.CESIUM_BASE_URL || null")
            b.close()
    finally:
        srv.shutdown()

    print(f"window.Cesium defined : {has_cesium}")
    print(f"#cesium canvas created: {has_canvas}")
    print(f"CESIUM_BASE_URL       : {base_url}")
    print(f"CSP violations        : {len(viol)}" + ("" if not viol else " -> " + " | ".join(viol[:5])))
    print(f"page errors           : {len(errs)}" + ("" if not errs else " -> " + " | ".join(errs[:5])))
    ok = has_cesium and has_canvas and not viol and not errs
    print("WEB-01 CSP SMOKE", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
