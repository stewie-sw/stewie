#!/usr/bin/env python3
"""[REQ:FR-18] Runtime Playwright probe: render /program at phone widths and measure that the filter
buttons (.fbtn), the search box (#program-search), and the row chips (.rowchip) meet the 44px touch floor.
The row chips are rendered by program_board.js from /program/snapshot, so this serves program.html + the
committed snapshot + the assets, then measures the real rects. Run: python scripts/fr18_program_touch_probe.py"""
from __future__ import annotations

import http.server
import os
import threading

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WEB = os.path.join(_ROOT, "stewie", "server", "web")
_SNAP = os.path.join(_ROOT, "stewie", "server", "program_snapshot.json")
_WIDTHS = [320, 390, 430, 768]


class _H(http.server.BaseHTTPRequestHandler):
    def _send(self, body: bytes, ctype: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        p = self.path.split("?", 1)[0]
        if p in ("/", "/program"):
            self._send(open(os.path.join(_WEB, "program.html"), "rb").read(), "text/html")
        elif p == "/program/snapshot":
            self._send(open(_SNAP, "rb").read(), "application/json")
        elif p.startswith("/assets/"):
            fp = os.path.join(_WEB, "assets", os.path.relpath(p[len("/assets/"):]))
            if os.path.isfile(fp):
                self._send(open(fp, "rb").read(),
                           "application/javascript" if fp.endswith(".js") else "image/png")
            else:
                self.send_error(404)
        else:
            self.send_error(404)

    def log_message(self, *a) -> None:
        pass


def main() -> int:
    port = 8815
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    fails: list[str] = []
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, channel="chrome", args=["--use-gl=swiftshader", "--no-sandbox"])
        for w in _WIDTHS:
            pg = b.new_page(viewport={"width": w, "height": 780})
            pg.goto(f"http://127.0.0.1:{port}/program", wait_until="domcontentloaded", timeout=40000)
            pg.wait_for_selector(".rowchip", timeout=15000)
            r = pg.evaluate(r"""(w) => {
                const out = {under44: [], overflow: false, counts: {}};
                for (const sel of ['.fbtn', '.rowchip', '#program-search']) {
                    const els = [...document.querySelectorAll(sel)];
                    out.counts[sel] = els.length;
                    for (const el of els) {
                        const b = el.getBoundingClientRect();
                        if (b.width === 0 && b.height === 0) continue;
                        if (b.height < 44) { out.under44.push(sel + ':' + Math.round(b.height)); break; }
                    }
                }
                out.overflow = document.scrollingElement.scrollWidth > w + 1;
                return out;
            }""", w)
            problems = []
            if r["under44"]:
                problems.append(f"under-44px: {r['under44']}")
            if r["overflow"]:
                problems.append("body horizontal overflow")
            status = "PASS" if not problems else "FAIL " + "; ".join(problems)
            print(f"  {w}px: controls={r['counts']} -> {status}")
            if problems:
                fails.append(f"{w}px: {problems}")
            pg.close()
        b.close()
    srv.shutdown()
    if fails:
        print("FR-18 probe: FAIL"); return 1
    print("FR-18 probe: PASS (/program filter/search/row controls >=44px at all phone widths, no overflow)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
