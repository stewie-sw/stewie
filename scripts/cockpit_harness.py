#!/usr/bin/env python3
"""Faithful cockpit debug harness — drive the REAL logged-in cockpit in a headless browser with the
Cesium globe present, and report the state of the controls + every gated fetch. This is the harness that
reproduces the "nothing loads after login" class of bugs that a logged-out or Cesium-less probe cannot.

Why it is faithful (the three things a naive probe gets wrong):
  1. Cesium present  -- the dev server serves /cesium/ from server/cesium/ (docker-cp the bundle out of
     the frontend image once: `docker cp <frontend-container>:/usr/share/nginx/html/cesium
     stewie/server/cesium`). Without it the globe never initialises.
  2. Real login      -- seed a director via STEWIE_BOOTSTRAP_DIRECTOR/_PASSWORD on the server, then this
     harness fills the #auth-login form and signs in, so post-login data loaders actually run.
  3. Software GL      -- `--use-gl=swiftshader` so Cesium renders without a GPU (matches scripts/ui_eval).

Usage (start the server first, with a seeded director + an API key so auth is configured):

    D=$(mktemp -d)
    STEWIE_DATA_DIR=$D STEWIE_API_KEY=devkey123 \\
      STEWIE_BOOTSTRAP_DIRECTOR=dev@stewie.local STEWIE_BOOTSTRAP_PASSWORD=devpassword123 \\
      <venv>/bin/python -m uvicorn stewie.server.server:app --host 127.0.0.1 --port 8823
    <venv>/bin/python scripts/cockpit_harness.py --url http://127.0.0.1:8823 \\
      --email dev@stewie.local --password devpassword123

Prints a JSON report (control option counts, Cesium canvas presence, and the boot->post-login status
sequence of each gated fetch) and writes <out>/cockpit.png. Exits non-zero on a page error. NOT a CI unit
test -- it needs google-chrome + the cesium bundle + a running server, like the Godot/COLMAP evals.
"""
from __future__ import annotations

import argparse
import json
import sys

from playwright.sync_api import sync_playwright

# the auth-gated boot loaders whose boot->post-login status we track (a fix re-runs them on login)
GATED = ("/sites", "/missions", "/profiles", "/events", "/structures/custom", "/layers/raster/hazard.png")


def main() -> int:
    ap = argparse.ArgumentParser(description="faithful logged-in cockpit harness")
    ap.add_argument("--url", default="http://127.0.0.1:8823")
    ap.add_argument("--email", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--out", default="validation/ui")
    ap.add_argument("--channel", default="chrome")
    args = ap.parse_args()

    host = args.url.split("//", 1)[-1]
    errs: list = []
    seq: dict = {}
    with sync_playwright() as p:
        gl_args = ["--use-gl=swiftshader", "--no-sandbox"]    # software GL so Cesium renders without a GPU
        if args.channel not in ("none", "bundled"):
            b = p.chromium.launch(headless=True, channel=args.channel, args=gl_args)
        else:
            b = p.chromium.launch(headless=True, args=gl_args)
        pg = b.new_page(viewport={"width": 1500, "height": 920})
        pg.on("pageerror", lambda e: errs.append(str(e)))

        def on_resp(r):
            path = r.url.split(host, 1)[-1].split("?")[0] if host in r.url else None
            if path in GATED:
                seq.setdefault(path, []).append(r.status)
        pg.on("response", on_resp)

        pg.goto(args.url + "/", wait_until="domcontentloaded", timeout=45000)
        pg.wait_for_timeout(1500)
        pg.fill("#auth-email", args.email)
        pg.fill("#auth-pass", args.password)
        pg.click("#auth-do-login")
        pg.wait_for_timeout(6000)                 # let login + the post-login re-loaders settle

        state = pg.evaluate("""()=>{
          const c = id => { const e=document.getElementById(id);
            return !e ? '(absent)' : (e.tagName==='SELECT' ? e.options.length : 'present'); };
          let cv=false; try { cv = !!(window.viewer && window.viewer.scene); } catch(e) {}
          const cz=document.getElementById('cesium');
          return { authmsg:(document.getElementById('auth-msg')||{}).textContent||'',
                   cesium_canvas: !!(cz && cz.querySelector('canvas')), cesium_viewer: cv,
                   vehicle:c('vehicle'), soil:c('soil'), sitesel:c('sitesel'),
                   plancanvas:c('plancanvas'), landx:c('landx') }; }""")
        try:
            import os
            os.makedirs(args.out, exist_ok=True)
            pg.screenshot(path=os.path.join(args.out, "cockpit.png"))
        except Exception:                          # noqa: BLE001 -- screenshot is best-effort
            pass
        b.close()

    report = {"url": args.url, "state": state, "gated_status_sequence": {k: seq.get(k, []) for k in GATED},
              "page_errors": errs}
    print(json.dumps(report, indent=2))
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
