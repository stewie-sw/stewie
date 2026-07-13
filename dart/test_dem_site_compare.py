"""viz2 PRD Phase G (G2 / G2a / G4) — cross-site DEM comparison, over the REAL on-disk bundles.

Every assertion runs against the real ``samples/lunar_dem/`` bundles (no synthetic terrain, no
fabricated stats). The gate: the compare table's rows are exactly the bundles on disk; each row's
citation is echoed VERBATIM from that bundle's ``metadata.json`` (the SfS tile carries Alexandrov &
Beyer, NOT LOLA; the LOLA tiles carry Barker/Mazarico); a residual is produced ONLY where footprints
truly overlap, else the explicit refusal path; and G2a is either a real residual or an honest BLOCKED.
"""
from __future__ import annotations

import json
import os

import numpy as np
import pytest

from dart import dem_site_compare as dsc


def _meta(bundle: str) -> dict:
    with open(os.path.join(bundle, "metadata.json")) as fh:
        return json.load(fh)


# --- G2: the compare table rows == the on-disk bundles (count + names) --------------------------

def test_table_rows_are_exactly_the_on_disk_bundles():
    bundles = dsc.list_site_bundles()
    assert len(bundles) >= 4, "expected the committed lunar_dem bundles on disk"
    rows = dsc.compare_table()
    assert len(rows) == len(bundles)
    assert [r.name for r in rows] == [os.path.basename(b) for b in bundles]
    # the known committed set is present (4 populated + at least the SfS + LOLA sites)
    names = {r.name for r in rows}
    assert "haworth_sfs_2km_1m" in names
    assert "haworth_10km_5m" in names


# --- G2/G4: each row's citation == that bundle's metadata dem_provenance.citation, VERBATIM ------

def test_every_row_citation_matches_its_bundle_metadata_verbatim():
    for bundle in dsc.list_site_bundles():
        m = _meta(bundle)
        want = (m.get("dem_provenance", {}) or {}).get("citation", "")
        row = dsc.site_stat(bundle)
        assert row.citation == want, f"{row.name}: citation must be verbatim from metadata"


def test_sfs_bundle_cites_alexandrov_beyer_not_lola():
    row = dsc.site_stat(os.path.join(dsc.DEFAULT_SITE_ROOT, "haworth_sfs_2km_1m"))
    assert "Alexandrov" in row.citation and "Beyer" in row.citation
    # the SfS tile is photoclinometry, NOT the LOLA-altimetry Barker/Mazarico product
    assert "Barker" not in row.citation
    assert "Shape-from-Shading" in row.citation or "photoclinometry" in row.citation


def test_lola_bundles_cite_barker_mazarico_not_sfs():
    for name in ("haworth_10km_5m", "nobile_rim1_10km_5m", "shackleton_rim_10km_5m"):
        row = dsc.site_stat(os.path.join(dsc.DEFAULT_SITE_ROOT, name))
        assert "Barker" in row.citation and "Mazarico" in row.citation, name
        assert "Alexandrov" not in row.citation, name


# --- G2: slope/roughness from the REAL producers; metadata-only bundles report None honestly -----

def test_populated_bundles_carry_real_slope_and_roughness():
    row = dsc.site_stat(os.path.join(dsc.DEFAULT_SITE_ROOT, "shackleton_rim_10km_5m"))
    assert row.has_heightmap
    # real slope/roughness, finite and physically ordered (a steep polar rim: high median slope)
    assert row.slope_median_deg is not None and 0.0 < row.slope_median_deg < 90.0
    assert row.slope_rms_deg is not None and row.slope_rms_deg > 0.0
    assert row.roughness_median_m is not None and row.roughness_median_m > 0.0
    assert row.relief_m > 0.0


def test_slope_matches_the_real_producer_independently():
    # independent recompute via the SAME real producer the module reuses
    from stewie.terrain.site_dem import load_haworth_dem, slope_deg_map
    bundle = os.path.join(dsc.DEFAULT_SITE_ROOT, "haworth_10km_5m")
    Z, cell = load_haworth_dem(bundle_dir=bundle)
    want = float(np.median(slope_deg_map(Z, cell)))
    row = dsc.site_stat(bundle)
    assert row.slope_median_deg == pytest.approx(want, rel=0, abs=1e-9)


