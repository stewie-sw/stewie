"""S-07 regression: login/registration must use typed request models with conservative field caps
and per-IP / per-account rate limits.

The audit found /auth/login and /auth/register accepted raw dicts with no length limits and no rate
limit, so a client could send multi-megabyte passwords (PBKDF2 then burns CPU on attacker-sized input)
and hammer the single worker with unbounded failed-login / registration bursts.

This pins:
 - an over-long password is rejected with a 4xx BEFORE the expensive PBKDF2 path,
 - an over-long email is rejected with a 4xx,
 - sustained failed logins from one IP are rate-limited (HTTP 429) rather than served unboundedly,
 - registration is rate-limited per IP.

Run: PYTHONPATH=. <venv>/bin/python -m pytest stewie/server/test_auth_limits.py -q
"""
from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_API_KEY", "test-key")
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    # keep the rate limits small + fast for the test
    monkeypatch.setenv("STEWIE_AUTH_RATE_MAX", "5")
    monkeypatch.setenv("STEWIE_AUTH_RATE_WINDOW_S", "60")
    # SEC-06: registration now defaults CLOSED -- make the closed default deterministic for these tests
    # (any inherited STEWIE_REGISTRATION is removed; tests that need it open set it explicitly)
    monkeypatch.delenv("STEWIE_REGISTRATION", raising=False)
    import stewie.server.server as srv
    importlib.reload(srv)
    # reset the in-process limiter so other tests don't bleed counts in
    from stewie.server.routers import auth as authr
    importlib.reload(authr)
    yield TestClient(srv.app)
    monkeypatch.undo()
    importlib.reload(srv)


def test_overlong_password_rejected_before_hashing(client):
    """A several-megabyte password must be refused by the typed model (4xx), not fed to PBKDF2."""
    huge = "x" * 5000
    r = client.post("/auth/login", json={"email": "op@example.com", "password": huge})
    assert r.status_code in (400, 413, 422), f"over-long password accepted ({r.status_code})"


def test_overlong_email_rejected(client):
    huge_email = ("a" * 5000) + "@x.co"
    r = client.post("/auth/register", json={"email": huge_email, "password": "long-enough-password"})
    assert r.status_code in (400, 413, 422), f"over-long email accepted ({r.status_code})"


def test_failed_login_burst_is_rate_limited(client):  # [REQ:FS-11]
    """Sustained failed logins from one IP must hit a 429 once the per-IP window cap is exceeded
    (so the single worker / PBKDF2 cannot be monopolized). This is the FS-11 assertion that rate
    limiting is WIRED on the auth-sensitive routes: /auth/login consults the per-IP + per-account
    RateLimiters (routers/auth.py) and maps an exceeded window to HTTP 429; /auth/register is pinned
    by test_registration_burst_is_rate_limited below."""
    codes = []
    for _ in range(12):
        r = client.post("/auth/login", json={"email": "nobody@example.com", "password": "wrongpassword1"})
        codes.append(r.status_code)
    assert 429 in codes, f"no 429 after a sustained failed-login burst (S-07); saw {codes}"


@pytest.mark.parametrize("hdr", [
    {"Authorization": "Bearer not-a-real-token"},   # a forged bearer must NOT exempt the limiter
    {"X-API-Key": "not-the-key"},                    # nor a wrong api-key value
])
def test_forged_credential_header_does_not_bypass_login_limit(client, hdr):
    """#270: the rate-limit exemption keyed on the mere PRESENCE of an Authorization/X-API-Key header, so a
    forged header skipped the per-IP/per-account limiter and the failed-PASSWORD burst still reached PBKDF2
    -- re-opening the exact DoS / brute-force S-07 closed. A password submission must be limited regardless
    of headers; only the password-LESS key bootstrap stays exempt (the next test)."""
    codes = []
    for _ in range(12):
        r = client.post("/auth/login",
                        json={"email": "nobody@example.com", "password": "wrongpassword1"}, headers=hdr)
        codes.append(r.status_code)
    assert 429 in codes, f"forged {list(hdr)[0]} bypassed the login limiter (#270); saw {codes}"


def test_passwordless_apikey_bootstrap_stays_exempt(client):
    """#270 regression: the password-LESS automation/API-key bootstrap stays exempt (a bounded constant-time
    key check; CI must not 429). Hammering it stays 200, never 429 -- the fix limits only the password path."""
    codes = []
    for _ in range(12):
        r = client.post("/auth/login", json={"email": "storeyaw@clarkson.edu"},
                        headers={"X-API-Key": "test-key"})
        codes.append(r.status_code)
    assert 429 not in codes and codes.count(200) == 12, f"bootstrap wrongly rate-limited (#270); saw {codes}"


def test_registration_burst_is_rate_limited(client, monkeypatch):
    # the per-IP limiter only fires on the OPEN path; closed registration 403s before the limiter (SEC-06)
    monkeypatch.setenv("STEWIE_REGISTRATION", "1")
    codes = []
    for i in range(12):
        r = client.post("/auth/register",
                        json={"email": f"user{i}@example.com", "password": "long-enough-password"})
        codes.append(r.status_code)
    assert 429 in codes, f"registration not rate-limited (S-07); saw {codes}"


def test_registration_defaults_closed_in_production(client):
    """SEC-06: an internet-facing deployment must NOT silently accept self-service registration. With
    STEWIE_REGISTRATION unset, a well-formed /auth/register must be refused (403 'registration is closed'),
    not create a pending account -- the prior `!= "0"` default left enrollment OPEN unless explicitly
    disabled, the wrong fail-direction for a public host. Operators turn it on with STEWIE_REGISTRATION=1."""
    r = client.post("/auth/register",
                    json={"email": "stranger@example.com", "password": "long-enough-password"})
    assert r.status_code == 403, f"registration open by default (SEC-06); got {r.status_code}: {r.text}"
    assert "closed" in r.text.lower()


def test_registration_opt_in_opens_it(client, monkeypatch):
    """The opt-in must actually work: with STEWIE_REGISTRATION=1 a first well-formed request is accepted
    (creates a director-approval-pending account), proving the gate is the only thing closing it."""
    monkeypatch.setenv("STEWIE_REGISTRATION", "1")
    r = client.post("/auth/register",
                    json={"email": "newop@example.com", "password": "long-enough-password"})
    assert r.status_code == 200, r.text
    assert r.json().get("ok") is True


def test_a_normal_login_attempt_still_works(client):
    """A single well-formed bootstrap login under the cap must still succeed (no false-positive limit)."""
    r = client.post("/auth/login", json={"email": "storeyaw@clarkson.edu"},
                    headers={"X-API-Key": "test-key"})
    assert r.status_code == 200, r.text
