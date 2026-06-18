#!/usr/bin/env python3
"""Render the STEWIE design-system gallery in real headless Chromium and screenshot it for review.
Captures any page JS error (exits non-zero), and proves the sim-vs-truth invariant by capturing both
SIM-OPERATE (truth layer available) and OPERATE (truth layer disabled). Uses swiftshader so it works
without a GPU, mirroring scripts/ui_eval.py. Run: PYTHONNOUSERSITE=1 <venv>/bin/python gallery/render.py
"""
from __future__ import annotations

import pathlib
import sys

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE.parent / "validation"
OUT.mkdir(parents=True, exist_ok=True)
URL = (HERE / "gallery.html").as_uri()


def main() -> int:
    errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--use-gl=swiftshader", "--no-sandbox"])
        page = browser.new_page(viewport={"width": 1280, "height": 1100}, device_scale_factor=2)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.goto(URL, wait_until="networkidle")
        page.wait_for_selector(".ds-modebar", timeout=8000)        # React mounted
        page.wait_for_timeout(400)                                  # fonts settle
        page.screenshot(path=str(OUT / "gallery_sim_operate.png"), full_page=True)

        # flip to OPERATE -> the truth layer must disable (no truth on real hardware)
        page.get_by_role("button", name="OPERATE", exact=True).click()
        page.wait_for_timeout(250)
        page.screenshot(path=str(OUT / "gallery_operate.png"), full_page=True)

        # assert the invariant in the rendered DOM, not just visually
        truth_disabled = page.eval_on_selector(
            '.ds-source__opt[data-src="truth"]', "el => el.disabled")
        browser.close()

    if errors:
        print("PAGE ERRORS:", *errors, sep="\n  ")
        return 1
    if not truth_disabled:
        print("INVARIANT FAIL: truth layer not disabled in OPERATE")
        return 2
    print(f"render ok: {OUT}/gallery_sim_operate.png + gallery_operate.png; truth disabled in OPERATE = True")
    return 0


if __name__ == "__main__":
    sys.exit(main())
