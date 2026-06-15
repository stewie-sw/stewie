"""AG-03/04 (PRD §7.12): one-time invite tokens. A director MINTS a role-scoped, single-use,
TTL-bounded token (the raw token is returned once; only its sha256 hash is stored); anyone holding
the token REDEEMS it to create their own active account and set their own password. Real PBKDF2 +
on-disk store + injected clock against a tmp data_dir; nothing synthetic.

Run: <venv>/bin/python -m pytest stewie/server/test_invites.py -q
"""
import importlib

import pytest
from fastapi.testclient import TestClient

_PW = "a-strong-passphrase"


@pytest.fixture()
def ops(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    from stewie.server import operators as OPS
    importlib.reload(OPS)
    return OPS


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_API_KEY", "test-key")          # the api-key identity resolves to director
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    from stewie.server import operators as OPS
    importlib.reload(OPS)
    from stewie.server.routers import invites as invr
    importlib.reload(invr)
    import stewie.server.server as srv
    importlib.reload(srv)
    yield TestClient(srv.app), OPS, "test-key"
    monkeypatch.undo()
    importlib.reload(srv)


# ---- primitive: operators.create_invite / redeem_invite ----------------------------------------

def test_create_invite_returns_raw_token_and_stores_only_the_hash(ops, tmp_path):
    token = ops.create_invite(by="director@x.com", role="operator")
    assert isinstance(token, str) and len(token) >= 32
    raw = (tmp_path / "operators.json").read_text()
    assert token not in raw                                    # the plaintext token is never persisted
    assert "invites" in raw


def test_redeem_creates_active_account_at_invite_role_then_burns(ops):
    token = ops.create_invite(by="director@x.com", role="trainee")
    rec = ops.redeem_invite(token, "Newbie@x.com", _PW)
    assert rec["email"] == "newbie@x.com"                      # normalized
    assert ops.is_active("newbie@x.com") and ops.store_role("newbie@x.com") == "trainee"
    assert ops.verify_credentials("newbie@x.com", _PW) == "newbie@x.com"
    with pytest.raises(ValueError):                            # single-use -> the token is burned
        ops.redeem_invite(token, "other@x.com", _PW)


def test_unknown_token_is_rejected(ops):
    with pytest.raises(ValueError):
        ops.redeem_invite("nope-not-a-real-token", "x@x.com", _PW)


def test_expired_invite_is_rejected(ops, monkeypatch):
    t = {"now": 1000.0}
    monkeypatch.setattr(ops, "_clock", lambda: t["now"])       # deterministic expiry, no sleeping
    token = ops.create_invite(by="d@x.com", role="operator", ttl_s=10)
    t["now"] = 1000.0 + 11
    with pytest.raises(ValueError):
        ops.redeem_invite(token, "late@x.com", _PW)


def test_bad_password_does_not_burn_the_invite(ops):
    token = ops.create_invite(by="d@x.com", role="operator")
    with pytest.raises(ValueError):
        ops.redeem_invite(token, "x@x.com", "short")           # weak pw -> create_active raises first
    rec = ops.redeem_invite(token, "x@x.com", _PW)             # invite intact -> a good redeem works
    assert ops.is_active("x@x.com") and rec["email"] == "x@x.com"


def test_invite_role_must_be_known(ops):
    with pytest.raises(ValueError):
        ops.create_invite(by="d@x.com", role="superadmin")


# ---- endpoints: /admin/invite (director) + /auth/invite/redeem (public) ------------------------

def test_redeem_endpoint_is_public_and_creates_the_account(client):
    c, OPS, _key = client
    token = OPS.create_invite(by="director@x.com", role="operator")
    r = c.post("/auth/invite/redeem", json={"token": token, "email": "pub@x.com", "password": _PW})
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "operator"
    assert OPS.is_active("pub@x.com")


def test_mint_endpoint_requires_director(client):
    c, _OPS, key = client
    r0 = c.post("/admin/invite", json={"role": "operator"})            # no credential
    assert r0.status_code in (401, 403), r0.status_code
    r1 = c.post("/admin/invite", headers={"X-API-Key": key}, json={"role": "trainee"})
    assert r1.status_code == 200, r1.text
    assert r1.json()["token"] and r1.json()["role"] == "trainee"


def test_redeem_endpoint_rejects_a_bad_token(client):
    c, _OPS, _key = client
    r = c.post("/auth/invite/redeem", json={"token": "bogus", "email": "x@x.com", "password": _PW})
    assert r.status_code == 400, r.text
