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


def test_failed_login_burst_is_rate_limited(client):
    """Sustained failed logins from one IP must hit a 429 once the per-IP window cap is exceeded
    (so the single worker / PBKDF2 cannot be monopolized)."""
    codes = []
    for _ in range(12):
        r = client.post("/auth/login", json={"email": "nobody@example.com", "password": "wrongpassword1"})
        codes.append(r.status_code)
    assert 429 in codes, f"no 429 after a sustained failed-login burst (S-07); saw {codes}"


def test_registration_burst_is_rate_limited(client):
    codes = []
    for i in range(12):
        r = client.post("/auth/register",
                        json={"email": f"user{i}@example.com", "password": "long-enough-password"})
        codes.append(r.status_code)
    assert 429 in codes, f"registration not rate-limited (S-07); saw {codes}"


def test_a_normal_login_attempt_still_works(client):
    """A single well-formed bootstrap login under the cap must still succeed (no false-positive limit)."""
    r = client.post("/auth/login", json={"email": "storeyaw@clarkson.edu"},
                    headers={"X-API-Key": "test-key"})
    assert r.status_code == 200, r.text
