"""[REQ:BP-03] Production requires a standalone session-signing secret. Without STEWIE_SESSION_SECRET the
session key is DERIVED from STEWIE_API_KEY, so an API-key rotation silently kills every live session;
production (STEWIE_TLS_TERMINATED=1) must fail LOUD at startup, and the two secrets must rotate independently."""
import pytest


def _auth(monkeypatch, tmp_path, *, api_key="A", session_secret=None, tls=False):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))          # isolate the revocation store
    monkeypatch.setenv("STEWIE_API_KEY", api_key)
    if session_secret is None:
        monkeypatch.delenv("STEWIE_SESSION_SECRET", raising=False)
    else:
        monkeypatch.setenv("STEWIE_SESSION_SECRET", session_secret)
    if tls:
        monkeypatch.setenv("STEWIE_TLS_TERMINATED", "1")
    else:
        monkeypatch.delenv("STEWIE_TLS_TERMINATED", raising=False)
    from stewie.server import auth              # reads env at call time -> cached module is fine
    return auth


def test_bp03_prod_without_session_secret_fails_loud(monkeypatch, tmp_path):  # [REQ:BP-03]
    auth = _auth(monkeypatch, tmp_path, session_secret=None, tls=True)        # production, derived key
    assert auth.session_secret_is_derived() is True
    with pytest.raises(RuntimeError, match="STEWIE_SESSION_SECRET"):
        auth.require_session_secret_for_prod()


def test_bp03_prod_with_session_secret_boots(monkeypatch, tmp_path):  # [REQ:BP-03]
    auth = _auth(monkeypatch, tmp_path, session_secret="s3ssion-secret", tls=True)
    assert auth.session_secret_is_derived() is False
    auth.require_session_secret_for_prod()                                    # no raise


def test_bp03_dev_without_secret_only_warns(monkeypatch, tmp_path):  # [REQ:BP-03]
    auth = _auth(monkeypatch, tmp_path, session_secret=None, tls=False)       # not production
    auth.require_session_secret_for_prod()                                    # no raise (warns)


def test_bp03_api_key_rotation_does_not_invalidate_sessions(monkeypatch, tmp_path):  # [REQ:BP-03]
    # with a standalone session secret, rotating STEWIE_API_KEY leaves the session SIGNATURE valid
    # (decode_claims isolates the signing check from the allowlist -- BP-03 is about the signing secret).
    auth = _auth(monkeypatch, tmp_path, api_key="A", session_secret="fixed-session-secret")
    tok = auth.issue_token("op@x.com")
    assert auth.decode_claims(tok)["op"] == "op@x.com"                        # signature verifies
    monkeypatch.setenv("STEWIE_API_KEY", "B")                                 # rotate the automation key
    assert auth.decode_claims(tok) is not None                              # signature STILL verifies
    assert auth.decode_claims(tok)["op"] == "op@x.com"                       # session UNAFFECTED


def test_bp03_session_secret_rotation_does_invalidate_sessions(monkeypatch, tmp_path):  # [REQ:BP-03]
    # rotating the SESSION secret DOES break the signature -> live sessions invalidated (separate effect).
    auth = _auth(monkeypatch, tmp_path, api_key="A", session_secret="secret-one")
    tok = auth.issue_token("op2@x.com")
    assert auth.decode_claims(tok) is not None                              # signed with secret-one
    monkeypatch.setenv("STEWIE_SESSION_SECRET", "secret-two")                 # rotate the session secret
    assert auth.decode_claims(tok) is None                                  # signature no longer verifies
