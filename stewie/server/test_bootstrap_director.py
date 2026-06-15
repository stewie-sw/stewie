"""bootstrap_director_from_env(): server-side first-director provisioning from the deploy env
(STEWIE_BOOTSTRAP_DIRECTOR / STEWIE_BOOTSTRAP_PASSWORD), so the shared deploy key never enters a
browser. Real PBKDF2 + on-disk JSON round-trips against a tmp data_dir; the only account in the
store is the one the test seeds (no synthetic fixtures).

Run: <venv>/bin/python -m pytest stewie/server/test_bootstrap_director.py -q
"""
import importlib

import pytest

_PW = "a-strong-passphrase"          # >= 10 chars, passes the password policy


@pytest.fixture()
def ops(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    # start from a clean env: no prior test / host value can leak in
    monkeypatch.delenv("STEWIE_BOOTSTRAP_DIRECTOR", raising=False)
    monkeypatch.delenv("STEWIE_BOOTSTRAP_PASSWORD", raising=False)
    from stewie.server import operators as OPS
    importlib.reload(OPS)
    return OPS, monkeypatch


def test_seeds_an_active_director_when_env_set_and_store_empty(ops):
    OPS, mp = ops
    mp.setenv("STEWIE_BOOTSTRAP_DIRECTOR", "Founder@Example.com")
    mp.setenv("STEWIE_BOOTSTRAP_PASSWORD", _PW)
    seeded = OPS.bootstrap_director_from_env()
    assert seeded == "founder@example.com"               # normalized
    assert OPS.is_active("founder@example.com")
    assert OPS.store_role("founder@example.com") == "director"
    assert OPS.verify_credentials("founder@example.com", _PW) == "founder@example.com"


def test_no_op_without_env(ops):
    OPS, _mp = ops
    assert OPS.bootstrap_director_from_env() is None      # neither var set
    assert OPS.list_all() == []                           # nothing created


def test_no_op_when_only_one_var_set(ops):
    OPS, mp = ops
    mp.setenv("STEWIE_BOOTSTRAP_DIRECTOR", "founder@example.com")   # password missing
    assert OPS.bootstrap_director_from_env() is None
    assert OPS.list_all() == []


def test_idempotent_when_the_account_already_exists(ops):
    OPS, mp = ops
    mp.setenv("STEWIE_BOOTSTRAP_DIRECTOR", "founder@example.com")
    mp.setenv("STEWIE_BOOTSTRAP_PASSWORD", _PW)
    assert OPS.bootstrap_director_from_env() == "founder@example.com"
    assert OPS.bootstrap_director_from_env() is None      # second boot is a no-op
    directors = [r for r in OPS.list_all() if r["role"] == "director"]
    assert len(directors) == 1                            # not duplicated


def test_no_op_when_another_active_director_already_exists(ops):
    OPS, mp = ops
    OPS.create_active("boss@example.com", _PW, role="director", by="test")
    mp.setenv("STEWIE_BOOTSTRAP_DIRECTOR", "newcomer@example.com")
    mp.setenv("STEWIE_BOOTSTRAP_PASSWORD", _PW)
    assert OPS.bootstrap_director_from_env() is None      # a fleet is already configured
    assert not OPS.exists("newcomer@example.com")         # the env account is NOT seeded


def test_returns_none_on_weak_password(ops):
    OPS, mp = ops
    mp.setenv("STEWIE_BOOTSTRAP_DIRECTOR", "founder@example.com")
    mp.setenv("STEWIE_BOOTSTRAP_PASSWORD", "short")       # < 10 chars -> create_active raises
    assert OPS.bootstrap_director_from_env() is None
    assert not OPS.exists("founder@example.com")          # nothing half-created


def test_returns_none_on_bad_email(ops):
    OPS, mp = ops
    mp.setenv("STEWIE_BOOTSTRAP_DIRECTOR", "not-an-email")
    mp.setenv("STEWIE_BOOTSTRAP_PASSWORD", _PW)
    assert OPS.bootstrap_director_from_env() is None
    assert OPS.list_all() == []
