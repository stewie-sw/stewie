"""#117: the end-to-end auth UI backend -- self-registration, director approval, password login
(keyless), the bootstrap director set-password flow, and the director-only admin panel.

Real flows over the FastAPI TestClient against a tmp data_dir; real PBKDF2 + real HMAC tokens.
The founding allowlist (default) makes the X-API-Key identity a director, so api-key calls drive
the admin side without first creating a store account.
"""
import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_API_KEY", "test-key")
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    import stewie.server.server as srv
    importlib.reload(srv)
    yield TestClient(srv.app)
    monkeypatch.undo()
    importlib.reload(srv)


def _approve(client, email, role="operator"):
    return client.post("/admin/operators/approve", headers={"X-API-Key": "test-key"},
                       json={"email": email, "role": role})


def test_register_then_approve_then_keyless_password_login(client):
    r = client.post("/auth/register", json={"email": "newop@example.com",
                                            "password": "a-strong-passphrase"})
    assert r.status_code == 200 and r.json()["status"] == "pending"
    # pending cannot sign in
    assert client.post("/auth/login", json={"email": "newop@example.com",
                                            "password": "a-strong-passphrase"}).status_code == 403
    # a director approves
    assert _approve(client, "newop@example.com").json()["operator"]["status"] == "active"
    # now password login works WITHOUT the shared key
    r = client.post("/auth/login", json={"email": "newop@example.com",
                                         "password": "a-strong-passphrase"})
    assert r.status_code == 200
    j = r.json()
    assert j["must_set_password"] is False and j["role"] == "operator"
    # the minted token authorizes a mutating endpoint
    r2 = client.post("/missions/by-newop", headers={"Authorization": f"Bearer {j['token']}"},
                     json={"body": "moon", "orders": []})
    assert r2.status_code == 200 and r2.json()["ok"]


def test_wrong_password_is_a_generic_403(client):
    client.post("/auth/register", json={"email": "x@example.com", "password": "a-strong-passphrase"})
    _approve(client, "x@example.com")
    r = client.post("/auth/login", json={"email": "x@example.com", "password": "wrong-passphrase-xx"})
    assert r.status_code == 403 and r.json()["error"] == "invalid credentials"


def test_bootstrap_director_sets_password_then_uses_it(client):
    """A founding director (default allowlist, no store record) signs in via the legacy shared-key
    bootstrap, is told to set a password, does so (keyless thereafter)."""
    r = client.post("/auth/login", json={"email": "aaron.w.storey80@gmail.com"},
                    headers={"X-API-Key": "test-key"})
    assert r.status_code == 200
    j = r.json()
    assert j["must_set_password"] is True and j["role"] == "director"
    r = client.post("/auth/password", headers={"Authorization": f"Bearer {j['token']}"},
                    json={"new_password": "aarons-strong-passphrase"})
    assert r.status_code == 200
    # keyless password login now works and is no longer flagged must_set_password
    r = client.post("/auth/login", json={"email": "aaron.w.storey80@gmail.com",
                                         "password": "aarons-strong-passphrase"})
    assert r.status_code == 200 and r.json()["must_set_password"] is False and r.json()["role"] == "director"
    # legacy key login is now refused for this account (it has a password)
    assert client.post("/auth/login", json={"email": "aaron.w.storey80@gmail.com"},
                       headers={"X-API-Key": "test-key"}).status_code == 403


def test_auth_me_reports_identity_role_and_password_state(client):
    r = client.get("/auth/me", headers={"X-API-Key": "test-key"})
    assert r.status_code == 200
    j = r.json()
    assert j["identity"] == "api-key" and j["role"] == "director" and j["has_password"] is False


def test_admin_panel_is_director_only(client):
    client.post("/auth/register", json={"email": "plainop@example.com", "password": "a-strong-passphrase"})
    _approve(client, "plainop@example.com", role="operator")
    tok = client.post("/auth/login", json={"email": "plainop@example.com",
                                           "password": "a-strong-passphrase"}).json()["token"]
    # operator token is refused on the admin panel
    assert client.get("/admin/operators", headers={"Authorization": f"Bearer {tok}"}).status_code == 403
    # the director (api-key) sees the roster
    r = client.get("/admin/operators", headers={"X-API-Key": "test-key"})
    assert r.status_code == 200
    assert any(o["email"] == "plainop@example.com" for o in r.json()["operators"])


def test_revoke_denies_subsequent_login(client):
    client.post("/auth/register", json={"email": "rv@example.com", "password": "a-strong-passphrase"})
    _approve(client, "rv@example.com")
    assert client.post("/auth/login", json={"email": "rv@example.com",
                                            "password": "a-strong-passphrase"}).status_code == 200
    client.post("/admin/operators/revoke", headers={"X-API-Key": "test-key"},
                json={"email": "rv@example.com"})
    assert client.post("/auth/login", json={"email": "rv@example.com",
                                            "password": "a-strong-passphrase"}).status_code == 403


def test_admin_reset_password(client):
    client.post("/auth/register", json={"email": "rp@example.com", "password": "original-passphrase"})
    _approve(client, "rp@example.com")
    client.post("/admin/operators/reset", headers={"X-API-Key": "test-key"},
                json={"email": "rp@example.com", "new_password": "reset-passphrase-xx"})
    assert client.post("/auth/login", json={"email": "rp@example.com",
                                            "password": "reset-passphrase-xx"}).status_code == 200
    assert client.post("/auth/login", json={"email": "rp@example.com",
                                            "password": "original-passphrase"}).status_code == 403


def test_last_active_director_guard(client):
    client.post("/auth/register", json={"email": "d1@example.com", "password": "a-strong-passphrase"})
    _approve(client, "d1@example.com", role="director")
    # the only store director -> revoke refused (would lock out admin)
    assert client.post("/admin/operators/revoke", headers={"X-API-Key": "test-key"},
                       json={"email": "d1@example.com"}).status_code == 409
    # a second store director -> revoking the first is now allowed
    client.post("/auth/register", json={"email": "d2@example.com", "password": "a-strong-passphrase"})
    _approve(client, "d2@example.com", role="director")
    assert client.post("/admin/operators/revoke", headers={"X-API-Key": "test-key"},
                       json={"email": "d1@example.com"}).status_code == 200


def test_registration_can_be_closed(client, monkeypatch):
    monkeypatch.setenv("STEWIE_REGISTRATION", "0")
    r = client.post("/auth/register", json={"email": "late@example.com",
                                            "password": "a-strong-passphrase"})
    assert r.status_code == 403
    assert client.get("/auth/config").json()["registration_open"] is False
