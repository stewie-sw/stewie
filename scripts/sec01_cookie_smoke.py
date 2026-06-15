#!/usr/bin/env python3
"""SEC-01 browser smoke -- prove the cockpit keeps NO credential in localStorage and authenticates from
the HttpOnly session cookie, in a real browser against a real server.

It drives stewie/server/index.html in headless Chrome and asserts the SEC-01 contract end to end:

  * the one-time migration deletes a legacy bearer token / API key that an older build left in localStorage,
  * after sign-in the readable CSRF cookie exists but the HttpOnly stewie_session cookie is NOT visible to
    document.cookie (XSS cannot read it),
  * localStorage holds NO optoken / apikey,
  * a state-changing request made via the page's apiHeaders() authenticates by COOKIE and carries the
    double-submit X-CSRF-Token (and no X-API-Key), and succeeds.

NOT a CI unit test (needs google-chrome + playwright + a running server, like ui_eval.py). Start a real
server first, then point this at it:
    STEWIE_API_KEY=test-key STEWIE_DATA_DIR=/tmp/sec01 <venv>/bin/python -m uvicorn \
        stewie.server.server:app --host 127.0.0.1 --port 8804
    <venv>/bin/python scripts/sec01_cookie_smoke.py --url http://127.0.0.1:8804
Exits non-zero on any failure.
"""
from __future__ import annotations

import argparse
import json
import sys

_BOOTSTRAP = "storeyaw@clarkson.edu"     # an allowlisted founding director (password-less bootstrap)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8804")
    ap.add_argument("--api-key", default="test-key")
    ap.add_argument("--channel", default="chrome")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright
    fail: list[str] = []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, channel=args.channel,
                              args=["--use-gl=swiftshader", "--no-sandbox"])
        ctx = b.new_context(viewport={"width": 1280, "height": 900})
        # seed a LEGACY localStorage credential blob BEFORE any page script runs (every navigation)
        ctx.add_init_script(
            "try { localStorage.setItem('stewie_settings', JSON.stringify("
            "{optoken:'legacy-token', apikey:'legacy-key', theme:'dark', fontpx:13})); } catch (e) {}")
        pg = ctx.new_page()
        errs: list[str] = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        # the cockpit is index.html: the dev server serves it at "/"; production nginx aliases it at /app
        pg.goto(args.url + "/", wait_until="domcontentloaded", timeout=40000)
        pg.wait_for_function("() => typeof doLogin === 'function' && typeof apiHeaders === 'function'",
                             timeout=15000)

        # 1) the migration must have scrubbed the legacy creds at load
        after_load = pg.evaluate("() => localStorage.getItem('stewie_settings')")
        blob = json.loads(after_load) if after_load else {}
        if "optoken" in blob or "apikey" in blob:
            fail.append(f"migration did NOT scrub legacy creds from localStorage: {blob}")

        # 2) sign in via the REAL client path (bootstrap: in-memory key -> server sets the cookies)
        pg.evaluate(
            "async (key) => { AUTH.apikey = key;"
            "  document.getElementById('auth-email').value = '%s';"
            "  document.getElementById('auth-pass').value = '';"
            "  await doLogin(); }" % _BOOTSTRAP, args.api_key)
        pg.wait_for_timeout(400)

        # 3) the readable CSRF cookie exists; the HttpOnly session cookie is INVISIBLE to JS
        doc_cookie = pg.evaluate("() => document.cookie")
        if "stewie_csrf=" not in doc_cookie:
            fail.append("no readable stewie_csrf cookie after sign-in")
        if "stewie_session=" in doc_cookie:
            fail.append("HttpOnly session cookie is readable by JS (it must NOT be)")

        # 4) localStorage still holds no credential
        stored = pg.evaluate("() => localStorage.getItem('stewie_settings')") or "{}"
        sb = json.loads(stored)
        if "optoken" in sb or "apikey" in sb:
            fail.append(f"credential persisted to localStorage after login: {sb}")

        # 5) a state-changing request via apiHeaders() authenticates by COOKIE + double-submit CSRF
        res = pg.evaluate(
            "async () => { AUTH.apikey = '';"          # drop the in-memory key -> force the cookie path
            "  const h = apiHeaders();"
            "  const r = await fetch('/missions/by-sec01-smoke', {method:'POST', headers: h,"
            "    body: JSON.stringify({body:'moon', orders:[]})});"
            "  return {status: r.status, sentCsrf: !!h['X-CSRF-Token'], sentKey: !!h['X-API-Key']}; }")
        if not res.get("sentCsrf"):
            fail.append("apiHeaders() did not attach X-CSRF-Token on a mutating request")
        if res.get("sentKey"):
            fail.append("apiHeaders() leaked an X-API-Key on the cookie path")
        if res.get("status") != 200:
            fail.append(f"cookie+CSRF mutating request failed: status {res.get('status')}")
        b.close()

    print("page errors:", errs)
    print("checks failed:", fail if fail else "none")
    ok = not fail and not errs
    print("SEC-01 COOKIE SMOKE", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
