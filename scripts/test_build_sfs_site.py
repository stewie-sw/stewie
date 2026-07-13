"""[viz2 A2 + A3a + M-7] Real Haworth 1 m SfS drive-site bundle + honest DEM provenance.

TDD gates for three tasks (viz2 driveable-sim plan v4):

* **A3a** — ``dart.dem_sources.DemSource`` gains an additive ``citation`` field, and the
  ``lroc_nac_sfs_1m`` row carries the correct Shape-from-Shading citation (USGS Astrogeology
  LRO NAC photoclinometry DEM; method Alexandrov & Beyer 2018, Earth & Space Sci. 5:652).
* **A2**  — a ~2 km @ 1 m site bundle cropped INSIDE the real SfS footprint, emitted with
  SfS provenance, registered in ``stewie.specs.sites`` + the ``dem_sources`` catalog.
* **M-7** — the emitted ``dem_provenance`` asserts SfS / Alexandrov-Beyer and NEVER carries
  the false LOLA Product-78 / Barker-Mazarico provenance ``build_from_dem.build`` hard-codes.

Real data only: the crop is read (windowed, no 140 Mpx full load) off the real on-host
``Lunar_LROnac_Haworth_sfs-dem_1m_v3.tif``; the build-path tests skip where it is absent
(CI), while the committed-bundle + registry gates always run.

Run: PYTHONPATH=<worktree> <venv>/bin/python -m pytest scripts/test_build_sfs_site.py -q
"""
from __future__ import annotations

import json
import os

import numpy as np
import pytest

from dart import dem_sources as S
from stewie.dataset.dem_source import GeoTiffWindowReader, resolve_dem_path

# The verified real SfS footprint (IAU_2015:30135 m), read off the GeoTIFF tags: the crop must
# lie fully inside it. Matches the plan's stated bounds X[-40120,-28460] Y[83260,95320].
_SFS_FOOTPRINT = {"x0": -40120.0, "x1": -28460.0, "y0": 83260.0, "y1": 95320.0}

_SITE = "haworth_sfs"
_SOURCE_ID = "haworth_sfs_2km_1m"
_BUNDLE_NAME = "haworth_sfs_2km_1m"
_CENTER = (-34290.0, 89290.0)           # inside the SfS bounds (plan v4 A2)
_EXTENT_M = 2000.0                       # ~2 km
_CELL_M = 1.0

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_COMMITTED = os.path.join(_REPO_ROOT, "samples", "lunar_dem", _BUNDLE_NAME)

_FORBIDDEN = ("lola", "product 78", "product-78", "barker", "mazarico")


def _assert_sfs_not_lola(prov: dict) -> None:
    """The M-7 regression gate: SfS/Alexandrov-Beyer present, LOLA/Product-78/Barker absent."""
    blob = json.dumps(prov).lower()
    assert "alexandrov" in blob, f"dem_provenance must cite Alexandrov & Beyer (SfS): {prov}"
    assert ("shape-from-shading" in blob or "photoclinometry" in blob or "sfs" in blob), \
        f"dem_provenance must name the SfS/photoclinometry method: {prov}"
    for bad in _FORBIDDEN:
        assert bad not in blob, f"dem_provenance falsely carries {bad!r} (LOLA provenance): {prov}"


# ---------------------------------------------------------------------------------------------
# A3a — the DemSource.citation field + the SfS row.
# ---------------------------------------------------------------------------------------------

def test_demsource_has_additive_citation_field_defaulting_empty():
    # additive: pre-existing rows keep an empty citation (no behavior change) unless populated
    src = S.DemSource(id="x", name="x", instrument="LOLA", resolution_m=5.0, coverage="x",
                      crs="south_polar_stereographic", fmt="geotiff_cog",
                      access_url="http://x", license="x", ingest="dem_import")
    assert src.citation == ""


def test_sfs_source_row_cites_alexandrov_beyer_not_lola():
    s = S.dem_source("lroc_nac_sfs_1m")
    cit = s.citation
    assert cit, "lroc_nac_sfs_1m must carry a citation (A3a)"
    low = cit.lower()
    assert "alexandrov" in low and ("photoclinometry" in low or "shape-from-shading" in low)
    assert "usgs" in low, "cite the USGS Astrogeology product"
    for bad in _FORBIDDEN:
        assert bad not in low, f"SfS citation must not carry {bad!r}: {cit}"


def test_sfs_bundle_source_row_registered_and_planning_grade():
    s = S.dem_source(_SOURCE_ID)
    assert s.bundled and s.planning_grade
    assert s.instrument == "LROC NAC" and s.resolution_m == 1.0
    assert s.crs == "south_polar_stereographic"
    assert "alexandrov" in s.citation.lower()
    for bad in _FORBIDDEN:
        assert bad not in s.citation.lower()


