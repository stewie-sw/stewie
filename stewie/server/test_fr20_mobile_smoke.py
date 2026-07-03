"""[REQ:FR-20] Mobile command-surface smoke harness: the acceptance gate that codifies the mobile review
(FR-16..19) across five phone/tablet viewports (320/360/390/430/768). It boots the real cockpit + /program
statically and, with a real Chrome, asserts per viewport:
  (a) no body horizontal overflow,
  (b) the primary nav/action controls (.vtab, #drawerbtn, #editmode; /program .fbtn/.rowchip/#program-search)
      meet the 44px touch floor,
  (c) the ToolBox stays viewport-contained when #editmode opens (FR-19),
  (d) the More/account menus stay in-viewport when opened (FR-17).
It does NOT yet assert (e) health/alerts visible-in-first-viewport -- FR-16 (the fixed status bar) is not
built, so that check is deliberately deferred to FR-16 rather than faked. Skips cleanly where a system
Chrome / Playwright is unavailable (CI without a browser); runs + is verified on-host.
"""
import http.server
import os
import sys
import threading

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_HERE))   # stewie/server -> stewie -> repo root (where scripts/ lives)
sys.path.insert(0, os.path.join(_REPO, "scripts"))

_WIDTHS = [320, 360, 390, 430, 768]
_CESIUM = os.path.join(_HERE, "cesium")
_WEB = os.path.join(_HERE, "web")
_SNAP = os.path.join(_HERE, "program_snapshot.json")


def _have_browser() -> bool:
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        return False
    return os.path.exists("/usr/bin/google-chrome") or os.path.exists("/usr/bin/chromium")


_skip = pytest.mark.skipif(not _have_browser(), reason="no system Chrome / Playwright on this host (CI-gated)")


class _ProgHandler(http.server.BaseHTTPRequestHandler):
    def _send(self, body: bytes, ctype: str) -> None:
        self.send_response(200); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def do_GET(self) -> None:
        p = self.path.split("?", 1)[0]
        if p in ("/", "/program"):
            self._send(open(os.path.join(_WEB, "program.html"), "rb").read(), "text/html")
        elif p == "/program/snapshot":
            self._send(open(_SNAP, "rb").read(), "application/json")
        elif p.startswith("/assets/"):
            fp = os.path.join(_WEB, "assets", os.path.relpath(p[len("/assets/"):]))
            self._send(open(fp, "rb").read(), "application/javascript") if os.path.isfile(fp) else self.send_error(404)
        else:
            self.send_error(404)

    def log_message(self, *a) -> None:
        pass


def _serve(handler, port):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@_skip
def test_cockpit_mobile_command_surface_smoke():  # [REQ:FR-20]
    from web01_csp_smoke import _make_handler, _production_csp
    srv = _serve(_make_handler(_CESIUM, _production_csp()), 8821)
    problems: list[str] = []
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            b = pw.chromium.launch(headless=True, channel="chrome", args=["--use-gl=swiftshader", "--no-sandbox"])
            for w in _WIDTHS:
                pg = b.new_page(viewport={"width": w, "height": 780})
                pg.goto("http://127.0.0.1:8821/", wait_until="domcontentloaded", timeout=40000)
                pg.wait_for_selector("#viewtabs .vtab", timeout=15000)
                pg.eval_on_selector("#editmode", "el => el.click()")   # (c) open the ToolBox
                r = pg.evaluate(r"""(w) => {
                    const out = {overflow: false, toolbar: null, menus: [], under44: []};
                    out.overflow = document.scrollingElement.scrollWidth > w + 1;                 // (a)
                    const tb = document.getElementById('edittoolbar');                            // (c)
                    if (tb) { const b = tb.getBoundingClientRect(); if (b.right > w + 1 || b.left < -1) out.toolbar = Math.round(b.right); }
                    const wa = document.getElementById('whoami'); if (wa) wa.style.display = 'inline-flex';
                    for (const id of ['moremenu','profmenu']) {                                    // (d)
                        const el = document.getElementById(id); if (!el) continue;
                        el.style.display = (id === 'moremenu') ? 'flex' : 'block';
                        const b = el.getBoundingClientRect();
                        if (b.width && (b.left < -1 || b.right > w + 1 || b.bottom > 781)) out.menus.push(id);
                    }
                    for (const sel of ['.vtab','#drawerbtn','#editmode']) {                        // (b)
                        for (const el of document.querySelectorAll(sel)) {
                            const b = el.getBoundingClientRect();
                            if (b.width && b.height && Math.round(b.height) < 44) { out.under44.push(sel + ':' + b.height.toFixed(1)); break; }
                        }
                    }
                    return out;
                }""", w)
                if r["overflow"]:
                    problems.append(f"{w}px: body overflow")
                if r["toolbar"]:
                    problems.append(f"{w}px: ToolBox offscreen right={r['toolbar']}")
                if r["menus"]:
                    problems.append(f"{w}px: menus offscreen {r['menus']}")
                if r["under44"]:
                    problems.append(f"{w}px: controls under 44px {r['under44']}")
                pg.close()
            b.close()
    finally:
        srv.shutdown()
    assert not problems, "cockpit mobile smoke failures:\n  " + "\n  ".join(problems)


@_skip
def test_program_mobile_touch_surface_smoke():  # [REQ:FR-20]
    srv = _serve(_ProgHandler, 8822)
    problems: list[str] = []
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            b = pw.chromium.launch(headless=True, channel="chrome", args=["--use-gl=swiftshader", "--no-sandbox"])
            for w in _WIDTHS:
                pg = b.new_page(viewport={"width": w, "height": 780})
                pg.goto("http://127.0.0.1:8822/program", wait_until="domcontentloaded", timeout=40000)
                pg.wait_for_selector(".rowchip", timeout=15000)
                r = pg.evaluate(r"""(w) => {
                    const out = {overflow: document.scrollingElement.scrollWidth > w + 1, under44: []};
                    for (const sel of ['.fbtn','.rowchip','#program-search']) {
                        for (const el of document.querySelectorAll(sel)) {
                            const b = el.getBoundingClientRect();
                            if (b.width && b.height && Math.round(b.height) < 44) { out.under44.push(sel + ':' + b.height.toFixed(1)); break; }
                        }
                    }
                    return out;
                }""", w)
                if r["overflow"]:
                    problems.append(f"{w}px: /program body overflow")
                if r["under44"]:
                    problems.append(f"{w}px: /program controls under 44px {r['under44']}")
                pg.close()
            b.close()
    finally:
        srv.shutdown()
    assert not problems, "/program mobile smoke failures:\n  " + "\n  ".join(problems)
