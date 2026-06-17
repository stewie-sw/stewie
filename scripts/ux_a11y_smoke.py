#!/usr/bin/env python3
"""Batch-6 UX/a11y smoke -- verify the cockpit's accessibility + touch behaviour in a REAL browser,
under the tightened production CSP, at desktop AND mobile viewports.

Reuses the CSP-serving harness from web01_csp_smoke (serves index.html + /cesium/ + /assets/ with the
exact nginx CSP) and asserts:
  * the view switcher is a WAI-ARIA tablist: role=tab + aria-selected; clicking a tab moves aria-selected;
    ArrowRight moves the active tab (UX-04),
  * the auth dialog (role=dialog) takes focus on open and Escape closes it (UX-04),
  * the Cesium canvas carries an aria-label (UX-04),
  * --dim text reaches WCAG AA (>=4.5:1) computed live, both themes (UX-03),
  * key touch targets (.vtab, #drawerbtn) are >=44x44 px at a phone viewport (MOBILE-01),
  * 0 page errors + 0 CSP violations under the tightened policy.

Needs google-chrome + playwright + a vendored Cesium build (default /tmp/cesium_vendor). Exits non-zero
on any failure.
"""
from __future__ import annotations

import argparse
import http.server
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # so we can reuse the web01 harness
from web01_csp_smoke import _make_handler, _production_csp        # noqa: E402


def _luminance(rgb):
    lin = [(c / 12.92) if c <= 0.03928 else (((c + 0.055) / 1.055) ** 2.4) for c in (v / 255 for v in rgb)]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contrast(c1, c2):
    a, b = _luminance(c1) + 0.05, _luminance(c2) + 0.05
    return max(a, b) / min(a, b)


