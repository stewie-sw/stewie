"""Setup routes serve measured lunar terrain; procedural preview is retired."""
from __future__ import annotations

import json
import os

import numpy as np
import pytest
from fastapi.testclient import TestClient

from stewie.stream.app import app

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SAMPLES = os.path.join(REPO_ROOT, "samples", "lunar_dem")


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


# ── /bundles ────────────────────────────────────────────────────────────────────────────────
def test_bundles_lists_real_sites_with_real_citations_no_synthetic(client: TestClient):
    r = client.get("/bundles")
    assert r.status_code == 200
    body = r.json()
    rows = body["bundles"]
    assert body["default"] == "haworth_sfs_2km_1m"
    assert len(rows) >= 2, "expected the widened real bundle set"
    names = {b["name"] for b in rows}
    # the widened bundles are present
    assert "haworth_sfs_2km_1m" in names
    assert "shackleton_rim_10km_5m" in names
    for b in rows:
        assert b["synthetic"] is False
        # a real bundle carries a real, non-empty verbatim citation
        assert isinstance(b["citation"], str) and b["citation"].strip(), f"{b['name']} has no citation"
        assert "PROCEDURAL" not in b["source"].upper(), f"{b['name']} looks synthetic"
    # exactly one flagged default, and it is haworth
    assert sum(1 for b in rows if b["default"]) == 1




# ── /preview/heightmap (real) ─────────────────────────────────────────────────────────────────
def test_preview_heightmap_real_stats_match_bundle(client: TestClient):
    site = "haworth_sfs_2km_1m"
    r = client.get(f"/preview/heightmap?site={site}")
    assert r.status_code == 200
    d = r.json()
    assert d["synthetic"] is False
    assert d["site"] == site
    assert d["has_heightmap"] is True
    # non-empty decimated grid
    assert d["n"] >= 32 and d["ncols"] >= 32
    assert len(d["z"]) == d["n"] * d["ncols"]
    # the FULL-resolution stats must match the on-disk bundle exactly
    meta = json.load(open(os.path.join(SAMPLES, site, "metadata.json")))
    Z = np.fromfile(os.path.join(SAMPLES, site, "heightmap.rf32"), dtype="<f4").reshape(
        meta["grid"]["height"], meta["grid"]["width"])
    assert d["full_min_m"] == pytest.approx(float(Z.min()), abs=1e-3)
    assert d["full_max_m"] == pytest.approx(float(Z.max()), abs=1e-3)
    # and match the bundle's declared height_range_m
    hr = meta["height_range_m"]
    assert d["full_min_m"] == pytest.approx(hr[0], abs=1e-2)
    assert d["full_max_m"] == pytest.approx(hr[1], abs=1e-2)
    # the real citation rides along (guardrail: real preview shows the real reference)
    assert "Alexandrov" in d["citation"] or "USGS" in d["citation"]
    # the decimated grid values lie within the full range
    zmin, zmax = min(d["z"]), max(d["z"])
    assert float(Z.min()) - 1e-3 <= zmin <= zmax <= float(Z.max()) + 1e-3


def test_preview_heightmap_bad_site_paths(client: TestClient):
    assert client.get("/preview/heightmap?site=../etc").status_code == 400
    assert client.get("/preview/heightmap?site=nope_not_a_site").status_code == 404


def test_preview_heightmap_metadata_only_bundle(client: TestClient):
    # de_gerlache_kocher_10km_5m ships metadata-only (git tracks ONLY its metadata.json; no heightmap.rf32)
    bundle = os.path.join(SAMPLES, "de_gerlache_kocher_10km_5m")
    if not os.path.isdir(bundle):
        pytest.skip("metadata-only bundle not present")
    # PRECONDITION, stated rather than assumed: this asserts the endpoint's metadata-ONLY branch, so it is
    # only meaningful while the bundle really has no heightmap. A dev tree can carry an UNTRACKED
    # heightmap.rf32 here (fetched/generated locally into a bundle that ships without one) -- then
    # has_heightmap is legitimately True and the scenario under test simply is not present. Skip LOUDLY in
    # that case instead of going red on a real, correct response: the assertions below still run in CI and
    # on any clean checkout, where the file genuinely is absent.
    if os.path.exists(os.path.join(bundle, "heightmap.rf32")):
        pytest.skip("bundle carries an untracked local heightmap.rf32 -> the metadata-only case is absent "
                    "in this tree (it ships metadata-only; CI/clean checkouts still exercise this test)")
    d = client.get("/preview/heightmap?site=de_gerlache_kocher_10km_5m").json()
    assert d["synthetic"] is False
    assert d["has_heightmap"] is False
    assert d["z"] == []
    assert isinstance(d["citation"], str) and d["citation"].strip()


# ── /preview/procedural (synthetic, real fbm_global) ─────────────────────────────────────────






def test_root_serves_setup_and_stream_serves_view(client: TestClient):
    root = client.get("/")
    assert root.status_code == 200 and "drive setup" in root.text
    assert 'id="view"' in root.text and "three.module.min.js" in root.text
    stream = client.get("/stream")
    assert stream.status_code == 200 and "live pixel stream" in stream.text
    # self-hosted three.js is served (no external CDN)
    v = client.get("/vendor/three.module.min.js")
    assert v.status_code == 200 and len(v.content) > 100_000


def test_procedural_preview_is_retired(client: TestClient):
    response = client.get("/preview/procedural?seed=1")
    assert response.status_code == 404
    assert "z" not in response.json()