# ---------------------------------------------------------------------------------------------
# A2 / M-7 — the emitted bundle, built fresh from the real SfS DEM (skips without the tif).
# ---------------------------------------------------------------------------------------------

@pytest.mark.skipif(resolve_dem_path() is None, reason="real Haworth 1 m SfS DEM absent on this host")
def test_build_from_source_emits_sfs_provenance_and_inside_footprint(tmp_path):
    from scripts import build_from_dem as B

    out = str(tmp_path / _BUNDLE_NAME)
    meta = B.build_from_source(out, source_id="lroc_nac_sfs_1m", center_xy=_CENTER,
                               extent_m=_EXTENT_M, base_cell_m=_CELL_M)
    # M-7: provenance is SfS, never LOLA
    _assert_sfs_not_lola(meta["dem_provenance"])
    # A2: world_bounds strictly inside the SfS footprint
    wb = meta["world_bounds_m"]
    assert _SFS_FOOTPRINT["x0"] <= wb["x0"] < wb["x1"] <= _SFS_FOOTPRINT["x1"], wb
    assert _SFS_FOOTPRINT["y0"] <= wb["y0"] < wb["y1"] <= _SFS_FOOTPRINT["y1"], wb
    # a ~2 km tile at 1 m
    assert meta["base_cell_m"] == 1.0
    assert abs((wb["x1"] - wb["x0"]) - _EXTENT_M) <= _CELL_M
    # the on-disk scene loaded back matches
    on_disk = json.load(open(os.path.join(out, "metadata.json")))
    _assert_sfs_not_lola(on_disk["dem_provenance"])


@pytest.mark.skipif(resolve_dem_path() is None, reason="real Haworth 1 m SfS DEM absent on this host")
def test_build_from_source_heightmap_roundtrips_to_the_source_window(tmp_path):
    from scripts import build_from_dem as B
    from stewie.twin.io_fields import load_scene

    out = str(tmp_path / _BUNDLE_NAME)
    meta = B.build_from_source(out, source_id="lroc_nac_sfs_1m", center_xy=_CENTER,
                               extent_m=_EXTENT_M, base_cell_m=_CELL_M)
    fields, _ = load_scene(out)
    hm = np.asarray(fields["heightmap"], dtype=np.float64)

    # re-read the SAME source window the bundle recorded and compare (native 1 m -> no resample)
    r0, c0 = meta["dem_provenance"]["crop_window_row0_col0"]
    n = hm.shape[0]
    src_win = GeoTiffWindowReader(resolve_dem_path())(r0, c0, n, n).astype(np.float64)
    assert np.isfinite(src_win).all(), "the committed crop window must be fully finite (no NoData)"
    err = float(np.max(np.abs(hm - src_win)))
    assert err <= 1e-3, f"heightmap deviates from the source window by {err:.3e} m (> 1e-3)"


# ---------------------------------------------------------------------------------------------
# A2 — the COMMITTED bundle + site registration (always run; no source tif needed).
# ---------------------------------------------------------------------------------------------

def test_committed_sfs_bundle_provenance_is_sfs_and_inside_footprint():
    meta_path = os.path.join(_COMMITTED, "metadata.json")
    assert os.path.exists(meta_path), f"the committed SfS bundle is missing: {_COMMITTED}"
    meta = json.load(open(meta_path))
    _assert_sfs_not_lola(meta["dem_provenance"])                 # M-7 on the committed artifact
    wb = meta["world_bounds_m"]
    assert _SFS_FOOTPRINT["x0"] <= wb["x0"] < wb["x1"] <= _SFS_FOOTPRINT["x1"], wb
    assert _SFS_FOOTPRINT["y0"] <= wb["y0"] < wb["y1"] <= _SFS_FOOTPRINT["y1"], wb
    assert meta["base_cell_m"] == 1.0 and meta["grid"]["cell_m"] == 1.0


def test_sfs_site_resolves_via_the_registry():
    from stewie.specs.sites import SITES, get_site
    from stewie.terrain.site_dem import bundle_for_site, load_site_dem

    assert _SITE in SITES
    s = get_site(_SITE)
    assert s.bundle_dir and os.path.isdir(s.bundle_dir)
    assert os.path.abspath(bundle_for_site(_SITE)) == os.path.abspath(_COMMITTED)
    Z, cell = load_site_dem(_SITE)
    assert cell == 1.0 and Z.shape == (2000, 2000)
    assert np.isfinite(Z).all()