def test_metadata_only_bundle_reports_none_slope_not_zero():
    dg = os.path.join(dsc.DEFAULT_SITE_ROOT, "de_gerlache_kocher_10km_5m")
    if not os.path.isdir(dg) or os.path.exists(os.path.join(dg, "heightmap.rf32")):
        pytest.skip("de_gerlache_kocher metadata-only bundle not present as expected")
    row = dsc.site_stat(dg)
    assert row.has_heightmap is False
    assert row.slope_median_deg is None and row.roughness_median_m is None
    # height range still honestly carried from metadata
    assert np.isfinite(row.relief_m)


# --- G2: a residual ONLY where footprints overlap; else the explicit refusal path ---------------

def test_all_committed_pairs_are_disjoint_and_refuse():
    report = dsc.pairwise_residual_report()
    assert len(report) >= 6
    for p in report:
        # the bundled sites are disjoint craters -> every pair refuses, none produces a residual
        assert p["overlap"] is False
        assert "disjoint" in p["reason"]


def test_disjoint_pair_refuses_with_reason():
    a = os.path.join(dsc.DEFAULT_SITE_ROOT, "haworth_10km_5m")
    b = os.path.join(dsc.DEFAULT_SITE_ROOT, "nobile_rim1_10km_5m")
    r = dsc.site_residual(a, b)
    assert r["overlap"] is False and r["reason"]
    assert "n" not in r  # no residual stats when refused


def test_overlap_pair_produces_a_real_residual_self_is_zero():
    # the honest overlap case: a DEM differenced against itself is a full overlap and MUST be 0
    b = os.path.join(dsc.DEFAULT_SITE_ROOT, "haworth_10km_5m")
    r = dsc.site_residual(b, b, keep_array=True)
    assert r["overlap"] is True and r["reason"] == ""
    assert r["n"] > 0
    assert r["rms_m"] == 0.0 and r["max_abs_m"] == 0.0
    assert np.all(r["residual_m"] == 0.0)


def test_metadata_only_overlap_refuses_no_heightmap():
    dg = os.path.join(dsc.DEFAULT_SITE_ROOT, "de_gerlache_kocher_10km_5m")
    if not os.path.isdir(dg) or os.path.exists(os.path.join(dg, "heightmap.rf32")):
        pytest.skip("de_gerlache_kocher metadata-only bundle not present as expected")
    r = dsc.site_residual(dg, dg)
    assert r["overlap"] is True  # identical footprint overlaps
    assert "metadata-only" in r["reason"]  # but cannot difference without a heightmap


def test_footprint_overlap_geometry():
    assert dsc.footprint_overlap((0, 0, 10, 10), (5, 5, 20, 20)) == (5, 5, 10, 10)
    assert dsc.footprint_overlap((0, 0, 10, 10), (10, 10, 20, 20)) is None  # zero-area touch
    assert dsc.footprint_overlap((0, 0, 10, 10), (20, 20, 30, 30)) is None  # disjoint


# --- G2a: the 1 m SfS vs 5 m LOLA residual — real when the source is on host, else BLOCKED -------

def test_g2a_blocked_when_raw_source_missing():
    r = dsc.haworth_1m_vs_5m_residual(raw_5m_src="/no/such/haworth_5mpp.tif")
    assert r["blocked"] is True
    assert "raw 5 m Haworth source not on host" in r["reason"]


def test_g2a_real_residual_when_source_present():
    if not os.path.exists(dsc.DEFAULT_HAWORTH_5M_SRC):
        pytest.skip(f"raw 5 m Haworth source not on host at {dsc.DEFAULT_HAWORTH_5M_SRC} (G2a BLOCKED)")
    r = dsc.haworth_1m_vs_5m_residual()
    assert r["blocked"] is False
    assert r["n"] > 0
    # SfS-vs-LOLA absolute error at the ~1 m scale (Alexandrov & Beyer 2018 §5.4) — a real residual,
    # bounded well away from both 0 (would mean identical products) and absurdity
    assert 0.1 < r["rms_m"] < 5.0
    assert r["max_abs_m"] > r["rms_m"]
    assert "Alexandrov" in r["a_citation"]  # the SfS side's verbatim provenance


# --- G4: provenance pane echoes the verbatim citation --------------------------------------------

def test_provenance_pane_is_verbatim():
    for bundle in dsc.list_site_bundles():
        m = _meta(bundle)
        prov = m.get("dem_provenance", {}) or {}
        pane = dsc.provenance_pane(bundle)
        assert pane["citation"] == prov.get("citation", "")
        assert pane["source"] == prov.get("source", "")
        assert pane["region"] == m.get("region", "")
