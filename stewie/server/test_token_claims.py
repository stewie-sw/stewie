"""S-12 regression: token signing is separated from the automation key, and tokens carry
issuer/audience/jti with a revocation mechanism.

The audit found the raw automation credential (STEWIE_API_KEY) was ALSO the HMAC signing key, and
tokens carried only {op, exp} -- no issuer, audience, token id, or revocation. So exposure of the
automation key let anyone mint tokens, rotation killed all sessions at once, and a single compromised
session could not be revoked.

This pins:
 - the session-signing secret is independent of the automation key (rotating the API key does NOT
   invalidate already-issued session tokens),
 - tokens carry iss/aud/jti and are rejected if iss/aud do not match,
 - an individual token can be REVOKED by its jti without disturbing other live sessions.

Run: PYTHONPATH=. <venv>/bin/python -m pytest stewie/server/test_token_claims.py -q
"""
from __future__ import annotations

import importlib

import pytest


@pytest.fixture()
def auth(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_API_KEY", "automation-key-AAAA")
    monkeypatch.setenv("STEWIE_SESSION_SECRET", "session-secret-BBBB")
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWIE_ALLOWED_OPERATORS", "op@example.com,dir@example.com")
    from stewie.server import auth as AUTH
    importlib.reload(AUTH)
    return AUTH


def test_token_signed_with_session_secret_not_the_api_key(auth, monkeypatch):
    """A token issued under the session secret must REMAIN valid after the automation API key is
    rotated -- proving the two secrets are independent (S-12)."""
    tok = auth.issue_token("op@example.com")
    assert auth.verify_token(tok) == "op@example.com"
    # rotate ONLY the automation key; the session token must survive
    monkeypatch.setenv("STEWIE_API_KEY", "automation-key-ROTATED")
    assert auth.verify_token(tok) == "op@example.com", (
        "rotating the automation key invalidated a session token -> the signing key is still the API key (S-12)")


def test_token_carries_iss_aud_jti(auth):
    tok = auth.issue_token("op@example.com")
    claims = auth.decode_claims(tok)
    assert claims["iss"], "token has no issuer (S-12)"
    assert claims["aud"], "token has no audience (S-12)"
    assert claims["jti"], "token has no jti (S-12)"


def test_token_with_wrong_audience_is_rejected(auth, monkeypatch):
    tok = auth.issue_token("op@example.com")
    assert auth.verify_token(tok) == "op@example.com"
    # the server now expects a DIFFERENT audience -> the old token must not verify
    monkeypatch.setenv("STEWIE_TOKEN_AUD", "some-other-audience")
    importlib.reload  # noqa -- aud read live below
    assert auth.verify_token(tok) is None, "a token with a non-matching audience verified (S-12)"


def test_individual_token_can_be_revoked_by_jti(auth):
    tok_a = auth.issue_token("op@example.com")
    tok_b = auth.issue_token("dir@example.com")
    assert auth.verify_token(tok_a) == "op@example.com"
    assert auth.verify_token(tok_b) == "dir@example.com"
    jti_a = auth.decode_claims(tok_a)["jti"]
    auth.revoke_jti(jti_a)
    assert auth.verify_token(tok_a) is None, "a revoked token still verified (S-12)"
    assert auth.verify_token(tok_b) == "dir@example.com", "revoking A also killed B's session (S-12)"
