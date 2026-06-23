#!/usr/bin/env python3
"""Interactive cockpit verification — assert the WIRING that a screenshot cannot.

The screenshot harness (cockpit_harness.py) only captures the default state, so a structural reorg that
silently breaks a control (e.g. a moved Feasibility input whose `estimate()` listener no longer fires,
or a tab whose pane no longer activates) renders an identical-looking screenshot and passes. This harness
drives the REAL logged-in cockpit and asserts behavior:

  1. ESTIMATE wiring: change `#padW` and assert `#est` re-renders (the quick-estimate listener still fires).
  2. TAB switching: click each `.vtab[data-view=...]` and assert its `VIEW_PANE` target pane goes .active.

Same launch contract as cockpit_harness.py (seeded director + google-chrome + the cesium bundle):

    D=$(mktemp -d)
    STEWIE_DATA_DIR=$D STEWIE_API_KEY=devkey123 \\
      STEWIE_BOOTSTRAP_DIRECTOR=dev@stewie.local STEWIE_BOOTSTRAP_PASSWORD=devpassword123 \\
      <venv>/bin/python -m uvicorn stewie.server.server:app --host 127.0.0.1 --port 8823
    <venv>/bin/python scripts/cockpit_interactive_check.py --url http://127.0.0.1:8823 \\
      --email dev@stewie.local --password devpassword123

Prints a JSON report (per-check PASS/FAIL + page errors) and exits non-zero on any failure. NOT a CI unit
test -- it needs google-chrome + the cesium bundle + a running server, like the Godot/COLMAP evals.
"""
from __future__ import annotations

import argparse
import json
import sys

from playwright.sync_api import sync_playwright

# the tab -> pane mapping mirrors VIEW_PANE in cockpit.js; `plan` has no overlay pane (the bare globe).
VIEW_PANE = {"rehearse": "pane_rehearse", "nav": "navview", "perception": "renderpanel",
             "metrics": "execview", "report": "pane-report"}


def main() -> int:
    ap = argparse.ArgumentParser(description="interactive cockpit wiring check")
    ap.add_argument("--url", default="http://127.0.0.1:8823")
    ap.add_argument("--email", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--channel", default="chrome")
    args = ap.parse_args()

    errs: list = []
    checks: dict = {}
    with sync_playwright() as p:
        gl_args = ["--use-gl=swiftshader", "--no-sandbox"]
        if args.channel not in ("none", "bundled"):
            b = p.chromium.launch(headless=True, channel=args.channel, args=gl_args)
        else:
            b = p.chromium.launch(headless=True, args=gl_args)
        pg = b.new_page(viewport={"width": 1500, "height": 920})
        pg.on("pageerror", lambda e: errs.append(str(e)))

        pg.goto(args.url + "/", wait_until="domcontentloaded", timeout=45000)
        pg.wait_for_timeout(1500)
        pg.fill("#auth-email", args.email)
        pg.fill("#auth-pass", args.password)
        pg.click("#auth-do-login")
        pg.wait_for_timeout(6000)

        # 1) ESTIMATE wiring -- changing padW must re-render #est (the quick-estimate listener still fires).
        # padW lives in a collapsible <details> section (collapseSidebar), so it may be hidden; set the
        # value + dispatch the 'input' event via JS (exactly what a keystroke does) to test the listener
        # regardless of collapse state -- a visibility check is a separate concern from the wiring.
        try:
            _txt = "(id)=>{const e=document.getElementById(id);return e?(e.textContent||''):null;}"
            before = pg.evaluate(_txt, "est")    # textContent, not inner_text: #est sits in a collapsed
            changed = pg.evaluate("""()=>{const el=document.getElementById('padW');
              if(!el) return null; el.value = (el.value==='20'?'30':'20');
              el.dispatchEvent(new Event('input',{bubbles:true})); return el.value;}""")
            pg.wait_for_timeout(600)
            after = pg.evaluate(_txt, "est")     # <details> section, so inner_text would read '' (hidden)
            checks["estimate_fires_on_padW_change"] = {
                "pass": changed is not None and bool(after) and after != before,
                "before": before[:60], "after": after[:60]}
        except Exception as e:  # noqa: BLE001
            checks["estimate_fires_on_padW_change"] = {"pass": False, "error": str(e)}

        # 2) TAB switching -- clicking each visible tab must activate its VIEW_PANE target
        for view, pane in VIEW_PANE.items():
            try:
                tab = pg.query_selector(f'.vtab[data-view="{view}"]')
                if not tab or not tab.is_visible():
                    checks[f"tab_{view}"] = {"pass": True, "skipped": "tab not visible for this role"}
                    continue
                tab.click()
                pg.wait_for_timeout(500)
                active = pg.evaluate(
                    "(id)=>{const e=document.getElementById(id);return !!e && e.classList.contains('active');}",
                    pane)
                checks[f"tab_{view}"] = {"pass": bool(active), "pane": pane, "active": bool(active)}
            except Exception as e:  # noqa: BLE001
                checks[f"tab_{view}"] = {"pass": False, "error": str(e)}
        b.close()

    all_pass = all(c.get("pass") for c in checks.values()) and not errs
    print(json.dumps({"url": args.url, "all_pass": all_pass, "checks": checks, "page_errors": errs},
                     indent=2))
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
