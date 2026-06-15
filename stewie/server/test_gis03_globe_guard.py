"""GIS-03 (revised, live-site fix): the /layers/globe/* routes took unbounded float params (a DoS:
each distinct param recomputes + grows the disk cache, and for kind='grid' the raw `color` became a
cache-FILE component -> path abuse). The original fix auth-GATED them (heavy_quota), but that 401'd the
base-map drape on the live cockpit -- a map you cannot see is worse than the DoS the rate-limit already
covers. So the drape is now PUBLIC but PER-IP RATE-LIMITED (globe_quota), with the sun params clamped+
quantized to integer degrees, `color` sanitized to 6 hex digits, and `kind` validated against the known
layers. (Auth still guards the heavy PLANNER routes; only the read-only base map is public.)
"""
from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_API_KEY", "test-key")
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWIE_GLOBE_QUOTA_MAX", "3")        # small per-IP globe quota so a burst trips fast
    monkeypatch.setenv("STEWIE_GLOBE_QUOTA_WINDOW_S", "60")
    from stewie.server.routers import layers as layersr
    importlib.reload(layersr)      # fresh _globe_quota at MAX=3, rebinds the globe routes onto it
    import stewie.server.server as srv
    importlib.reload(srv)          # re-includes the fresh layers router
    yield TestClient(srv.app), "test-key"
    monkeypatch.undo()
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


def test_globe_png_is_public(client):
    # GIS-03 (live-fix): the base-map drape is PUBLIC -- a no-auth request must NOT be auth-rejected.
    # (Here the DEM is absent in the tmp data dir, so it's a clean 404, never a 401/403.)
    c, _key = client
    r = c.get("/layers/globe/slope.png")
    assert r.status_code not in (401, 403), f"globe png must be public (GIS-03 live-fix): {r.status_code}"


def test_globe_bbox_is_public(client):
    c, _key = client
    r = c.get("/layers/globe/slope/bbox")
    assert r.status_code not in (401, 403), f"globe bbox must be public (GIS-03 live-fix): {r.status_code}"


def test_globe_unknown_kind_is_404_not_500(client):
    c, key = client
    r = c.get("/layers/globe/warp.png", headers={"X-API-Key": key})
    assert r.status_code == 404, r.status_code


def test_globe_serves_without_a_key(client):
    # a request with NO API key reaches the renderer (200 if the DEM renders, 404 if absent in this env
    # -- never 401/403). Proves the public drape needs no operator credential.
    c, _key = client
    r = c.get("/layers/globe/dem.png")
    assert r.status_code not in (401, 403), r.status_code


def test_globe_enforces_per_ip_ratelimit(client):
    # GIS-03 (live-fix): no auth gate, but the heavy reprojection is still rate-limited PER CLIENT IP.
    # The fixture sets STEWIE_GLOBE_QUOTA_MAX=3, so a no-key burst from one IP must trip 429 (not 401/403).
    c, _key = client
    codes = [c.get("/layers/globe/grid.png").status_code for _ in range(5)]
    assert 429 in codes, f"globe route has no per-IP rate-limit (GIS-03 live-fix); saw {codes}"
    assert 401 not in codes and 403 not in codes, codes
