"""SEC-01: the operator's session credential lives in an HttpOnly cookie, never in localStorage.

The audit found the cockpit stored the bearer token AND the raw automation key in localStorage, where
any XSS can read and exfiltrate them. The fix moves the browser credential into a server-issued
HttpOnly + SameSite=Strict session cookie, with a readable double-submit CSRF cookie guarding
state-changing routes. This pins the server half of that contract:

  * /auth/login issues stewie_session (HttpOnly, SameSite=Strict) + stewie_csrf (readable),
  * require_auth accepts the session cookie when no explicit auth header is sent (the browser path),
  * a cookie-authenticated state-changing request needs a matching X-CSRF-Token (double submit),
  * an EXPLICIT header credential (Bearer / X-API-Key) still works and stays CSRF-exempt (automation),
  * /auth/logout clears both cookies.

Run: PYTHONPATH=. <venv>/bin/python -m pytest stewie/server/test_auth_cookie.py -q
"""
from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

_BOOTSTRAP = "storeyaw@clarkson.edu"          # an allowlisted founding director (password-less bootstrap)


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_API_KEY", "test-key")
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    import stewie.server.server as srv
    importlib.reload(srv)
    yield TestClient(srv.app)
    monkeypatch.undo()
    importlib.reload(srv)


def _bootstrap_login(client):
    """Sign in the password-less founding director via the shared key -> sets the session cookies."""
    return client.post("/auth/login", json={"email": _BOOTSTRAP}, headers={"X-API-Key": "test-key"})


def _set_cookie_headers(resp):
    # one entry per Set-Cookie (do NOT split on commas -- "expires=Thu, 01 Jan ..." contains commas)
    return [ln.lower() for ln in resp.headers.get_list("set-cookie")]


def test_login_sets_httponly_session_and_readable_csrf_cookies(client):
    r = _bootstrap_login(client)
    assert r.status_code == 200, r.text
    lines = _set_cookie_headers(r)
    session_line = next((ln for ln in lines if ln.startswith("stewie_session=")), None)
    csrf_line = next((ln for ln in lines if ln.startswith("stewie_csrf=")), None)
    assert session_line, "login did not set a session cookie (SEC-01)"
    # the session cookie must be HttpOnly (JS cannot read it) and SameSite=Strict
    assert "httponly" in session_line, "session cookie is not HttpOnly (XSS could read it)"
    assert "samesite=strict" in session_line, "session cookie is not SameSite=Strict"
    # the CSRF cookie must be present and READABLE by JS (NOT HttpOnly) for the double-submit
    assert csrf_line, "login did not set a CSRF cookie"
    assert "httponly" not in csrf_line, "CSRF cookie must be readable by JS (double-submit), not HttpOnly"


def test_require_auth_accepts_the_session_cookie(client):
    """After login the jar holds the session cookie; a GET to a protected route must authenticate from
    it with NO Authorization header (the browser path)."""
    assert _bootstrap_login(client).status_code == 200
    r = client.get("/auth/me")                 # no Authorization header -> cookie must carry the identity
    assert r.status_code == 200, r.text
    assert r.json()["identity"] == _BOOTSTRAP


def test_cookie_post_requires_a_matching_csrf_token(client):
    """A state-changing request authenticated by COOKIE must present X-CSRF-Token == the csrf cookie."""
    assert _bootstrap_login(client).status_code == 200
    csrf = client.cookies.get("stewie_csrf")
    assert csrf, "no CSRF cookie to read"
    # cookie auth, NO csrf header -> rejected
    r_no = client.post("/missions/by-test", json={"body": "moon", "orders": []})
    assert r_no.status_code == 403, f"cookie POST without CSRF was not rejected ({r_no.status_code})"
    # cookie auth, WITH the matching csrf header -> allowed
    r_ok = client.post("/missions/by-test", json={"body": "moon", "orders": []},
                       headers={"X-CSRF-Token": csrf})
    assert r_ok.status_code == 200, r_ok.text
    # a WRONG csrf token is rejected too
    r_bad = client.post("/missions/by-test", json={"body": "moon", "orders": []},
                        headers={"X-CSRF-Token": "not-the-token"})
    assert r_bad.status_code == 403


def test_explicit_header_auth_stays_csrf_exempt(client):
    """An explicit X-API-Key (automation) must authenticate a state-changing route WITHOUT any CSRF
    token -- the attacker cannot set that header cross-site, so CSRF does not apply. A fresh client (no
    cookie jar) proves the header alone carries it."""
    import stewie.server.server as srv
    bare = TestClient(srv.app)                  # no login -> no cookies
    r = bare.post("/missions/by-auto", json={"body": "moon", "orders": []},
                  headers={"X-API-Key": "test-key"})
    assert r.status_code == 200, r.text


def test_logout_clears_both_cookies(client):
    assert _bootstrap_login(client).status_code == 200
    assert client.get("/auth/me").status_code == 200          # signed in via cookie
    r = client.post("/auth/logout")
    assert r.status_code == 200, r.text
    cleared = "\n".join(_set_cookie_headers(r)).lower()
    assert "stewie_session=" in cleared and "stewie_csrf=" in cleared, "logout did not rewrite the cookies"
    # the cleared cookies must be expired (Max-Age=0 or a past expiry)
    assert "max-age=0" in cleared or "expires=thu, 01 jan 1970" in cleared, "logout did not expire the cookies"
    # after the jar drops them, the browser path is no longer authenticated
    client.cookies.clear()
    assert client.get("/auth/me").status_code in (401, 403)
