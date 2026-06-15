"""AG-01 (PRD §7.12): the four-tier role ladder guest < trainee < operator < director,
with role_rank() as the single capability-ordering source. Legacy director/operator records
stay valid (forward migration, no data loss). Real PBKDF2 + on-disk round-trips against a tmp
data_dir; the only accounts in the store are the ones under test (no synthetic fixtures).

Run: <venv>/bin/python -m pytest stewie/server/test_role_ladder.py -q
"""
import importlib

import pytest

_PW = "a-strong-passphrase"          # >= 10 chars, passes the password policy


@pytest.fixture()
def ops(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    from stewie.server import operators as OPS
    importlib.reload(OPS)
    return OPS


def test_role_rank_orders_the_four_tiers(ops):
    r = ops.role_rank
    assert r("guest") < r("trainee") < r("operator") < r("director")


def test_unknown_or_missing_role_ranks_below_guest(ops):
    # fail-closed: an unknown / None / empty role can never satisfy a ">= guest" capability gate
    assert ops.role_rank("bogus") < ops.role_rank("guest")
    assert ops.role_rank(None) < ops.role_rank("guest")
    assert ops.role_rank("") < ops.role_rank("guest")


def test_all_four_roles_register_and_round_trip(ops):
    for role in ("guest", "trainee", "operator", "director"):
        email = f"{role}@example.com"
        ops.create_active(email, _PW, role=role, by="test")
        assert ops.store_role(email) == role


def test_legacy_two_roles_remain_valid(ops):
    # forward migration: pre-existing director/operator roles still validate, persist, and rank
    ops.create_active("boss@example.com", _PW, role="director", by="test")
    ops.create_active("op@example.com", _PW, role="operator", by="test")
    assert ops.store_role("boss@example.com") == "director"
    assert ops.store_role("op@example.com") == "operator"
    assert ops.role_rank("director") > ops.role_rank("operator")


def test_invalid_role_is_rejected_at_create(ops):
    with pytest.raises(ValueError):
        ops.create_active("x@example.com", _PW, role="superadmin", by="test")
