"""Security regression tests (server/security audit S-01, S-02, S-04, S-11).

Each test pins a concrete vulnerability the audit found and proves the fix:
 - S-01 cross-identity bootstrap escalation: an operator token must NOT be able to mint a token
   for a DIFFERENT (esp. director) identity via the password-less legacy bootstrap.
 - S-02 email-validator XSS surface: the validator must reject HTML/control metacharacters and
   over-long input while still accepting a normal address.
 - S-04 plaintext-HTTP startup guard: a non-loopback bind without a declared TLS terminator is
   refused (code-testable half of the otherwise config-only finding).
 - S-11 weak CORS / missing security headers: same-origin by default (no wildcard ACAO unless an
   explicit origin list is configured) and the baseline hardening headers are present.

Run: PYTHONPATH=. <venv>/bin/python -m pytest stewie/server/test_security.py -q
"""
from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


# --------------------------------------------------------------------------------------------------
# S-02 -- the email validator is the testable core (operators._validate_new / register).
# --------------------------------------------------------------------------------------------------
@pytest.fixture()
def ops(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    from stewie.server import operators as OPS
    importlib.reload(OPS)
    return OPS


def test_email_validator_rejects_html_xss_payload(ops):
    # the exact payload the audit smuggled past the old `non-space text around '@'` check
    with pytest.raises(ValueError):
        ops.register("<img/src=x/onerror=alert(1)>@x.co", "long-enough-password")


def test_email_validator_rejects_html_metacharacters(ops):
    for bad in ('a<b@x.co', 'a>b@x.co', 'a"b@x.co', "a'b@x.co", 'a&b@x.co', 'a;b@x.co',
                'a/b@x.co', 'a\\b@x.co', 'a\x00b@x.co', 'a\tb@x.co'):
        with pytest.raises(ValueError):
            ops.register(bad, "long-enough-password")


def test_email_validator_rejects_overlong_input(ops):
    huge = ("a" * 300) + "@x.co"          # well past any sane local/total length
    with pytest.raises(ValueError):
        ops.register(huge, "long-enough-password")


def test_email_validator_accepts_a_normal_address(ops):
    rec = ops.register("Normal.User+tag@Example.com", "long-enough-password")
    assert rec["email"] == "normal.user+tag@example.com"   # normalized, accepted


# --------------------------------------------------------------------------------------------------
# S-01 -- the cross-identity bootstrap escalation.
# --------------------------------------------------------------------------------------------------
@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_API_KEY", "test-key")
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    import stewie.server.server as srv
    importlib.reload(srv)
    yield TestClient(srv.app)
    monkeypatch.undo()
    importlib.reload(srv)


def test_bootstrap_token_cannot_mint_a_different_identity(client):
    """An authenticated operator (a valid session token for identity A) must NOT be able to use the
    password-less legacy bootstrap to obtain a token for a DIFFERENT identity B (here, a director).
    Before the fix, _legacy_authed accepted any valid token regardless of the requested email."""
    # operator A logs in via the legacy shared-key bootstrap (A == requested email -> allowed)
    a = client.post("/auth/login", json={"email": "storeyaw@clarkson.edu"},
                    headers={"X-API-Key": "test-key"})
    assert a.status_code == 200
    tok_a = a.json()["token"]
    # A now presents its own valid token but requests a DIFFERENT allowlisted (director) email
    r = client.post("/auth/login", json={"email": "mccardle.john@gmail.com"},
                    headers={"Authorization": f"Bearer {tok_a}"})
    assert r.status_code in (401, 403), (
        f"cross-identity bootstrap escalation: got {r.status_code} {r.json()}")


def test_bootstrap_same_subject_token_still_works_once(client):
    """The legitimate path: presenting a valid token whose subject EQUALS the requested email is the
    self-enrollment case and must still succeed (so a director is not locked out mid-migration)."""
    a = client.post("/auth/login", json={"email": "storeyaw@clarkson.edu"},
                    headers={"X-API-Key": "test-key"})
    tok_a = a.json()["token"]
    r = client.post("/auth/login", json={"email": "storeyaw@clarkson.edu"},
                    headers={"Authorization": f"Bearer {tok_a}"})
    assert r.status_code == 200 and r.json()["operator"] == "storeyaw@clarkson.edu"


def test_bootstrap_shared_key_still_binds_only_to_the_requested_email(client):
    """The raw shared key still bootstraps, but only for the requested allowlisted email itself --
    the key carries no subject of its own, so any allowlisted email is the holder's to claim. This
    is the unchanged automation/founding-director path; it must keep working."""
    r = client.post("/auth/login", json={"email": "aaron.w.storey80@gmail.com"},
                    headers={"X-API-Key": "test-key"})
    assert r.status_code == 200 and r.json()["operator"] == "aaron.w.storey80@gmail.com"


def test_bootstrap_tailscale_must_match_requested_email(client, monkeypatch):
    """A trusted Tailscale identity may only bootstrap ITS OWN email, not an arbitrary other one."""
    monkeypatch.setenv("STEWIE_TRUST_TAILSCALE", "1")
    # Tailscale identity B requests a DIFFERENT email A -> refused
    r = client.post("/auth/login", json={"email": "storeyaw@clarkson.edu"},
                    headers={"Tailscale-User-Login": "mccardle.john@gmail.com"})
    assert r.status_code in (401, 403)
    # Tailscale identity requesting its OWN email -> allowed
    ok = client.post("/auth/login", json={"email": "mccardle.john@gmail.com"},
                     headers={"Tailscale-User-Login": "mccardle.john@gmail.com"})
    assert ok.status_code == 200 and ok.json()["operator"] == "mccardle.john@gmail.com"


# --------------------------------------------------------------------------------------------------
# S-11 -- CORS default + security headers.
# --------------------------------------------------------------------------------------------------
def test_cors_does_not_default_to_wildcard(monkeypatch, tmp_path):
    """With no explicit STEWIE_CORS_ORIGINS, a cross-origin request must NOT receive a wildcard
    Access-Control-Allow-Origin (same-origin by default)."""
    monkeypatch.delenv("STEWIE_CORS_ORIGINS", raising=False)
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    import stewie.server.server as srv
    importlib.reload(srv)
    c = TestClient(srv.app)
    r = c.get("/healthz", headers={"origin": "http://evil.example"})
    acao = r.headers.get("access-control-allow-origin")
    assert acao != "*", "CORS still defaults to wildcard '*' (S-11)"
    monkeypatch.undo()
    importlib.reload(srv)


def test_cors_honors_an_explicit_allowlist(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_CORS_ORIGINS", "https://stewie.space")
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    import stewie.server.server as srv
    importlib.reload(srv)
    c = TestClient(srv.app)
    ok = c.get("/healthz", headers={"origin": "https://stewie.space"})
    assert ok.headers.get("access-control-allow-origin") == "https://stewie.space"
    bad = c.get("/healthz", headers={"origin": "https://evil.example"})
    assert bad.headers.get("access-control-allow-origin") != "https://evil.example"
    monkeypatch.undo()
    importlib.reload(srv)


def test_security_headers_present(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    import stewie.server.server as srv
    importlib.reload(srv)
    c = TestClient(srv.app)
    r = c.get("/healthz")
    hdrs = {k.lower(): v for k, v in r.headers.items()}
    assert hdrs.get("x-content-type-options") == "nosniff"
    assert "referrer-policy" in hdrs
    assert "permissions-policy" in hdrs
    monkeypatch.undo()
    importlib.reload(srv)


# --------------------------------------------------------------------------------------------------
# S-04 -- plaintext-HTTP / non-loopback TLS startup guard.
# --------------------------------------------------------------------------------------------------
def test_nonloopback_bind_without_tls_is_refused(monkeypatch):
    """Binding to a non-loopback address in production without declaring a TLS terminator must be
    refused (fail-closed). Loopback binds and an explicit STEWIE_TLS_TERMINATED=1 are allowed."""
    import stewie.server.server as srv
    importlib.reload(srv)
    monkeypatch.delenv("STEWIE_TLS_TERMINATED", raising=False)
    monkeypatch.delenv("STEWIE_DEV_OPEN", raising=False)
    with pytest.raises(SystemExit):
        srv._require_tls_for_public_bind("0.0.0.0")
    # loopback is fine
    srv._require_tls_for_public_bind("127.0.0.1")
    # an explicit TLS-terminated declaration unlocks a public bind
    monkeypatch.setenv("STEWIE_TLS_TERMINATED", "1")
    srv._require_tls_for_public_bind("0.0.0.0")
    monkeypatch.undo()
