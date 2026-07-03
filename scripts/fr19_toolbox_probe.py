#!/usr/bin/env python3
"""[REQ:FR-19] Runtime Playwright probe: open the Plan ToolBox at phone widths and measure that the
expanded #edittoolbar (and every visible edit control) stays inside the viewport, and that #koradius (the
keep-out radius input) meets the 44px touch floor. This is the real-render check behind the FR-19 static
guard. Run: python scripts/fr19_toolbox_probe.py  (exit 0 = all widths pass)."""
from __future__ import annotations

import http.server
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from web01_csp_smoke import _make_handler, _production_csp  # noqa: E402

_WIDTHS = [320, 390, 430, 768]
_CESIUM = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "stewie", "server", "cesium")


def main() -> int:
    port = 8814
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), _make_handler(_CESIUM, _production_csp()))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    fails: list[str] = []
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, channel="chrome", args=["--use-gl=swiftshader", "--no-sandbox"])
        for w in _WIDTHS:
            pg = b.new_page(viewport={"width": w, "height": 780})
            pg.goto(f"http://127.0.0.1:{port}/", wait_until="domcontentloaded", timeout=40000)
            pg.wait_for_selector("#editmode", timeout=15000)
            pg.eval_on_selector("#editmode", "el => el.click()")     # open the ToolBox
            pg.wait_for_timeout(200)
            r = pg.evaluate(r"""(w) => {
                const out = {overflow: [], koradius_h: null, toolbar_right: null, expanded: false};
                const tb = document.getElementById('edittoolbar');
                const et = document.getElementById('edittools');
                out.expanded = !!et && getComputedStyle(et).display !== 'none';
                if (tb) { const b = tb.getBoundingClientRect(); out.toolbar_right = Math.round(b.right); }
                // every VISIBLE control inside the toolbar must stay within the viewport.
                for (const el of document.querySelectorAll('#edittoolbar button, #edittoolbar input, #edittoolbar label')) {
                    const b = el.getBoundingClientRect();
                    if (b.width === 0 || b.height === 0) continue;
                    if (b.right > w + 1 || b.left < -1) out.overflow.push((el.id||el.tagName)+':'+Math.round(b.right));
                }
                const ko = document.getElementById('koradius');
                if (ko) out.koradius_h = Math.round(ko.getBoundingClientRect().height);
                return out;
            }""", w)
            problems = []
            if not r["expanded"]:
                problems.append("ToolBox did not expand")
            if r["overflow"]:
                problems.append(f"offscreen controls: {r['overflow']}")
            if r["koradius_h"] is not None and r["koradius_h"] < 44:
                problems.append(f"#koradius height {r['koradius_h']}<44")
            status = "PASS" if not problems else "FAIL " + "; ".join(problems)
            print(f"  {w}px: toolbar_right={r['toolbar_right']} koradius_h={r['koradius_h']} -> {status}")
            if problems:
                fails.append(f"{w}px: {problems}")
            pg.close()
        b.close()
    srv.shutdown()
    if fails:
        print("FR-19 probe: FAIL"); return 1
    print("FR-19 probe: PASS (ToolBox contained + keep-out radius >=44px at all phone widths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
