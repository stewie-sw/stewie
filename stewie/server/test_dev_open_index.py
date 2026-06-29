"""#265: a loopback dev-open server seeds the readable stewie_csrf cookie on GET / so the cockpit boot
sees "a session likely exists", calls /auth/me (which returns the dev-open director on loopback), and
reveals the cockpit instead of the sign-in overlay -- unblocking headless visual verification. A
NON-dev-open server must NOT seed it (fail-closed for real deploys). Auth itself is granted by
require_auth's env+loopback check, not the cookie; this only flips the client's reveal heuristic."""
from fastapi.testclient import TestClient


def _client(monkeypatch, tmp_path, *, dev_open):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("STEWIE_API_KEY", raising=False)
    if dev_open:
        monkeypatch.setenv("STEWIE_DEV_OPEN", "1")
    else:
        monkeypatch.delenv("STEWIE_DEV_OPEN", raising=False)
    import stewie.server.server as SRV
    return TestClient(SRV.app)


def test_dev_open_index_seeds_readable_csrf(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path, dev_open=True)
    r = c.get("/")
    assert r.status_code == 200
    assert "stewie_csrf" in r.cookies, "dev-open GET / should seed the readable stewie_csrf cookie"
    # and /auth/me on the same loopback session returns the dev-open director (the reveal the client needs)
    me = c.get("/auth/me").json()
    assert me.get("role") == "director" and me.get("identity") == "dev-open"


def test_non_dev_open_index_seeds_no_cookie(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path, dev_open=False)
    r = c.get("/")
    assert r.status_code == 200
    assert "stewie_csrf" not in r.cookies, "a non-dev-open server must not seed a session cookie (fail-closed)"
