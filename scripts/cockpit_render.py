#!/usr/bin/env python3
"""Cockpit render-verification harness (Phase 2 / FS-18). Drive the LIVE stewie/server cockpit in a real
headless browser (swiftshader -> no GPU needed), optionally sign in, screenshot the sign-in gate, the
signed-in cockpit, each work-area pane, the Settings pane, and a mobile width, and FAIL if any pane logs
a JS error. Like scripts/ui_eval.py but for the current stewie/server cockpit (not the old planet_browser).

NOT a CI unit test -- it launches a real browser against a running server. Usage:

    # 1) start the server (provision a director so the panes are reachable):
    STEWIE_DATA_DIR=/tmp/cr STEWIE_API_KEY=k \\
      STEWIE_BOOTSTRAP_DIRECTOR=admin@stewie.space STEWIE_BOOTSTRAP_PASSWORD=a-strong-passphrase \\
      PYTHONPATH=. <venv>/bin/python -m uvicorn stewie.server.server:app --host 127.0.0.1 --port 8799
    # 2) render + screenshot it:
    <venv>/bin/python scripts/cockpit_render.py --url http://127.0.0.1:8799 \\
      --email admin@stewie.space --password a-strong-passphrase --out validation/cockpit

Writes <out>/<shot>.png + <out>/cockpit_render.json; exits non-zero on any pane JS error.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from playwright.sync_api import sync_playwright

# FS-20: the work-area tab bar carries only the mission views; System / Settings / Admin moved into
# the profile menu (role-gated), so the harness reaches those by opening the menu first.
WORK_PANES = ["plan", "nav", "perception", "metrics", "report", "rehearse", "fleet",
              "construction", "models"]   # REHEARSE candidate-compare + FS-03 Fleet/Construction/Models
PROFILE_PANES = ["settings", "system", "admin"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8799")
    ap.add_argument("--out", default="validation/cockpit")
    ap.add_argument("--email", default="")
    ap.add_argument("--password", default="")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    errors: list[str] = []
    shots: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--use-gl=swiftshader", "--no-sandbox", "--disable-gpu-sandbox"])
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(a.url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)

        def shot(name: str) -> None:
            path = os.path.join(a.out, f"{name}.png")
            page.screenshot(path=path)
            shots.append(path)

        shot("00_gate")
        if a.email:
            try:
                page.fill("#auth-email", a.email)
                page.fill("#auth-pass", a.password)
                page.click("#auth-do-login")
                page.wait_for_timeout(3000)
            except Exception as e:                       # noqa: BLE001 -- record, keep rendering
                errors.append(f"login: {e!r}")
        shot("01_cockpit")
        try:                                             # FS-20: capture the account menu OPEN (moved items + role-gating)
            page.click("#profbtn", timeout=3000)
            page.wait_for_timeout(300)
            shot("02_profile_menu")
            page.click("#profbtn")                       # close it again before the pane loop reopens it
            page.wait_for_timeout(150)
        except Exception as e:                           # noqa: BLE001
            errors.append(f"profile menu: {e!r}")
        for pane in WORK_PANES:                          # mission views: a .vtab in the top bar
            try:
                page.click(f".vtab[data-view='{pane}']", timeout=3000)
                page.wait_for_timeout(800)
                shot(f"pane_{pane}")
            except Exception as e:                       # noqa: BLE001
                errors.append(f"pane {pane}: {e!r}")
        for pane in PROFILE_PANES:                       # FS-20: reached via the profile menu, not the tab bar
            try:
                page.click("#profbtn", timeout=3000)     # open the account menu
                page.wait_for_timeout(200)
                page.click(f"#profmenu [data-view='{pane}']", timeout=3000)
                page.wait_for_timeout(800)
                shot(f"pane_{pane}")
            except Exception as e:                       # noqa: BLE001
                errors.append(f"pane {pane}: {e!r}")
        # FS-20 IA invariants: the moved views are OFF the work-area tab bar and present in the profile menu.
        vtab_views = page.eval_on_selector_all(".vtab", "els => els.map(e => e.dataset.view)")
        for moved in ("system", "settings", "admin"):
            if moved in vtab_views:
                errors.append(f"FS-20: '{moved}' still in the work-area tab bar {vtab_views}")
            if not page.query_selector(f"#profmenu [data-view='{moved}']"):
                errors.append(f"FS-20: '{moved}' missing from the profile menu")
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(800)
        shot("99_mobile")
        # the #134 live-site fix: the automation-key box must be gone from the DOM
        set_apikey_present = 'id="set-apikey"' in page.content()
        browser.close()

    summary = {"url": a.url, "shots": shots, "errors": errors,
               "set_apikey_present": set_apikey_present, "ok": not errors and not set_apikey_present}
    with open(os.path.join(a.out, "cockpit_render.json"), "w") as fh:
        json.dump(summary, fh, indent=2)
    print(json.dumps({"ok": summary["ok"], "shots": len(shots), "errors": errors[:5],
                      "set_apikey_present": set_apikey_present}))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
