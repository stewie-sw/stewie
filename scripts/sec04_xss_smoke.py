#!/usr/bin/env python3
"""SEC-04 browser smoke -- prove the cockpit's server-derived innerHTML sinks do NOT execute injected
HTML/JS, in a real browser.

The audit flagged several `innerHTML = ...` sinks that interpolate server-returned strings (profile
names the operator chose, the figure/site/vehicle/tool/soil labels from the API). A value like
`<img src=x onerror=...>` must render as INERT TEXT, never a live element that runs script.

This drives the real render paths in headless Chrome with a poisoned server payload and asserts:
  * no injected onerror/onload handler ever fires (a window sentinel stays 0),
  * no <img>/<svg> element from the payload appears in the DOM (it was escaped to text),
  * the rendered option text equals the literal payload string.

NOT a CI unit test (needs google-chrome + playwright + a running server, like ui_eval.py). Run a real
server first, then point this at it:
    STEWIE_API_KEY=test-key STEWIE_DATA_DIR=/tmp/sec04 <venv>/bin/python -m uvicorn \
        stewie.server.server:app --host 127.0.0.1 --port 8806
    <venv>/bin/python scripts/sec04_xss_smoke.py --url http://127.0.0.1:8806
Exits non-zero on any failure.
"""
from __future__ import annotations

import argparse
import sys

_PAYLOAD = "<img src=x onerror=\"window.__XSS=(window.__XSS||0)+1\">"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8806")
    ap.add_argument("--channel", default="chrome")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright
    fail: list[str] = []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, channel=args.channel,
                              args=["--use-gl=swiftshader", "--no-sandbox"])
        pg = b.new_page(viewport={"width": 1280, "height": 900})
        errs: list[str] = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(args.url + "/", wait_until="domcontentloaded", timeout=40000)
        pg.wait_for_function("() => typeof refreshProfiles === 'function' && "
                             "typeof populateFleet === 'function'", timeout=15000)

        # drive the real render paths with a poisoned payload, then let any onerror fire
        result = pg.evaluate(
            """async (payload) => {
                window.__XSS = 0;
                const orig = window.fetch;
                window.fetch = async (u, o) => {
                  const url = typeof u === 'string' ? u : (u && u.url) || '';
                  if (url === '/profiles')
                    return new Response(JSON.stringify({ok:true, profiles:[payload]}),
                                        {headers:{'Content-Type':'application/json'}});
                  return orig(u, o);
                };
                await refreshProfiles();                         // user-named profile sink
                // server-derived fleet sinks (vehicles / tools / soils)
                PHY = {_vehicles:{evil:{label:payload}}, _tools:{t:{label:payload}}, poison:{label:payload}};
                populateFleet();
                return new Promise((res) => setTimeout(() => {
                  const prof = document.querySelector('#profload option');
                  res({
                    xss: window.__XSS,
                    injectedImgs: document.querySelectorAll('img[src=\\"x\\"]').length,
                    profText: prof ? prof.textContent : null,
                  });
                }, 400));
            }""", _PAYLOAD)

        b.close()

    if result["xss"]:
        fail.append(f"injected onerror FIRED {result['xss']}x -- a sink executed server HTML (XSS)")
    if result["injectedImgs"]:
        fail.append(f"{result['injectedImgs']} injected <img> element(s) entered the DOM (not escaped)")
    if result["profText"] != _PAYLOAD:
        fail.append(f"profile option text was not the literal payload: {result['profText']!r}")
    if errs:
        fail.append(f"page errors: {errs[:3]}")

    print("result:", result)
    print("checks failed:", fail if fail else "none")
    ok = not fail
    print("SEC-04 XSS SMOKE", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
