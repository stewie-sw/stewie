"""Playwright visual smoke for the STEWIE desktop cockpit.

Drives real Chromium against a desktop-mode sidecar (STEWIE_DESKTOP=1) -- the exact UI the Electron
shell wraps -- asserts the operator-login gate is LIFTED (so the desktop bypass works in a real
browser, not just on the server), and screenshots every work-area pane.

Run (needs the repo .venv with playwright + chromium, and a free port):

    PYTHONNOUSERSITE=1 STEWIE_DESKTOP=1 .venv/bin/stewie-serve --port 8795 --host 127.0.0.1 &
    PYTHONNOUSERSITE=1 .venv/bin/python desktop/visual_smoke.py 8795 [out_dir]

Exit non-zero if the login gate is still up (the bypass regressed) or a pane fails to render.
"""
import os
import sys

from playwright.sync_api import sync_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "8795"
OUT = sys.argv[2] if len(sys.argv) > 2 else "/tmp/pw"
PANES = ["plan", "nav", "perception", "metrics", "report"]


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--use-gl=swiftshader", "--no-sandbox", "--ignore-gpu-blocklist"])
        pg = b.new_page(viewport={"width": 1600, "height": 1000})
        pg.goto(f"http://127.0.0.1:{PORT}/", wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(7000)                       # cockpit.js boot + Cesium globe paint
        am = pg.locator("#authmodal")
        disp = am.evaluate("e => getComputedStyle(e).display") if am.count() else "absent"
        who = pg.locator("#whoami-label")
        who_txt = who.inner_text() if who.count() else "?"
        print(f"authmodal_display={disp}  whoami={who_txt!r}")
        ok = disp in ("none", "absent")                 # the desktop login gate must be lifted
        for v in PANES:
            tab = pg.locator(f'button.vtab[data-view="{v}"]')
            if tab.count():
                tab.click()
                pg.wait_for_timeout(3500)
            path = os.path.join(OUT, f"{v}.png")
            pg.screenshot(path=path)
            size = os.path.getsize(path)
            print(f"{v}: {size} bytes")
            ok = ok and size > 5000                     # a real render, not a blank frame
        b.close()
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
