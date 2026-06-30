"""SEC-02 regression: the session-revocation store must FAIL CLOSED on corruption.

The audit found `auth._revoked_set()` returned an EMPTY set on any JSON/IO error, so verify_token's
revocation gate `jti in _revoked_set()` silently became "nothing is revoked" -- a revoked session
token would be ACCEPTED again (fail OPEN) the moment the revocation file was corrupt or unreadable.

Fix verified here:
 - an ABSENT store is the normal no-revocations state (a clean deploy still works),
 - a present-but-CORRUPT store makes verify_token DENY the token (fail closed) and flips a visible
   degraded health flag + writes an audit event (the degradation is observable, not silent),
 - revoke_jti will NOT overwrite a corrupt store (which would silently drop existing revocations).

Run: PYTHONPATH=. <venv>/bin/python -m pytest stewie/server/test_revocation_failclosed.py -q
"""
from __future__ import annotations

import importlib
import os

import pytest

_DIRECTOR = "storeyaw@clarkson.edu"          # an allowlisted founding director


@pytest.fixture()
def auth(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWIE_API_KEY", "test-key")        # gives a signing secret + automation key
    from stewie.server import services as SVC
    importlib.reload(SVC)
    from stewie.server import auth as AUTH
    importlib.reload(AUTH)
    SVC.reset_revocation_health()
    return AUTH


def _store_path(tmp_path):
    return os.path.join(str(tmp_path), "revoked_jti.json")


def test_absent_store_is_no_revocations(auth):
    """No revocation file at all = nothing revoked. A freshly issued token verifies."""
    tok = auth.issue_token(_DIRECTOR)
    assert auth.verify_token(tok) == _DIRECTOR


def test_valid_store_revokes_its_token(auth):
    """The happy path still works: revoking a token's jti makes verify_token reject it."""
    tok = auth.issue_token(_DIRECTOR)
    assert auth.verify_token(tok) == _DIRECTOR
    jti = auth.decode_claims(tok)["jti"]
    auth.revoke_jti(jti)
    assert auth.verify_token(tok) is None                   # revoked -> denied


def test_corrupt_store_fails_closed_and_records_degraded(auth, tmp_path, monkeypatch):
    """A CORRUPT revocation store must DENY an otherwise-valid token (fail closed), not accept it, and
    the degradation must be observable in the revocation health + the audit trail."""
    from stewie.server import services as SVC
    tok = auth.issue_token(_DIRECTOR)
    assert auth.verify_token(tok) == _DIRECTOR              # valid before corruption
    with open(_store_path(tmp_path), "w") as f:
        f.write('{ this is not valid json ]')              # corrupt -> unreadable
    assert auth.verify_token(tok) is None, "a corrupt revocation store FAILED OPEN (accepted the token)"
    assert SVC.revocation_health()["degraded"] is True, "revocation degradation is not observable"
    assert SVC.revocation_health()["failures"] >= 1


def test_schema_invalid_store_also_fails_closed(auth, tmp_path):
    """A structurally-valid JSON of the WRONG shape (not a list of jti) must also fail closed."""
    tok = auth.issue_token(_DIRECTOR)
    with open(_store_path(tmp_path), "w") as f:
        f.write('{"revoked": "nope"}')                      # not a JSON list
    assert auth.verify_token(tok) is None


def test_revoke_does_not_clobber_a_corrupt_store(auth, tmp_path):
    """revoke_jti must NOT overwrite a corrupt store with a fresh single-entry file -- that would
    silently drop every existing revocation and re-open the fail-open hole. It raises instead."""
    with open(_store_path(tmp_path), "w") as f:
        f.write('{ broken')
    with pytest.raises(auth.RevocationStoreError):
        auth.revoke_jti("some-jti")
    # the corrupt bytes are still there (not replaced by a valid one-entry store)
    with open(_store_path(tmp_path)) as f:
        assert f.read() == '{ broken'


def test_revoke_jti_runs_the_rmw_under_a_lock(auth, monkeypatch):
    """#285: revoke_jti's read-modify-write of the revocation store runs under _REVOKE_LOCK, so two
    concurrent logouts (FastAPI threadpool) cannot lose a revocation (a fail-OPEN lost-update window).
    Deterministic guard: the lock is HELD while the store is read inside revoke_jti, and a second revoke
    preserves the first (no lost update)."""
    locks = []
    orig = auth._revoked_set

    def spy():
        locks.append(auth._REVOKE_LOCK.locked())
        return orig()
    monkeypatch.setattr(auth, "_revoked_set", spy)
    auth.revoke_jti("jti-1")
    assert locks and locks[0] is True, "revoke_jti's read-modify-write ran WITHOUT the lock (#285)"
    auth.revoke_jti("jti-2")
    assert auth.is_revoked("jti-1") and auth.is_revoked("jti-2")   # no lost update
