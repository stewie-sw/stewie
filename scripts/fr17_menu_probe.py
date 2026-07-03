#!/usr/bin/env python3
"""[REQ:FR-17] Runtime Playwright probe: force the More + account menus open at phone widths and confirm
each menu rect is fully within the viewport (no offscreen edge), where they used to open at right edges
~624/~881px. Run: python scripts/fr17_menu_probe.py"""
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
    port = 8818
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
                const [w, h] = args;
                const out = {rects: {}, offscreen: []};
                // #profmenu lives inside #whoami (display:none until signed in) -- force the account chrome
                // visible so the account menu actually renders and can be measured.
                const wa = document.getElementById('whoami'); if (wa) wa.style.display = 'inline-flex';
                for (const id of ['moremenu', 'profmenu']) {
                    const el = document.getElementById(id);
                    if (!el) continue;
                    el.style.display = (id === 'moremenu') ? 'flex' : 'block';   // force open
                    const b = el.getBoundingClientRect();
                    out.rects[id] = `${Math.round(b.left)}..${Math.round(b.right)} x ${Math.round(b.top)}..${Math.round(b.bottom)}`;
                    if (b.left < -1 || b.right > w + 1 || b.top < -1 || b.bottom > h + 1)
                        out.offscreen.push(id);
                }
                return out;
            }""", [w, 780])
            problems = [f"offscreen: {r['offscreen']}"] if r["offscreen"] else []
            status = "PASS" if not problems else "FAIL " + "; ".join(problems)
            print(f"  {w}px: {r['rects']} -> {status}")
            if problems:
                fails.append(f"{w}px: {problems}")
            pg.close()
        b.close()
    srv.shutdown()
    if fails:
        print("FR-17 probe: FAIL"); return 1
    print("FR-17 probe: PASS (More + account menus fully within the viewport at all phone widths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
