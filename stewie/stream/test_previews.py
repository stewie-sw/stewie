"""[REQ:] viz2 setup-screen backend — /bundles + /preview/heightmap + /preview/procedural.

Gate on exit code: pytest stewie/stream/test_previews.py

Real data only. Asserts the three producers the three.js setup screen consumes:
  * /bundles lists the REAL samples/lunar_dem bundles with their REAL citations and NO synthetic;
  * /preview/heightmap?site=haworth_sfs_2km_1m returns a non-empty REAL heightmap whose stats match
    the on-disk bundle;
  * /preview/procedural runs the REAL fbm_global (bit-exact with a direct call), is labelled
    SYNTHETIC with a null citation, and changes when the seed changes.
No mock terrain, no fabricated stats — every value is read off the real bundles / the real generator.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile

import numpy as np
import pytest
from fastapi.testclient import TestClient

from stewie.stream import previews
from stewie.stream.app import app
from stewie.terrain.procgen_seed import fbm_global

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


def test_bundles_excludes_a_real_synthetic_bundle(tmp_path):
    """The shared dem_site_compare filter must drop a genuinely-synthetic bundle even if it sits in
    the site root. Uses the REAL procedural generator (no fabricated metadata)."""
    from stewie.terrain.procedural_bundle import generate_procedural_bundle
    root = str(tmp_path / "sites")
    os.makedirs(root)
    # a REAL bundle: only its metadata.json is needed for enumeration
    real_meta = json.load(open(os.path.join(SAMPLES, "haworth_10km_5m", "metadata.json")))
    os.makedirs(os.path.join(root, "haworth_10km_5m"))
    with open(os.path.join(root, "haworth_10km_5m", "metadata.json"), "w") as fh:
        json.dump(real_meta, fh)
    # a REAL synthetic bundle produced by the actual generator, then its metadata dropped into root
    sandbox = tempfile.mkdtemp(prefix="viz2_syn_test_")
    try:
        generate_procedural_bundle(os.path.join(sandbox, "syn_site"), world_seed=3,
                                   extent_m=32.0, cell_m=1.0, write_previews=False)
        syn_meta = json.load(open(os.path.join(sandbox, "syn_site", "metadata.json")))
        os.makedirs(os.path.join(root, "syn_site"))
        with open(os.path.join(root, "syn_site", "metadata.json"), "w") as fh:
            json.dump(syn_meta, fh)
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)

    rows = previews.list_real_bundles(root=root)
    names = {b["name"] for b in rows}
    assert "haworth_10km_5m" in names          # real bundle listed
    assert "syn_site" not in names             # synthetic bundle EXCLUDED (guardrail)


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
def test_preview_procedural_matches_direct_fbm_global(client: TestClient):
    seed = 7
    H, wl, amp, oct_ = 0.9, 40.0, 8.0, 6
    r = client.get(f"/preview/procedural?seed={seed}&H={H}&wavelength={wl}&amplitude={amp}&octaves={oct_}")
    assert r.status_code == 200
    d = r.json()
    # labelled SYNTHETIC, null citation (guardrail)
    assert d["synthetic"] is True
    assert d["label"] == "SYNTHETIC"
    assert d["citation"] is None
    assert "PROCEDURAL" in d["source"]
    assert d["provenance"]["synthetic"] is True and d["provenance"]["citation"] is None
    # bit-exact with a DIRECT fbm_global call using the module's documented preview window
    got = np.array(d["z"], dtype=np.float64).reshape(d["n"], d["ncols"])
    ref = fbm_global(
        previews.PREVIEW_WORLD_X0, previews.PREVIEW_WORLD_Y0, previews.PREVIEW_N,
        previews.PREVIEW_CELL_M, H=H, nu0=amp * amp, world_seed=seed, octaves=oct_,
        base_wavelength_m=wl, lacunarity=previews.PREVIEW_LACUNARITY,
        base_cell_class=previews.PREVIEW_BASE_CELL_CLASS)
    assert got.shape == ref.shape == (previews.PREVIEW_N, previews.PREVIEW_N)
    assert np.array_equal(got, ref), "preview heightmap is not bit-exact with fbm_global"


def test_preview_procedural_seed_changes_terrain(client: TestClient):
    base = "H=0.9&wavelength=40&amplitude=8&octaves=6"
    a = np.array(client.get(f"/preview/procedural?seed=1&{base}").json()["z"])
    b = np.array(client.get(f"/preview/procedural?seed=2&{base}").json()["z"])
    assert a.shape == b.shape
    assert not np.array_equal(a, b), "changing the world_seed must change the terrain"
    assert float(np.abs(a - b).max()) > 1e-3


def test_preview_procedural_rejects_bad_params(client: TestClient):
    # H out of (0,1] and octaves < 1 are rejected by the real _normalize_params validation
    assert client.get("/preview/procedural?seed=0&H=1.5&wavelength=40&amplitude=8&octaves=6").status_code == 400
    assert client.get("/preview/procedural?seed=0&H=0.9&wavelength=0&amplitude=8&octaves=6").status_code == 400
    assert client.get("/preview/procedural?seed=0&H=0.9&wavelength=40&amplitude=8&octaves=0").status_code == 400


def test_root_serves_setup_and_stream_serves_view(client: TestClient):
    root = client.get("/")
    assert root.status_code == 200 and "drive setup" in root.text
    assert 'id="view"' in root.text and "three.module.min.js" in root.text
    stream = client.get("/stream")
    assert stream.status_code == 200 and "live pixel stream" in stream.text
    # self-hosted three.js is served (no external CDN)
    v = client.get("/vendor/three.module.min.js")
    assert v.status_code == 200 and len(v.content) > 100_000
