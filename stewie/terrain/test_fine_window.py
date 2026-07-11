"""[REQ:] 2 cm-fine overlay on a REAL DEM window (stewie.terrain.fine_window) — the viz2
``--fine on|off`` producer.

fine ON must be CONSERVATION-BOUNDED (coarsen(fine) == the real DEM), carry the REAL citation
verbatim plus a fine_overlay disclosure, and add real sub-base detail. fine OFF must be a straight
real crop. Runs against the committed real Haworth SfS bundle (no synthetic terrain).
Run: pytest stewie/terrain/test_fine_window.py  (gate on exit code).
"""
from __future__ import annotations

import json
import os

import numpy as np
import pytest

from stewie.terrain import fine_window as fw

_REAL = os.path.join(fw._REPO_ROOT, "samples", "lunar_dem", "haworth_sfs_2km_1m")

pytestmark = pytest.mark.skipif(
    not os.path.exists(os.path.join(_REAL, "heightmap.rf32")),
    reason="real Haworth SfS bundle not on disk")


def test_fine_off_is_a_real_base_crop(tmp_path):
    fields, meta = fw.real_fine_window(_REAL, str(tmp_path / "off"), fine_on=False,
                                       window_cells=16, write_previews=False)
    assert meta["grid"]["cell_m"] == meta["base_cell_m"]     # base resolution
    assert meta["grid"]["width"] == 16 and meta["grid"]["height"] == 16
    assert "fine_overlay" not in meta                        # no overlay in off mode
    # citation is the REAL bundle's, verbatim
    real_meta = json.loads(open(os.path.join(_REAL, "metadata.json")).read())
    assert meta["dem_provenance"]["citation"] == real_meta["dem_provenance"]["citation"]
    assert "Alexandrov" in meta["dem_provenance"]["citation"]  # the real SfS provenance


def test_fine_on_is_conservation_bounded_and_2cm(tmp_path):
    fields, meta = fw.real_fine_window(_REAL, str(tmp_path / "on"), fine_on=True,
                                       window_cells=16, world_seed=0, write_previews=False)
    assert meta["grid"]["cell_m"] == pytest.approx(0.02)
    # 16 base cells @ 1 m, k = 50 -> 800 fine cells/side
    assert meta["grid"]["width"] == 800 and meta["grid"]["height"] == 800
    fo = meta["fine_overlay"]
    assert fo["enabled"] is True and fo["detail_synthetic"] is True
    assert fo["conservation_bounded"] is True
    cc = fo["conservation_check"]
    assert cc["coarsen_equals_real_dem"] is True
    assert cc["state_bit_exact"] is True
    assert cc["fbm_zero_mean_per_cell_max_m"] <= 1e-9   # fbm re-coarsens to 0 per base cell
    assert cc["coarsen_height_err_m"] <= 0.05           # surface coarsens to real DEM (upsample bound)
    # real sub-DEM detail (bicubic anti-alias + fbm roughness) added on the base, sub-1 m
    assert 0.0 < fo["added_detail_rms_m"] < 1.0


def test_fine_on_keeps_the_real_citation(tmp_path):
    _, meta = fw.real_fine_window(_REAL, str(tmp_path / "on2"), fine_on=True,
                                  window_cells=16, write_previews=False)
    real_meta = json.loads(open(os.path.join(_REAL, "metadata.json")).read())
    # a REAL-backbone window carries the REAL citation (it re-coarsens to that DEM), NOT null
    assert meta["dem_provenance"]["citation"] == real_meta["dem_provenance"]["citation"]
    assert meta["dem_provenance"].get("synthetic") in (None, False)  # NOT a synthetic bundle


def test_fine_on_coarsens_to_the_same_surface_as_fine_off(tmp_path):
    """The 2 cm overlay re-coarsens to the SAME real window surface the base crop shows (the
    conservation guarantee, checked at the height level)."""
    off_fields, off_meta = fw.real_fine_window(_REAL, str(tmp_path / "coff"), fine_on=False,
                                               window_cells=12, write_previews=False)
    on_fields, on_meta = fw.real_fine_window(_REAL, str(tmp_path / "con"), fine_on=True,
                                             window_cells=12, world_seed=0, write_previews=False)
    k = int(on_meta["fine_overlay"]["conservation_check"]["k"])
    fine_h = on_fields["heightmap"].astype(np.float64)
    coarse_h = fine_h.reshape(12, k, 12, k).mean(axis=(1, 3))
    off_h = off_fields["heightmap"].astype(np.float64)
    # the fine surface re-coarsens to the real base window within the bicubic-upsample bound
    assert np.max(np.abs(coarse_h - off_h)) < 0.05


def test_output_is_under_out_fine_window_not_samples(tmp_path):
    assert os.path.join("out", "fine_window") in os.path.normpath(fw._resolve_out_dir("x"))
    with pytest.raises(ValueError):
        fw._resolve_out_dir(os.path.join(fw._REPO_ROOT, "samples", "lunar_dem", "evil"))
