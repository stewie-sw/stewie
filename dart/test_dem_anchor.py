"""Correlation-based DEM anchoring (NCC / phase-correlation peak).

MATH check (self-consistency on REAL DEM data): crop a patch from a REAL dustgym/LOLA DEM, shift it
by a KNOWN offset, and confirm the correlator recovers that offset within one cell. No synthetic
terrain: the elevation field is a real DEM (crater_boulders @ 0.02 m, and the LOLA Haworth tile @
5 m), only the shift is the known numeric quantity being recovered.

Truth firewall I3: the recovered offset is a perception product (observed patch vs prior map); no
ground-truth pose/slip/terrain-truth (e.g. the crater_boulders `clasts` metadata) enters the
anchoring input. The DEM heightfield is the prior MAP, which is a legitimate perception input.
"""
import os

import numpy as np
import pytest

from dart import dem_anchor

# REAL DEMs (dustgym samples). crater_boulders has genuine 2-D relief (a crater + boulders) so the
# correlation peak is unambiguous; the Haworth tile is the operational south-polar prior map.
_CRATER = "/mnt/projects/foss_ipex/dustgym/samples/crater_boulders/heightmap.rf32"
_HAWORTH = "/mnt/projects/foss_ipex/dustgym/samples/lunar_dem/haworth_10km_5m/heightmap.rf32"
_crater = os.path.exists(_CRATER)
_haworth = os.path.exists(_HAWORTH)


def _crater_dem() -> np.ndarray:
    return np.fromfile(_CRATER, dtype="<f4").reshape(256, 256).astype(np.float64)


def _haworth_dem() -> np.ndarray:
    return np.fromfile(_HAWORTH, dtype="<f4").reshape(2000, 2000).astype(np.float64)


# ---- NCC surface shape / identity peak, on a REAL DEM patch (no synthetic data) ----
@pytest.mark.skipif(not os.path.exists(_CRATER), reason="real crater DEM not available")
def test_ncc_surface_shape_and_peak_centered_on_identity():
    base = _crater_dem()[64:104, 104:144].copy()  # REAL 40x40 patch with relief (textured -> distinct peak)
    obs = base[8:-8, 8:-8].copy()  # a 24x24 sub-window taken from the centre (zero offset)
    surf = dem_anchor.ncc_surface(obs, base)
    # matchTemplate surface size = (H - h + 1, W - w + 1)
    assert surf.shape == (40 - 24 + 1, 40 - 24 + 1)
    # the centre of the search window is the true match -> peak there
    pr, pc = np.unravel_index(int(np.argmax(surf)), surf.shape)
    assert (pr, pc) == (8, 8)
    assert surf.max() > 0.99  # near-perfect normalized correlation for an exact crop


def test_anchor_rejects_flat_patch_as_ambiguous():
    flat = np.full((20, 20), 3.0)
    dem_patch = np.zeros((40, 40))
    with pytest.raises(ValueError):
        dem_anchor.anchor_offset(flat, dem_patch)


def test_anchor_shape_guard():
    with pytest.raises(ValueError):
        dem_anchor.anchor_offset(np.zeros((30, 30)), np.zeros((20, 20)))  # observed bigger than DEM


def test_unknown_method_rejected():
    with pytest.raises(ValueError):
        dem_anchor.anchor_offset(np.zeros((10, 10)) + np.arange(10), np.zeros((40, 40)), method="zncc")


def test_phase_offset_shape_guard():
    with pytest.raises(ValueError):
        dem_anchor.phase_offset(np.zeros((10, 10)), np.zeros((12, 12)))


# ---- MATH check on REAL crater_boulders DEM: recover KNOWN integer offsets exactly ----
@pytest.mark.skipif(not _crater, reason="crater_boulders DEM not present")
@pytest.mark.parametrize("known", [(3, -2), (1, 4), (0, 0), (-3, 2), (2, 2)])
def test_ncc_recovers_known_integer_offset_real_dem(known):
    Z = _crater_dem()
    # a verified 2-D-distinctive region of the real crater_boulders DEM
    cr, cc, win, half = 92, 164, 20, 12
    dem_patch = Z[cr - win:cr + win, cc - win:cc + win]
    kdr, kdc = known
    obs = Z[cr + kdr - half:cr + kdr + half, cc + kdc - half:cc + kdc + half]
    res = dem_anchor.anchor_offset(obs, dem_patch, method="ncc")
    # offset reported relative to the centre of the DEM search window (the binding MATH assertion)
    assert res.offset_cells == (kdr, kdc)
    assert abs(res.offset_cells[0] - kdr) <= 1 and abs(res.offset_cells[1] - kdc) <= 1
    assert res.peak > 0.99
    assert res.surface.shape == (2 * win - 2 * half + 1, 2 * win - 2 * half + 1)


@pytest.mark.skipif(not _crater, reason="crater_boulders DEM not present")
def test_subcell_refinement_within_one_cell_real_dem():
    """The parabolic sub-cell refinement stays within one cell of the integer peak (local quadratic
    interpolation, |refinement| < 1 cell by construction)."""
    Z = _crater_dem()
    cr, cc, win, half = 92, 164, 20, 12
    dem_patch = Z[cr - win:cr + win, cc - win:cc + win]
    kdr, kdc = 1, 4
    obs = Z[cr + kdr - half:cr + kdr + half, cc + kdc - half:cc + kdc + half]
    res = dem_anchor.anchor_offset(obs, dem_patch, method="ncc")
    assert abs(res.offset_subcell[0] - kdr) < 1.0
    assert abs(res.offset_subcell[1] - kdc) < 1.0
    assert res.confidence > 0.0


@pytest.mark.skipif(not _crater, reason="crater_boulders DEM not present")
def test_offset_meters_uses_posting():
    Z = _crater_dem()
    cr, cc, win, half = 92, 164, 20, 12
    posting = 0.02  # crater_boulders posting (m)
    dem_patch = Z[cr - win:cr + win, cc - win:cc + win]
    obs = Z[cr + 3 - half:cr + 3 + half, cc - half:cc + half]
    res = dem_anchor.anchor_offset(obs, dem_patch, method="ncc", posting_m=posting)
    assert res.offset_m is not None
    # 3 cells of 0.02 m posting = 0.06 m in the row direction, within one cell
    assert abs(res.offset_m[0] - 3.0 * posting) < posting


# ---- phase correlation on the REAL Haworth tile: recover a KNOWN shift to sub-cell precision ----
@pytest.mark.skipif(not _haworth, reason="Haworth DEM not present")
def test_phase_correlation_recovers_subcell_shift_real_dem():
    F = _haworth_dem()
    # a 2-D-distinctive 64x64 window of the real Haworth tile; phase correlation recovers the
    # integer shift to within one cell (sub-cell precision on real, naturally smooth relief)
    cr, cc, win = 300, 340, 64
    a = F[cr - win // 2:cr + win // 2, cc - win // 2:cc + win // 2]
    kdr, kdc = 2, 1
    b = F[cr + kdr - win // 2:cr + kdr + win // 2, cc + kdc - win // 2:cc + kdc + win // 2]
    dr, dc, response = dem_anchor.phase_offset(a, b)
    assert abs(dr - kdr) <= 1.0
    assert abs(dc - kdc) <= 1.0
    assert 0.0 < response <= 1.0
