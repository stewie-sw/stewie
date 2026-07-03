#!/usr/bin/env python3
"""[REQ:FR-14] Runtime Playwright probe: the nav surface's #navmode badge reads PREVIEW by default (no live
autonomy attested), and setNavMode() flips it to LIVE ONLY when a live-autonomy attestation is present --
proving the label is a real gate, not a static stub. Run: python scripts/fr14_nav_preview_probe.py"""
from __future__ import annotations

import http.server
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from web01_csp_smoke import _make_handler, _production_csp  # noqa: E402

_CESIUM = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "stewie", "server", "cesium")


def main() -> int:
    port = 8823
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), _make_handler(_CESIUM, _production_csp()))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    from playwright.sync_api import sync_playwright
    problems: list[str] = []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, channel="chrome", args=["--use-gl=swiftshader", "--no-sandbox"])
        pg = b.new_page(viewport={"width": 1280, "height": 900})
        pg.goto(f"http://127.0.0.1:{port}/", wait_until="domcontentloaded", timeout=40000)
        pg.wait_for_selector("#viewtabs .vtab", timeout=15000)
        r = pg.evaluate(r"""() => {
            const el = document.getElementById('navmode');
            if (!el) return {missing: true};
            const out = {};
            if (typeof setNavMode === 'function') setNavMode();
            out.default = el.textContent.trim();                    // no attestation -> PREVIEW
            window.STEWIE_LIVE_AUTONOMY = true; setNavMode();
            out.attested = el.textContent.trim();                   // attested -> LIVE
            window.STEWIE_LIVE_AUTONOMY = false; setNavMode();
            out.revoked = el.textContent.trim();                    // revoked -> PREVIEW again
            return out;
        }""")
        if r.get("missing"):
            problems.append("#navmode badge missing")
        else:
            if r["default"] != "PREVIEW":
                problems.append(f"default not PREVIEW: {r['default']}")
            if r["attested"] != "LIVE":
                problems.append(f"attestation did not flip to LIVE: {r['attested']}")
            if r["revoked"] != "PREVIEW":
                problems.append(f"revocation did not return to PREVIEW: {r['revoked']}")
            print(f"  navmode: default={r['default']} attested={r['attested']} revoked={r['revoked']}")
        pg.close()
        b.close()
    srv.shutdown()
    if problems:
        print("FR-14 probe: FAIL " + "; ".join(problems)); return 1
    print("FR-14 probe: PASS (nav labeled PREVIEW; flips to LIVE only on a live-autonomy attestation)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
