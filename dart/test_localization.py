"""Tests for map-relative localization (the scan-to-DEM 'overlay', P15 step 1).

Registers an observed elevation patch SENSED FROM THE CONSERVED-TRUTH DEM and recovers a perturbed pose --
no synthetic terrain (the real Haworth DEM is both the map and the truth the patch is sensed from). The flat
region uses a controlled zero patch to assert the ambiguity (low confidence) case.
"""
from __future__ import annotations

import numpy as np

from dart import localization as LOC
from lode import mission_planner as MP


def _textured_cell(Z, half):
    # a cell with real relief in its neighbourhood (so the match is well-conditioned), away from the edge
    H, W = Z.shape
    sub = Z[half + 5:H - half - 5, half + 5:W - half - 5]
    rr, cc = np.unravel_index(int(np.argmax(np.abs(np.gradient(sub)[0]))), sub.shape)
    return (rr + half + 5, cc + half + 5)


def test_recovers_a_perturbed_pose_on_real_haworth():
    dem = MP.load_haworth_dem(); Z, _cell = dem
    half = 6
    true_rc = _textured_cell(Z, half)
    observed = LOC.patch_at(Z, true_rc, half)                       # the rover senses the true terrain here
    guess_rc = (true_rc[0] + 3, true_rc[1] - 2)                     # ...but its belief has drifted
    out = LOC.register_to_dem(observed, dem, guess_rc, search_radius_cells=5)
    assert out["shift_cells"] == (-3, 2)                            # the correction recovers the drift exactly
    assert out["corrected_rc"] == true_rc                          # -> back to the true cell
    assert out["residual_rmse_m"] < 1e-6                           # an exact shape match
    assert out["confidence"] > 0.5                                 # textured terrain -> a sharp, confident peak


def test_drift_beyond_search_radius_is_not_fully_recovered():
    dem = MP.load_haworth_dem(); Z, _cell = dem
    half = 6
    true_rc = _textured_cell(Z, half)
    observed = LOC.patch_at(Z, true_rc, half)
    guess_rc = (true_rc[0] + 20, true_rc[1])                        # drift exceeds the +/-5 search window
    out = LOC.register_to_dem(observed, dem, guess_rc, search_radius_cells=5)
    assert abs(out["shift_cells"][0]) <= 5                          # bounded by the search radius (honest limit)
    assert out["corrected_rc"] != true_rc                          # cannot jump 20 cells -> not fully recovered


def test_flat_region_is_ambiguous_low_confidence():
    Z = np.zeros((40, 40), dtype=float)                            # a featureless flat map -> no shape to match
    observed = LOC.patch_at(Z, (20, 20), 6)
    out = LOC.register_to_dem(observed, (Z, 5.0), (22, 18), search_radius_cells=5)
    assert out["confidence"] == 0.0                               # ambiguous: every shift matches equally


def test_m06_out_of_bounds_candidate_patch_is_rejected_not_edge_clamped():
    """Audit M-06 (2026-06-14): a candidate whose full patch falls outside the map must be REJECTED, not
    edge-clamped. Clamping repeats the border rows/cols, which fabricates a low-SSD (high-confidence)
    match against any patch that happens to share the edge value -- a false fix off the map. patch_at
    must support a bounds-aware mode that flags out-of-bounds candidates, and register_to_dem must skip
    them so no high-confidence match can come from repeated edge cells."""
    import numpy as np
    from dart import localization as LOC

    # A map with a single sharp ridge column; everything else is flat 0. A patch taken from the FLAT
    # interior is featureless. Near the LEFT border the clamped candidates repeat column 0 (flat 0),
    # which matches the flat observed patch with SSD ~ 0 -> a fabricated confident off-map fix.
    Z = np.zeros((40, 40), dtype=float)
    Z[:, 25] = 10.0                                                # a distinctive ridge far from the border
    half = 4
    observed = LOC.patch_at(Z, (20, 10), half)                    # a flat interior patch (no ridge in it)

    # guess sits 2 cells from the left edge; the +/-5 search reaches candidates whose patch is partly
    # or fully off the left/top border.
    guess = (2, 2)

    # bounds-aware registration must NOT report a high-confidence fix built from clamped edge cells
    out = LOC.register_to_dem(observed, (Z, 5.0), guess, search_radius_cells=5)
    cr = out["corrected_rc"]
    # every reported correction must keep the FULL patch inside the map (no off-map clamped winner)
    assert half <= cr[0] <= Z.shape[0] - 1 - half
    assert half <= cr[1] <= Z.shape[1] - 1 - half

    # patch_at gains a bounds-aware mode: an out-of-bounds request is flagged, not silently clamped
    full_in = LOC.patch_at(Z, (20, 20), half, require_in_bounds=True)
    assert full_in is not None and full_in.shape == (2 * half + 1, 2 * half + 1)
    off_map = LOC.patch_at(Z, (1, 1), half, require_in_bounds=True)   # patch would run off the top-left
    assert off_map is None                                           # rejected, not edge-clamped

    # contrast: the legacy clamped path DOES manufacture a same-shape patch from repeated edge cells
    clamped = LOC.patch_at(Z, (1, 1), half)                          # default (clamped) still available
    assert clamped.shape == (2 * half + 1, 2 * half + 1)
    assert clamped[0, 0] == clamped[1, 0]                            # row 0 was repeated by the clamp
