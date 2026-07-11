"""[REQ:] viz2 PRD Phase E — WorkSite dig/dump moved-mass counters (E1) + the signed before/after
difference field (E2), on the REAL Haworth SfS 1 m bundle (no synthetic terrain).

E1: the cumulative CUT/PLACED counters are additive and DISTINCT from the residual drum ledger — a
dig-then-dump-in-place returns ``inventory_kg`` to ~0 while ``cut_total_kg`` keeps the gross cut mass
(the round-3 fact the E3 evidence contract rests on). Mass stays conserved across the whole run.

E2: ``window_virgin_height`` regenerates the deterministic un-worked surface (BYTE-IDENTICAL to a
fresh window), and ``diff_field`` = h_now - h_virgin reads NEGATIVE in a cut and POSITIVE on a berm.
"""
from __future__ import annotations

import os

import numpy as np
import pytest

import stewie.specs.constants as K
from stewie.physics.worksite import WorkSite

_SAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "samples", "lunar_dem")
SFS = os.path.join(_SAMPLES, "haworth_sfs_2km_1m")

pytestmark = pytest.mark.skipif(not os.path.isdir(SFS), reason="real Haworth SfS bundle not on disk")


def _centered_worksite() -> WorkSite:
    ws = WorkSite.from_haworth_bundle(SFS, fine_cell_m=0.05, tile_base_cells=4)
    cx = ws.world_x0 + 0.5 * ws.base.width * ws.base_cell_m
    cy = ws.world_y0 + 0.5 * ws.base.height * ws.base_cell_m
    ws.recenter((cx, cy))
    return ws


def _box(H: int, W: int, r: int, c: int, hc: int = 8) -> np.ndarray:
    m = np.zeros((H, W), dtype=bool)
    m[max(0, r - hc):min(H, r + hc + 1), max(0, c - hc):min(W, c + hc + 1)] = True
    return m


# -- E1: moved-mass counters -----------------------------------------------------------------

def test_flatten_advances_cut_total_and_conserves_mass():
    ws = _centered_worksite()
    f = ws.fine
    assert ws.cut_total_kg == 0.0 and ws.placed_total_kg == 0.0
    base_resid = ws.conservation_residual()
    mask = _box(f.height, f.width, f.height // 2, f.width // 2)
    target = float(f.derive_height()[mask].min()) - 0.12
    moved = ws.flatten(mask, target)
    assert moved > 0.0
    # the counter grew by EXACTLY the returned moved mass; the drum ledger holds it too (pre-dump)
    assert ws.cut_total_kg == pytest.approx(moved, rel=0, abs=0)
    assert ws.inventory_kg == pytest.approx(moved, rel=1e-12)
    assert ws.placed_total_kg == 0.0
    # mass conserved across the cut (grid loss == drum gain)
    assert ws.conservation_residual() <= base_resid + 1e-6 * max(1.0, ws.total_mass())


def test_dig_then_dump_in_place_counters_are_distinct_from_the_residual_ledger():
    """cut_total_kg keeps the GROSS cut mass; the residual inventory_kg returns to ~0 after the dump;
    placed_total_kg records what landed — the three are proven distinct (the round-3 §0.5 fact)."""
    ws = _centered_worksite()
    f = ws.fine
    mA = _box(f.height, f.width, f.height // 2, f.width // 3)
    cut = ws.flatten(mA, float(f.derive_height()[mA].min()) - 0.12)
    mB = _box(f.height, f.width, f.height // 2, 2 * f.width // 3)
    placed = ws.dump(mB)                                  # dump the whole drum onto a separate berm
    assert cut > 0.0 and placed > 0.0
    assert ws.cut_total_kg == pytest.approx(cut, rel=1e-12)        # gross cut, unchanged by the dump
    assert ws.placed_total_kg == pytest.approx(placed, rel=1e-12)  # SEPARATE quantity
    assert ws.inventory_kg == pytest.approx(0.0, abs=1e-6)         # residual ledger drained
    assert ws.conservation_residual() < 1e-6 * max(1.0, ws.total_mass())


# -- E2: virgin regen + signed diff drape ----------------------------------------------------

def test_window_virgin_height_is_byte_identical_on_a_fresh_window():
    ws = _centered_worksite()
    fresh = ws.fine.derive_height().copy()
    virgin = ws.window_virgin_height()
    assert np.array_equal(virgin, fresh)                 # fresh window == its deterministic virgin
    assert float(np.abs(ws.diff_field()).max()) == 0.0   # so the diff drape is flat before any work


def test_diff_field_is_negative_in_a_cut_and_positive_on_a_berm():
    ws = _centered_worksite()
    f = ws.fine
    virgin_before = ws.window_virgin_height().copy()
    mA = _box(f.height, f.width, f.height // 2, f.width // 3)
    ws.flatten(mA, float(f.derive_height()[mA].min()) - 0.12)
    d_cut = ws.diff_field()
    assert float(d_cut.min()) < -0.05                    # a real trench below virgin
    assert float(d_cut[mA].max()) <= 1e-12               # the cut footprint never rises
    # virgin regen is STABLE after the cut (deterministic — the drape diffs against the same baseline)
    assert np.array_equal(ws.window_virgin_height(), virgin_before)
    mB = _box(f.height, f.width, f.height // 2, 2 * f.width // 3)
    ws.dump(mB)
    d = ws.diff_field()
    assert float(d.min()) < -0.05                        # cut still reads negative
    assert float(d.max()) > 0.05                         # berm reads positive
    # spoil BULKS (RHO_SPOIL < in-situ), so the berm rises higher than the cut is deep
    assert float(d.max()) > abs(float(d.min())) - 1e-9
    assert K.RHO_SPOIL <= float(f.density.mean())        # sanity on the bulking premise
