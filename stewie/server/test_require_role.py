"""AG-02 [REQ:AG-02] (PRD §7.12): require_role(min) capability gating keyed off operators.role_rank, reusing
auth.role_of so every identity type (store account, env director, api-key/dev-open) resolves the
same way require_director already does. Real PBKDF2 + on-disk store against a tmp data_dir; one
account per role, nothing synthetic.

Run: <venv>/bin/python -m pytest stewie/server/test_require_role.py -q
"""
import importlib

import pytest
from fastapi import HTTPException

_PW = "a-strong-passphrase"


@pytest.fixture()
def deps(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWIE_DIRECTORS", "")          # no env directors -> the store governs roles
    from stewie.server import operators as OPS
    importlib.reload(OPS)
    from stewie.server import deps as DEPS
    importlib.reload(DEPS)
    for role in ("guest", "trainee", "operator", "director"):
        OPS.create_active(f"{role}@x.com", _PW, role=role, by="test")
    return DEPS


def _admits(DEPS, min_role, identity):
    """Run require_role(min_role) for `identity`; True if admitted, False on a 403 (calling the inner
    dependency directly with identity bypasses require_auth's header machinery)."""
    dep = DEPS.require_role(min_role)
    try:
        return dep(identity=identity) == identity
    except HTTPException as e:
        assert e.status_code == 403
        return False


def test_operator_gate_admits_operator_and_director(deps):
    assert _admits(deps, "operator", "operator@x.com")
    assert _admits(deps, "operator", "director@x.com")


def test_operator_gate_rejects_guest_and_trainee(deps):
    assert not _admits(deps, "operator", "guest@x.com")
    assert not _admits(deps, "operator", "trainee@x.com")


def test_director_gate_rejects_operator(deps):
    assert not _admits(deps, "director", "operator@x.com")
    assert _admits(deps, "director", "director@x.com")


def test_guest_gate_admits_every_tier(deps):
    for r in ("guest", "trainee", "operator", "director"):
        assert _admits(deps, "guest", f"{r}@x.com")


def test_api_key_and_dev_open_are_director_equivalent(deps):
    # role_of() maps automation/dev identities to director -> they clear any gate
    assert _admits(deps, "director", "api-key")
    assert _admits(deps, "director", "dev-open")
