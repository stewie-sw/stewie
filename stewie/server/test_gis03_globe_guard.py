"""GIS-03: the /layers/globe/* routes were unauthenticated and took unbounded float params (a DoS:
each distinct param recomputes + grows the disk cache, and for kind='grid' the raw `color` became a
cache-FILE component -> path abuse). Fix: gate them with the SAME auth+quota dependency the raster
layer uses (heavy_quota), clamp+quantize the sun params to integer degrees, and sanitize `color` to
6 hex digits + validate `kind` against the known layers.
"""
from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_API_KEY", "test-key")
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWIE_HEAVY_QUOTA_MAX", "3")        # small quota so a burst trips fast
    monkeypatch.setenv("STEWIE_HEAVY_QUOTA_WINDOW_S", "60")
    from stewie.server.routers import plan as planr
    from stewie.server.routers import layers as layersr
    importlib.reload(planr)        # fresh _heavy_quota at MAX=3
    importlib.reload(layersr)      # rebinds heavy_quota + globe routes onto the fresh limiter
    import stewie.server.server as srv
    importlib.reload(srv)          # re-includes the fresh layers router
    yield TestClient(srv.app), "test-key"
    monkeypatch.undo()
    importlib.reload(planr)
    importlib.reload(layersr)
    importlib.reload(srv)


def test_quantize_sun_clamps_and_wraps_to_integer_degrees():
    from stewie.server.routers import layers as L
    el, az = L._quantize_sun(6.4, 90.4, None)
    assert (el, az) == (6.0, 90.0)                           # rounded to integer degrees
    el, az = L._quantize_sun(200.0, 725.6, None)
    assert el == 90.0 and az == 6.0                          # el clamped to [-90,90]; az wrapped mod 360
    el, az = L._quantize_sun(-200.0, -1.0, None)
    assert el == -90.0 and 0.0 <= az < 360.0


def test_sanitize_color_rejects_nonhex_and_path_abuse():
    from stewie.server.routers import layers as L
    assert L._sanitize_color("abcdef") == "abcdef"
    assert L._sanitize_color("ABCDEF") == "ABCDEF"
    assert L._sanitize_color("../etc") == L._DEFAULT_GRID    # path chars -> default (no traversal)
    assert L._sanitize_color("zzz") == L._DEFAULT_GRID       # non-hex -> default
    assert L._sanitize_color("") == L._DEFAULT_GRID


def test_globe_png_requires_auth(client):
    c, _key = client
    r = c.get("/layers/globe/slope.png")
    assert r.status_code in (401, 403, 503), f"globe png is public (GIS-03): {r.status_code}"


def test_globe_bbox_requires_auth(client):
    c, _key = client
    r = c.get("/layers/globe/slope/bbox")
    assert r.status_code in (401, 403, 503), f"globe bbox is public (GIS-03): {r.status_code}"


def test_globe_unknown_kind_is_404_not_500(client):
    c, key = client
    r = c.get("/layers/globe/warp.png", headers={"X-API-Key": key})
    assert r.status_code == 404, r.status_code


def test_globe_authed_passes_the_gate(client):
    # an authed request gets PAST the auth gate (200 if the DEM renders, 404 if absent in this env --
    # never 401/403). Proves the gate admits a legitimate operator.
    c, key = client
    r = c.get("/layers/globe/dem.png", headers={"X-API-Key": key})
    assert r.status_code not in (401, 403), r.status_code


def test_globe_enforces_per_identity_quota(client):
    c, key = client
    codes = [c.get("/layers/globe/grid.png", headers={"X-API-Key": key}).status_code for _ in range(5)]
    assert 429 in codes, f"globe route has no per-identity quota (GIS-03); saw {codes}"
    assert 401 not in codes and 403 not in codes, codes
