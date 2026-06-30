"""#117: the operator-account store -- registration, approval, password auth, lockout, roles.

Real PBKDF2 hashing + real on-disk JSON round-trips (a tmp data_dir); the wall clock is the one
injected seam, so the lockout-window test is deterministic without sleeping.
"""
import importlib

import pytest


@pytest.fixture()
def ops(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    from stewie.server import operators as OPS
    importlib.reload(OPS)
    return OPS


def test_register_creates_a_pending_account(ops):
    rec = ops.register("Trainee@Example.com", "correct horse battery")
    assert rec["email"] == "trainee@example.com"      # normalized
    assert rec["status"] == "pending" and rec["role"] == "operator"
    assert ops.exists("trainee@example.com")
    assert not ops.is_active("trainee@example.com")    # pending != active


def test_password_is_never_stored_in_plaintext(ops, tmp_path):
    ops.register("op@example.com", "super-secret-passphrase")
    raw = (tmp_path / "operators.json").read_text()
    assert "super-secret-passphrase" not in raw
    assert "pw_hash" in raw and "pw_salt" in raw
    # the public record never exposes the hash/salt
    assert "pw_hash" not in ops.get("op@example.com")


def test_weak_password_and_bad_email_are_refused(ops):
    with pytest.raises(ValueError):
        ops.register("op@example.com", "short")        # < 10 chars
    with pytest.raises(ValueError):
        ops.register("not-an-email", "long-enough-password")


def test_duplicate_registration_is_refused(ops):
    ops.register("dup@example.com", "long-enough-password")
    with pytest.raises(ValueError):
        ops.register("dup@example.com", "another-long-password")


def test_pending_cannot_authenticate_until_approved(ops):
    ops.register("pend@example.com", "long-enough-password")
    assert ops.verify_credentials("pend@example.com", "long-enough-password") is None
    ops.approve("pend@example.com", by="director@example.com")
    assert ops.verify_credentials("pend@example.com", "long-enough-password") == "pend@example.com"
    assert ops.is_active("pend@example.com")


def test_wrong_password_fails_and_persists_across_reload(ops, monkeypatch, tmp_path):
    ops.create_active("a@example.com", "the-real-password")
    assert ops.verify_credentials("a@example.com", "the-real-password") == "a@example.com"
    assert ops.verify_credentials("a@example.com", "the-wrong-password") is None
    # a fresh import (new process) reads the same on-disk store
    import stewie.server.operators as OPS2
    importlib.reload(OPS2)
    assert OPS2.verify_credentials("a@example.com", "the-real-password") == "a@example.com"


def test_lockout_after_five_failures_then_releases(ops, monkeypatch):
    t = [1000.0]
    monkeypatch.setattr(ops, "_clock", lambda: t[0])
    ops.create_active("lock@example.com", "the-real-password")
    for _ in range(5):
        assert ops.verify_credentials("lock@example.com", "nope") is None
    assert ops.is_locked("lock@example.com")
    # locked out: even the CORRECT password is refused inside the window
    assert ops.verify_credentials("lock@example.com", "the-real-password") is None
    t[0] += 15 * 60 + 1                                 # past the lockout window
    assert not ops.is_locked("lock@example.com")
    assert ops.verify_credentials("lock@example.com", "the-real-password") == "lock@example.com"


def test_lockout_is_per_ip_not_griefable_across_ips(ops, monkeypatch):
    """#279: the failed-login lockout is keyed per (account, client_ip), so a remote attacker burning 5
    attempts from THEIR IP cannot lock out the legitimate operator logging in from a DIFFERENT IP. Pre-#279
    the lockout was global per-account, so any known email could be locked by anyone."""
    t = [1000.0]
    monkeypatch.setattr(ops, "_clock", lambda: t[0])
    ops.create_active("vic@example.com", "the-real-password")
    for _ in range(5):                                  # attacker at 10.0.0.9 burns the account's attempts
        assert ops.verify_credentials("vic@example.com", "nope", client_ip="10.0.0.9") is None
    assert ops.is_locked("vic@example.com", client_ip="10.0.0.9")          # the attacker's IP is locked
    # the LEGIT user at a different IP is NOT locked -> the correct password still authenticates (no griefing)
    assert not ops.is_locked("vic@example.com", client_ip="10.0.0.2")
    assert ops.verify_credentials("vic@example.com", "the-real-password", client_ip="10.0.0.2") == "vic@example.com"


def test_revoke_denies_and_role_change_sticks(ops):
    ops.create_active("r@example.com", "the-real-password", role="director")
    assert ops.store_role("r@example.com") == "director"
    ops.set_role("r@example.com", "operator", by="admin@example.com")
    assert ops.store_role("r@example.com") == "operator"
    ops.revoke("r@example.com", by="admin@example.com")
    assert not ops.is_active("r@example.com")
    assert ops.store_role("r@example.com") is None      # not active -> no store role
    assert ops.verify_credentials("r@example.com", "the-real-password") is None


def test_self_change_password_requires_old(ops):
    ops.create_active("c@example.com", "old-password-here")
    assert ops.verify_old_password("c@example.com", "old-password-here")
    assert not ops.verify_old_password("c@example.com", "guessed-password")
    ops.set_password("c@example.com", "brand-new-password")
    assert ops.verify_credentials("c@example.com", "brand-new-password") == "c@example.com"
    assert ops.verify_credentials("c@example.com", "old-password-here") is None


def test_delete_removes_the_account(ops):
    ops.create_active("d@example.com", "long-enough-password")
    assert ops.delete("d@example.com") is True
    assert not ops.exists("d@example.com")
    assert ops.delete("d@example.com") is False         # idempotent-ish: gone already


def test_list_all_is_public_and_sorted(ops):
    ops.create_active("zeta@example.com", "long-enough-password")
    ops.register("alpha@example.com", "long-enough-password")
    rows = ops.list_all()
    assert [r["email"] for r in rows] == ["alpha@example.com", "zeta@example.com"]
    assert all("pw_hash" not in r and "pw_salt" not in r for r in rows)
