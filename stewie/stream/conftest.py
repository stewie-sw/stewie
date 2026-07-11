"""Test isolation for the stream security guard.

The guard's state (the per-IP sliding window + the live-session counter) is process-global, so a
prior test's connections would otherwise bleed into the next (all TestClient requests share the
`testclient` peer IP). Reset that state before each test. The three guard env vars are also cleared
so every test starts from the OFF/default posture and opts in explicitly via ``monkeypatch.setenv``.
"""
import pytest


@pytest.fixture(autouse=True)
def _reset_stream_security(monkeypatch):
    from stewie.stream import security
    for var in (security.ENV_TOKEN, security.ENV_MAX_SESSIONS, security.ENV_MAX_CONN_PER_MIN):
        monkeypatch.delenv(var, raising=False)
    security.reset_state()
    yield
    security.reset_state()
