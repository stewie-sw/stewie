"""#52: operator authentication + whitelist (Tailscale and non-Tailscale paths).

Allowlist (default): mccardle.john@gmail.com, aaron.w.storey80@gmail.com, storeyaw@clarkson.edu
(env STEWIE_ALLOWED_OPERATORS overrides). Login = email + the API key -> an HMAC-signed session
token CARRYING THE OPERATOR IDENTITY (the #39 event-history actor). Tailscale deployments may
trust tailscale-serve's identity header when STEWIE_TRUST_TAILSCALE=1 and the login is
whitelisted.
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


def test_whitelisted_email_logs_in_and_token_authenticates(client):
    r = client.post("/auth/login", json={"email": "aaron.w.storey80@gmail.com"},
                    headers={"X-API-Key": "test-key"})
    assert r.status_code == 200
    tok = r.json()["token"]
    assert r.json()["operator"] == "aaron.w.storey80@gmail.com"
    # the token authorizes a mutating endpoint WITHOUT the raw key
    r2 = client.post("/missions/auth-test", headers={"Authorization": f"Bearer {tok}"},
                     json={"body": "moon", "orders": []})
    assert r2.status_code == 200 and r2.json()["ok"]


def test_unlisted_email_is_refused_even_with_the_key(client):
    r = client.post("/auth/login", json={"email": "intruder@gmail.com"},
                    headers={"X-API-Key": "test-key"})
    assert r.status_code == 403


def test_login_requires_the_api_key(client):
    r = client.post("/auth/login", json={"email": "aaron.w.storey80@gmail.com"})
    assert r.status_code == 401


def test_tampered_token_is_refused(client):
    r = client.post("/auth/login", json={"email": "storeyaw@clarkson.edu"},
                    headers={"X-API-Key": "test-key"})
    tok = r.json()["token"]
    bad = tok[:-4] + ("AAAA" if tok[-4:] != "AAAA" else "BBBB")
    r2 = client.post("/missions/tamper", headers={"Authorization": f"Bearer {bad}"},
                     json={"body": "moon", "orders": []})
    assert r2.status_code == 401


def test_tailscale_header_honored_only_when_trusted(client, monkeypatch):
    # NOT trusted by default
    r = client.post("/missions/ts", headers={"Tailscale-User-Login": "mccardle.john@gmail.com"},
                    json={"body": "moon", "orders": []})
    assert r.status_code == 401
    monkeypatch.setenv("STEWIE_TRUST_TAILSCALE", "1")
    r2 = client.post("/missions/ts", headers={"Tailscale-User-Login": "mccardle.john@gmail.com"},
                     json={"body": "moon", "orders": []})
    assert r2.status_code == 200
    # trusted mode still refuses non-whitelisted identities
    r3 = client.post("/missions/ts2", headers={"Tailscale-User-Login": "evil@gmail.com"},
                     json={"body": "moon", "orders": []})
    assert r3.status_code == 401


def test_operator_login_kill_switch(client, monkeypatch):
    monkeypatch.setenv("STEWIE_OPERATOR_LOGIN", "0")
    r = client.post("/auth/login", json={"email": "aaron.w.storey80@gmail.com"},
                    headers={"X-API-Key": "test-key"})
    assert r.status_code == 403 and "disabled" in r.json()["error"]
    assert client.get("/auth/config").json()["operator_login"] is False


def test_role_separation_director_vs_operator(client, monkeypatch):
    """#68 [REQ:PO-04]: truth views (debrief) are DIRECTOR-only; the shaped operator view is for
    everyone authenticated. Directors default to the full whitelist; STEWIE_DIRECTORS narrows."""
    monkeypatch.setenv("STEWIE_ALLOWED_OPERATORS",
                       "aaron.w.storey80@gmail.com, trainee@gmail.com")
    monkeypatch.setenv("STEWIE_DIRECTORS", "aaron.w.storey80@gmail.com")
    from stewie.server import auth as AUTH
    assert AUTH.role_of("aaron.w.storey80@gmail.com") == "director"
    assert AUTH.role_of("trainee@gmail.com") == "operator"
    assert AUTH.role_of("api-key") == "director"           # automation keeps full power
    # an operator token is refused on the debrief truth view
    tok = client.post("/auth/login", json={"email": "trainee@gmail.com"},
                      headers={"X-API-Key": "test-key"}).json()["token"]
    r = client.post("/session/start", headers={"X-API-Key": "test-key"},
                    json={"name": "rs", "body": "moon", "charger": [0, 0],
                          "orders": [{"action": "a", "kind": "cut", "x": 10, "y": 0,
                                      "footprint_m2": 16, "depth_m": 0.05},
                                     {"action": "b", "kind": "fill", "x": 20, "y": 0,
                                      "footprint_m2": 16, "depth_m": 0.05}]})
    sid = r.json()["session_id"]
    assert client.get(f"/session/{sid}/operator",
                      headers={"Authorization": f"Bearer {tok}"}).status_code == 200
    deb = client.get(f"/session/{sid}/debrief", headers={"Authorization": f"Bearer {tok}"})
    assert deb.status_code == 403 and "director" in deb.json()["error"].lower()
    assert client.get(f"/session/{sid}/debrief",
                      headers={"X-API-Key": "test-key"}).status_code == 200
