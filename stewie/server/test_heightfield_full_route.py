"""Integration tests for the viz.stewie.space full-resolution DEM endpoints (real Haworth LOLA bundle).

Same real-data posture as test_workarea_png (no synthetic DEM). Asserts: the binary heightfield carries the
right byte length + header meta, the /meta JSON agrees, the analysis drape registers over the same window,
and the graticule returns curved order-frame polylines.
"""
from __future__ import annotations

import os
import struct

import pytest
from fastapi.testclient import TestClient

from stewie.server.server import app

client = TestClient(app)

_BUNDLE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "samples", "lunar_dem", "haworth_10km_5m")
_HAS_DEM = os.path.exists(os.path.join(_BUNDLE, "heightmap.rf32"))
pytestmark = pytest.mark.skipif(not _HAS_DEM, reason="real Haworth DEM bundle not present")


def test_heightfield_full_binary_matches_meta_headers():
    r = client.get("/dem/heightfield_full?site=haworth&window_m=640&x0=300&y0=450")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/octet-stream"
    n = int(r.headers["X-Dem-N"])
    assert n == 129                                            # 640 m / 5 m native -> round(640/5)+1
    assert len(r.content) == n * n * 4                         # float32 row-major, no JSON bloat
    zmin = float(r.headers["X-Dem-Z-Min"])
    zmax = float(r.headers["X-Dem-Z-Max"])
    vals = struct.unpack(f"<{n * n}f", r.content)
    assert min(vals) == pytest.approx(zmin, abs=1e-3)
    assert max(vals) == pytest.approx(zmax, abs=1e-3)
    assert zmax > zmin                                         # real relief, DEM actually sampled


def test_heightfield_full_default_is_native_whole_tile():
    r = client.get("/dem/heightfield_full?site=haworth")       # no window -> whole native tile
    assert r.status_code == 200, r.text
    n = int(r.headers["X-Dem-N"])
    assert n == 2000                                           # 10 km Haworth tile at native 5 m
    assert int(r.headers["X-Dem-Native-N"]) == 2000
    assert r.headers["X-Dem-Lod"] == "0"                       # default max_dim=2048 >= 2000 -> true full res
    assert len(r.content) == n * n * 4


def test_heightfield_full_lod_caps_mesh():
    r = client.get("/dem/heightfield_full?site=haworth&max_dim=256")
    assert r.status_code == 200
    n = int(r.headers["X-Dem-N"])
    assert n == 256 and r.headers["X-Dem-Lod"] == "1"
    assert float(r.headers["X-Dem-Stride"]) > 1.0


def test_meta_endpoint_agrees_with_binary():
    q = "site=haworth&window_m=640&x0=300&y0=450"
    b = client.get(f"/dem/heightfield_full?{q}")
    m = client.get(f"/dem/heightfield_full/meta?{q}").json()
    assert m["ok"] and m["n"] == int(b.headers["X-Dem-N"])
    assert m["z_min"] == pytest.approx(float(b.headers["X-Dem-Z-Min"]), abs=1e-3)
    assert m["window_m"] == pytest.approx(640.0)


def test_full_layer_drape_registers_over_same_window():
    import io

    import numpy as np
    from imageio.v3 import imread
    r = client.get("/dem/heightfield_full/layer.png?site=haworth&window_m=640&x0=300&y0=450&kind=slope")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/png"
    img = np.asarray(imread(io.BytesIO(r.content)))
    assert img.ndim == 3 and img.shape[0] == img.shape[1]     # square, covers the square window
    assert img[:, :, 0].min() != img[:, :, 0].max()           # real slope variation, not blank


def test_full_layer_unknown_kind_400():
    r = client.get("/dem/heightfield_full/layer.png?site=haworth&window_m=320&kind=nonsense")
    assert r.status_code == 400


def test_graticule_returns_curved_order_polylines():
    r = client.get("/dem/graticule?site=haworth")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] and body["lines"]
    win = body["window_m"]
    # every emitted point is inside the (padded) window, in order-local metres
    for ln in body["lines"]:
        assert ln["kind"] in ("meridian", "parallel")
        for x, y in ln["coords"]:
            assert -0.05 * win <= x <= 1.05 * win and -0.05 * win <= y <= 1.05 * win
    # at least one line curves (non-collinear) in the polar frame
    curved = False
    for ln in body["lines"]:
        pts = ln["coords"]
        if len(pts) >= 3:
            (ax, ay), (bx, by), (cx, cy) = pts[0], pts[len(pts) // 2], pts[-1]
            if abs((bx - ax) * (cy - ay) - (by - ay) * (cx - ax)) > 1.0:
                curved = True
                break
    assert curved


def test_unknown_site_404():
    assert client.get("/dem/heightfield_full?site=nope_not_a_site").status_code == 404
    assert client.get("/dem/heightfield_full/meta?site=nope_not_a_site").status_code == 404
