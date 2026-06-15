"""Repo-wide pytest fixtures.

The test suite runs keyless. After audit C-01, a keyless server FAILS CLOSED on privileged routes
(no more director-equivalent `dev-open` by default), so declare EXPLICIT dev-open for the suite
(STEWIE_DEV_OPEN=1) — the TestClient is an in-process/loopback transport, which is the only place
dev-open is permitted. Auth-specific tests override this with monkeypatch to exercise the
fail-closed path.
"""
import pytest


@pytest.fixture(autouse=True)
def _dev_open(monkeypatch):
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")


@pytest.fixture(autouse=True)
def _reset_security_health():
    """S-10 / SEC-02: the audit-ledger and session-revocation health flags are process-global. A test
    that deliberately induces a degraded state (a fail-closed probe) would otherwise leave /healthz
    reading 'degraded' for every later test. Reset both before each test so the shared state is isolated.
    Resetting at SETUP (not teardown) keeps a test's own induced degradation visible within that test."""
    try:
        from stewie.server import services as _svc
        _svc.reset_audit_health()
        _svc.reset_revocation_health()
    except Exception:
        pass
    yield


@pytest.fixture(autouse=True)
def _reset_auth_rate_limits():
    """S-07: the auth rate limiters are process-global fixed-window counters. Reset them before each
    test so a multi-login test (admin flows, fixtures) does not inherit another test's spent budget
    and falsely 429. The production limiter is unaffected; this is test isolation for shared state."""
    try:
        from stewie.server.routers import auth as _authr
        for lim in ("_login_ip_limiter", "_login_acct_limiter", "_register_ip_limiter"):
            getattr(_authr, lim).reset()
    except Exception:
        pass
    try:
        from stewie.server.routers import plan as _planr
        _planr._heavy_quota.reset()           # S-08: per-identity heavy-route quota (process-global)
    except Exception:
        pass
    yield
