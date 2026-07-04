"""[REQ:BP-04] Production identity is strict: with no explicit STEWIE_ALLOWED_OPERATORS a TLS-terminated
deployment fails CLOSED (the built-in staff allowlist is NOT trusted), and /healthz + /config surface the
degraded 'running on built-in defaults' posture. dev/desktop keep the defaults for convenience."""
from fastapi.testclient import TestClient


def test_bp04_prod_without_allowlist_fails_closed(monkeypatch):  # [REQ:BP-04]
    monkeypatch.setenv("STEWIE_TLS_TERMINATED", "1")
    monkeypatch.delenv("STEWIE_ALLOWED_OPERATORS", raising=False)
    from stewie.server import auth
    assert auth.allowlist() == ()                                  # fail closed, NOT the hardcoded defaults
    assert auth.is_allowed("aaron.w.storey80@gmail.com") is False  # even a built-in staff email is denied


def test_bp04_dev_keeps_the_default_allowlist(monkeypatch):  # [REQ:BP-04]
    monkeypatch.delenv("STEWIE_TLS_TERMINATED", raising=False)
    monkeypatch.delenv("STEWIE_ALLOWED_OPERATORS", raising=False)
    from stewie.server import auth
    assert "aaron.w.storey80@gmail.com" in auth.allowlist()        # dev convenience preserved


def test_bp04_prod_with_explicit_allowlist_uses_it(monkeypatch):  # [REQ:BP-04]
    monkeypatch.setenv("STEWIE_TLS_TERMINATED", "1")
    monkeypatch.setenv("STEWIE_ALLOWED_OPERATORS", "ops@example.com")
    from stewie.server import auth
    assert auth.allowlist() == ("ops@example.com",)
    assert auth.is_allowed("ops@example.com") is True


def test_bp04_builtin_defaults_flag(monkeypatch):  # [REQ:BP-04]
    from stewie.server import auth
    monkeypatch.delenv("STEWIE_ALLOWED_OPERATORS", raising=False)
    monkeypatch.delenv("STEWIE_DIRECTORS", raising=False)
    assert auth.identity_on_builtin_defaults() is True
    monkeypatch.setenv("STEWIE_ALLOWED_OPERATORS", "ops@example.com")
    assert auth.identity_on_builtin_defaults() is False


def test_bp04_healthz_and_config_report_degraded_in_prod(monkeypatch, tmp_path):  # [REQ:BP-04]
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWIE_TLS_TERMINATED", "1")               # production posture
    monkeypatch.setenv("STEWIE_SESSION_SECRET", "test-session")    # satisfy the BP-03 startup guard
    monkeypatch.delenv("STEWIE_ALLOWED_OPERATORS", raising=False)  # -> on built-in defaults
    monkeypatch.delenv("STEWIE_DIRECTORS", raising=False)
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")                     # so the /config auth passes for loopback
    import stewie.server.server as SRV
    c = TestClient(SRV.app)
    h = c.get("/healthz").json()
    assert h["identity"]["on_builtin_defaults"] is True and h["identity"]["degraded"] is True
    assert h["status"] == "degraded"                              # prod-on-defaults flips the liveness state
    cfg = c.get("/config").json()
    assert cfg["identity"]["on_builtin_defaults"] is True
