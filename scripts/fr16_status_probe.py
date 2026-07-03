#!/usr/bin/env python3
"""[REQ:FR-16] Runtime Playwright probe: at phone widths, the operational status/account chrome
(#healthchip / #alertbtn / #wsbadge / #whoami) is visible in the FIRST viewport (its left edge inside the
screen at scroll position 0), where it used to sit at x>=570 inside the horizontally-scrolling #viewtabs.
Forces #wsbadge/#whoami visible (they are display:none until signed in) so the layout is measured with all
four present. Run: python scripts/fr16_status_probe.py"""
from __future__ import annotations

import http.server
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from web01_csp_smoke import _make_handler, _production_csp  # noqa: E402

_WIDTHS = [320, 360, 390, 430]
_CESIUM = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "stewie", "server", "cesium")
_IDS = ["healthchip", "alertbtn", "wsbadge", "whoami"]


def main() -> int:
    port = 8816
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), _make_handler(_CESIUM, _production_csp()))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    fails: list[str] = []
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, channel="chrome", args=["--use-gl=swiftshader", "--no-sandbox"])
        for w in _WIDTHS:
            pg = b.new_page(viewport={"width": w, "height": 780})
            pg.goto(f"http://127.0.0.1:{port}/", wait_until="domcontentloaded", timeout=40000)
            pg.wait_for_selector("#viewtabs .vtab", timeout=15000)
            r = pg.evaluate(r"""(args) => {
                const [w, ids] = args;
                // force the account/workspace chrome visible (display:none until signed in) with sample text.
                const ws = document.getElementById('wsslot'); if (ws) ws.style.display = 'inline-flex';
                const wb = document.getElementById('wsbadge'); if (wb) { wb.style.display = 'inline-flex'; wb.textContent = 'WORKSPACE'; }
                const wa = document.getElementById('whoami'); if (wa) wa.style.display = 'inline-flex';
                const wl = document.getElementById('whoami-label'); if (wl) wl.textContent = 'operator';
                const out = {offscreen: [], overlap: [], overflow: false, rects: {}};
                const boxes = [];
                for (const id of ids) {
                    const el = document.getElementById(id);
                    if (!el) continue;
                    const b = el.getBoundingClientRect();
                    if (b.width === 0 && b.height === 0) continue;
                    out.rects[id] = Math.round(b.left) + '..' + Math.round(b.right);
                    // visible in the first viewport: left edge on-screen (not scrolled off to the right).
                    if (b.left >= w || b.right <= 0) out.offscreen.push(id + '@' + Math.round(b.left));
                    boxes.push([id, b]);
                }
                // no two status controls may overlap (the reorder hack's failure mode).
                for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
                    const a = boxes[i][1], c = boxes[j][1];
                    const ox = Math.min(a.right, c.right) - Math.max(a.left, c.left);
                    const oy = Math.min(a.bottom, c.bottom) - Math.max(a.top, c.top);
                    if (ox > 1 && oy > 1) out.overlap.push(boxes[i][0] + '/' + boxes[j][0]);
                }
                out.overflow = document.scrollingElement.scrollWidth > w + 1;
                return out;
            }""", [w, _IDS])
            problems = []
            if r["offscreen"]:
                problems.append(f"offscreen: {r['offscreen']}")
            if r["overlap"]:
                problems.append(f"overlap: {r['overlap']}")
            if r["overflow"]:
                problems.append("body horizontal overflow")
            status = "PASS" if not problems else "FAIL " + "; ".join(problems)
            print(f"  {w}px: {r['rects']} -> {status}")
            if problems:
                fails.append(f"{w}px: {problems}")
            pg.close()
        b.close()
    srv.shutdown()
    if fails:
        print("FR-16 probe: FAIL"); return 1
    print("FR-16 probe: PASS (status/account chrome visible in the first viewport at all phone widths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
