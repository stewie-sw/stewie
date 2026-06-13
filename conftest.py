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
