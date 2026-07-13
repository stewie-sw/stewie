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
def _isolate_data_dir(tmp_path_factory, monkeypatch):
    """#122: every worker otherwise shares the default $STEWIE_DATA_DIR (~/.local/share/stewie), so under
    `pytest -n auto` tests that write app-data there race -- mission report PDFs (the /plan stem is a
    deterministic HMAC of the payload, so identical payloads collide on one {stem}.pdf across workers),
    events.jsonl, profiles, the operators store. A reader then catches a half-written report (the
    b'\\x00\\x00\\x00\\x00\\x00' != b'%PDF-' failure). Give every test its OWN scratch data dir so on-disk
    app-data is isolated across workers. A test that wants a specific dir (the ~20 that set STEWIE_DATA_DIR
    to their tmp_path) or the unset default (test_data_dir_default_is_outside_the_package pops the var)
    overrides this afterward -- its monkeypatch/pop runs after this fixture and wins."""
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path_factory.mktemp("appdata")))


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
def _reset_render_caches():
    """REG-01: the GIS raster + globe renderers cache by (kind, SITE, sun) in process-global dicts that
    are never cleared. A prior test that renders a site (in the same `-n auto` worker) can leave a stale
    entry, so test_dem_site_aware's distinct-per-site assertions then read another site's cached bytes
    and flip (the cache-key class that already broke test_globe_cache). Clear both before each test so the
    raster/globe distinctness checks are isolated -- the in-process equivalent of the data-dir isolation
    above. (The state DEM cache is site-keyed + loads deterministically from disk, so it is not a
    distinctness vector and is left alone.)"""
    try:
        from stewie.server import gis_layers as _gl
        _gl._CACHE.clear()
        _gl._GLOBE_CACHE.clear()
    except Exception:
        pass
    yield


@pytest.fixture(autouse=True)
def _reset_auth_rate_limits():
    """S-07 / S-08 / GIS-03: every RateLimiter is a MODULE-LEVEL, process-global fixed-window counter,
    and every TestClient shares ONE client IP ('testclient') -- so one test's spent budget leaks into
    every later test in the same process. Reset them before each test. Production is unaffected: this
    only clears in-process buckets between tests.

    This fixture used to HAND-LIST the limiters, and that is exactly what failed: the GIS-03 globe quota
    (`routers/layers.py::_globe_quota`, 180 hits / 60 s per IP) was added after this list and never
    registered here. Once the suite made >180 `/layers/raster/*` calls inside one window, the budget was
    spent, and a LATER, unrelated test went red on a 429 it never caused --
    `stewie/specs/test_solar.py::test_layer_endpoint_accepts_mission_time`, which passes in isolation and
    failed only in-suite (a genuine order-dependent false red, not a flake).

    So instead of hand-listing (the thing that broke), SWEEP every loaded `stewie.*` module for live
    RateLimiter instances and reset each. A limiter added in the future is then isolated automatically.
    The explicit resets below are kept so this stays a strict superset even if a module is not yet
    imported when the sweep runs.
    """
    try:
        import sys

        from stewie.server.ratelimit import RateLimiter
        for _name, _mod in list(sys.modules.items()):
            if _mod is None or not _name.startswith("stewie."):
                continue
            for _obj in list(vars(_mod).values()):
                if isinstance(_obj, RateLimiter):
                    _obj.reset()
    except Exception:
        pass
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
    try:
        from stewie.server.routers import layers as _layersr
        _layersr._globe_quota.reset()         # GIS-03: per-IP globe/raster render quota (the leak above)
    except Exception:
        pass
    yield


@pytest.fixture(autouse=True)
def _reset_world_state_service():
    """A1: the WorldStateService is a process-global singleton (state._WSS) bound to its data-dir world
    journal at first build. Like the twin, it is not reset by _isolate_data_dir, so a route that builds
    it (e.g. /twin/resync, /executive/run) would bind it to whichever test ran first and every later
    in-worker test would reuse that stale service (wrong journal). Reset it before each test so each gets
    a fresh service against its own isolated data dir. (It wraps the state.twin accessor, read live, so
    resetting _WSS alone suffices.)"""
    try:
        from stewie.server import state as _st
        _st._WSS = None
    except Exception:
        pass
    yield