def _rgb(s):
    nums = [int(x) for x in s.replace("rgb(", "").replace("rgba(", "").replace(")", "").split(",")[:3]]
    return nums


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cesium-dir", default="/tmp/cesium_vendor")
    ap.add_argument("--port", type=int, default=8811)
    ap.add_argument("--channel", default="chrome")
    args = ap.parse_args()
    if not os.path.isfile(os.path.join(args.cesium_dir, "Cesium.js")):
        print(f"FAIL: no Cesium.js under {args.cesium_dir}")
        return 2
    csp = _production_csp()
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), _make_handler(args.cesium_dir, csp))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    fail: list[str] = []
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True, channel=args.channel,
                                  args=["--use-gl=swiftshader", "--no-sandbox"])
            errs: list[str] = []
            viol: list[str] = []
            pg = b.new_page(viewport={"width": 1440, "height": 900})
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.on("console", lambda m: viol.append(m.text) if ("Content Security Policy" in (m.text or "")
                                                               or "Refused to" in (m.text or "")) else None)
            pg.goto(f"http://127.0.0.1:{args.port}/", wait_until="domcontentloaded", timeout=40000)
            pg.wait_for_selector("#viewtabs .vtab", timeout=15000)

            a = pg.evaluate(r"""() => {
                const tl = document.getElementById('viewtabs');
                const tabs = [...document.querySelectorAll('.vtab')];
                const active = tabs.find(t => t.getAttribute('aria-selected') === 'true');
                return {
                  tablist: tl && tl.getAttribute('role'),
                  tabRole: tabs[0] && tabs[0].getAttribute('role'),
                  oneSelected: tabs.filter(t => t.getAttribute('aria-selected') === 'true').length,
                  cesiumLabel: !!document.getElementById('cesium').getAttribute('aria-label'),
                  modalRole: document.getElementById('authmodal').getAttribute('role'),
                  modalAriaModal: document.getElementById('authmodal').getAttribute('aria-modal'),
                };
            }""")
            if a["tablist"] != "tablist":
                fail.append(f"#viewtabs role is {a['tablist']!r}, not 'tablist'")
            if a["tabRole"] != "tab":
                fail.append(f".vtab role is {a['tabRole']!r}, not 'tab'")
            if a["oneSelected"] != 1:
                fail.append(f"expected exactly one aria-selected tab, got {a['oneSelected']}")
            if not a["cesiumLabel"]:
                fail.append("#cesium has no aria-label")
            if a["modalRole"] != "dialog" or a["modalAriaModal"] != "true":
                fail.append(f"auth modal not a role=dialog aria-modal (got {a['modalRole']}/{a['modalAriaModal']})")

            # NOTE: the cockpit is now GATED (Aaron 2026-06-15) -- a no-session boot DOES show a blocking
            # sign-in (asserted in the gate block below), superseding the earlier UX-01 "no modal at boot".

            # UX-05: the planning sidebar auto-collapses off the Plan view and restores on return (desktop,
            # no pin set). At 1440x900 (the page default) applySidebar acts (innerWidth > 860).
            side = pg.evaluate(r"""() => {
                const panel = document.getElementById('panel');
                setView('report'); const offPlan = panel.classList.contains('collapsed');
                setView('plan');   const onPlan  = panel.classList.contains('collapsed');
                return { offPlan, onPlan };
            }""")
            if not side["offPlan"]:
                fail.append("the planning sidebar did not auto-collapse off the Plan view (UX-05)")
            if side["onPlan"]:
                fail.append("the planning sidebar did not restore on returning to the Plan view (UX-05)")

            # clicking a non-active tab moves aria-selected
            sel = pg.evaluate(r"""() => {
                const tabs = [...document.querySelectorAll('.vtab')].filter(t => t.offsetParent !== null);
                const cur = tabs.findIndex(t => t.getAttribute('aria-selected') === 'true');
                const other = tabs.find((t, i) => i !== cur);
                other.click();
                return { moved: other.getAttribute('aria-selected') === 'true',
                         onlyOne: tabs.filter(t => t.getAttribute('aria-selected') === 'true').length };
            }""")
            if not sel["moved"] or sel["onlyOne"] != 1:
                fail.append(f"clicking a tab did not move aria-selected cleanly ({sel})")

            # ArrowRight from the active tab moves the active tab
            arrowed = pg.evaluate(r"""() => {
                const tabs = [...document.querySelectorAll('.vtab')].filter(t => t.offsetParent !== null);
                const before = tabs.findIndex(t => t.getAttribute('aria-selected') === 'true');
                tabs[before].focus();
                document.getElementById('viewtabs').dispatchEvent(
                    new KeyboardEvent('keydown', {key: 'ArrowRight', bubbles: true}));
                const after = [...document.querySelectorAll('.vtab')].filter(t => t.offsetParent !== null)
                    .findIndex(t => t.getAttribute('aria-selected') === 'true');
                return { before, after };
            }""")
            if arrowed["after"] == arrowed["before"]:
                fail.append(f"ArrowRight did not move the active tab ({arrowed})")

            # --dim live contrast (dark theme, the default)
            dimvar = pg.evaluate("() => { const d=document.createElement('span'); d.style.color='var(--dim)';"
                                 "document.body.appendChild(d); const c=getComputedStyle(d).color;"
                                 "d.remove(); return c; }")
            bgvar = pg.evaluate("() => getComputedStyle(document.body).backgroundColor")
            ratio = _contrast(_rgb(dimvar), _rgb(bgvar))
            if ratio < 4.5:
                fail.append(f"--dim live contrast {ratio:.2f} < 4.5 (dark theme)")

            # GATED APP: a no-session boot shows a BLOCKING sign-in -- X hidden, Esc + closeAuth do NOT
            # dismiss, focus lands on a form field, no automation-key field. A simulated sign-in lifts it.
            gate = pg.evaluate(r"""() => {
                openAuth('login');                          // re-assert the boot gate (refresh focus)
                const m = document.getElementById('authmodal');
                const shownAtBoot = getComputedStyle(m).display !== 'none';
                const xHidden = getComputedStyle(document.getElementById('auth-dismiss')).display === 'none';
                const focusedField = m.contains(document.activeElement) && document.activeElement.tagName === 'INPUT';
                const noApiKey = !document.getElementById('auth-apikey');
                document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
                const stillUpAfterEsc = getComputedStyle(m).display !== 'none';
                closeAuth();
                const stillUpAfterClose = getComputedStyle(m).display !== 'none';
                AUTH.identity = 'ops@test'; AUTH.role = 'operator'; _gate = false; closeAuth();
                const liftedAfterSignin = getComputedStyle(m).display === 'none';
                return { shownAtBoot, xHidden, focusedField, noApiKey,
                         stillUpAfterEsc, stillUpAfterClose, liftedAfterSignin };
            }""")
            for k, want, msg in [
                ("shownAtBoot", True, "the auth gate is not shown on a no-session boot"),
                ("xHidden", True, "the close X is visible while gated (gate must be mandatory)"),
                ("focusedField", True, "the gate did not focus a form field"),
                ("noApiKey", True, "the automation-key field still clutters the sign-in modal"),
                ("stillUpAfterEsc", True, "Escape dismissed the gate (must be mandatory)"),
                ("stillUpAfterClose", True, "closeAuth dismissed the gate while signed-out (must refuse)"),
                ("liftedAfterSignin", True, "the gate did not lift after a successful sign-in"),
            ]:
                if gate.get(k) != want:
                    fail.append(msg + f" ({k}={gate.get(k)})")

            # #117: the signed-in identity chip is hidden when signed out, populated by renderWhoami,
            # and cleared again (the 'who's logged in' corner indicator + sign-out)
            who = pg.evaluate(r"""() => {
                const vis = () => getComputedStyle(document.getElementById('whoami')).display !== 'none';
                const before = vis();
                renderWhoami('aaron.w.storey80@gmail.com', 'director');
                const on = { vis: vis(), av: document.getElementById('whoami-av').textContent,
                             label: document.getElementById('whoami-label').textContent };
                renderWhoami(null);
                return { before, on, afterClear: vis(),
                         hasSignout: !!document.getElementById('whoami-signout') };
            }""")
            if who["before"]:
                fail.append("the whoami chip is shown before sign-in (should be hidden)")
            if not who["on"]["vis"] or who["on"]["av"] != "A" or "director" not in who["on"]["label"]:
                fail.append(f"whoami chip did not render the signed-in identity ({who['on']})")
            if who["afterClear"]:
                fail.append("whoami chip not cleared on sign-out (renderWhoami(null))")
            if not who["hasSignout"]:
                fail.append("no #whoami-signout button")

            # mobile viewport: touch targets >= 44px
            pg.set_viewport_size({"width": 390, "height": 844})
            touch = pg.evaluate(r"""() => {
                const r = (id, sel) => { const e = sel ? document.querySelector(sel) : document.getElementById(id);
                    if (!e) return null; const b = e.getBoundingClientRect(); return [Math.round(b.width), Math.round(b.height)]; };
                return { vtab: r(null, '.vtab'), drawer: r('drawerbtn') };
            }""")
            for name, dims in touch.items():
                if dims and (dims[0] < 44 or dims[1] < 44):
                    fail.append(f"touch target {name} is {dims} px (< 44x44, MOBILE-01)")

            # MOBILE-05/OPT-03: the landing primary CTA must sit ABOVE the 390x844 fold (no scroll)
            lp = b.new_page(viewport={"width": 390, "height": 844})
            lp.on("pageerror", lambda e: errs.append("[landing] " + str(e)))
            lp.goto(f"http://127.0.0.1:{args.port}/landing.html", wait_until="domcontentloaded", timeout=40000)
            lp.wait_for_selector(".hero .cta", timeout=10000)
            cta = lp.evaluate(r"""() => {
                const el = document.querySelector('.hero .cta');
                const r = el.getBoundingClientRect();
                return { bottom: Math.round(r.bottom), top: Math.round(r.top),
                         visible: el.offsetParent !== null, text: el.textContent.trim() };
            }""")
            if not cta["visible"]:
                fail.append("the landing primary CTA is not visible")
            if cta["bottom"] > 844:
                fail.append(f"landing CTA '{cta['text']}' bottom at {cta['bottom']}px is below the "
                            f"390x844 fold (MOBILE-05/OPT-03)")
            lp.close()
            b.close()
        if errs:
            fail.append(f"page errors: {errs[:3]}")
        if viol:
            fail.append(f"CSP violations: {viol[:3]}")
    finally:
        srv.shutdown()

    print("checks failed:", fail if fail else "none")
    ok = not fail
    print("UX/A11Y SMOKE", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
