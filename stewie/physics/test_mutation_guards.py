"""C-02 (audit 2026-06-13): conserved-state mutation boundaries reject negative/non-finite quantities.

The critical the audit probed: a negative cut returned -4 kg, INCREASED grid mass, and set drum
inventory to -4 kg (reversed mass flow); a NaN target poisoned mass_areal. Every authority mutation
now validates BEFORE touching the array. Valid positive transfers still work and conserve total mass
(grid + drum).
"""
import numpy as np
import pytest

from stewie.physics import rover as RV
from stewie.physics.column_state import ColumnState
from stewie.physics.sandpile import Sandpile


def _cs():
    cs = ColumnState(width=8, height=8, cell_m=0.5)
    cs.set_height_via_mass(np.full((8, 8), 0.5))   # ~0.5 m loose column everywhere
    return cs


def _mask():
    m = np.zeros((8, 8), bool)
    m[2:4, 2:4] = True
    return m


def test_cut_rejects_negative_and_nonfinite_but_allows_valid():
    cs = _cs()
    mask = _mask()
    with pytest.raises(ValueError):
        cs.cut_to_inventory(mask, -4.0)                 # would ADD mass + drive drum inventory negative
    with pytest.raises(ValueError):
        cs.cut_to_inventory(mask, np.nan)
    m0, d0 = cs.total_mass(), cs.drum_inventory
    moved = cs.cut_to_inventory(mask, 50.0)             # valid cut: grid -> drum, total conserved
    assert moved > 0 and cs.drum_inventory > d0 and abs(cs.total_mass() - m0) < 1e-9


def test_dump_rejects_negative_and_nonfinite():
    cs = _cs()
    mask = _mask()
    cs.cut_to_inventory(mask, 50.0)                     # fill the drum first
    with pytest.raises(ValueError):
        cs.dump_from_inventory(mask, -4.0)
    with pytest.raises(ValueError):
        cs.dump_from_inventory(mask, np.inf)
    assert cs.dump_from_inventory(mask, 10.0) > 0       # valid dump still works


def test_set_height_rejects_nonfinite_and_bad_shape():
    cs = _cs()
    with pytest.raises(ValueError):
        cs.set_height_via_mass(np.full((8, 8), np.nan))
    with pytest.raises(ValueError):
        cs.set_height_via_mass(np.zeros((4, 4)))        # wrong shape


def test_deposit_field_rejects_nonfinite():
    cs = _cs()
    mask = _mask()
    cs.cut_to_inventory(mask, 50.0)
    bad = np.full((8, 8), np.nan)
    with pytest.raises(ValueError):
        cs.deposit_field(mask, bad)


def test_drum_pass_rejects_negative_depth():
    cs = _cs()
    with pytest.raises(ValueError):
        RV.drum_pass(cs, [(4.0, 1.0), (4.0, 6.0)], depth_m=-0.1)
    assert RV.drum_pass(cs, [(4.0, 1.0), (4.0, 6.0)], depth_m=0.05) > 0   # valid


def test_sandpile_deposit_rejects_negative():
    cs = _cs()
    sp = Sandpile(cs)
    with pytest.raises(ValueError):
        sp.deposit(4, 4, -5.0)
    sp.deposit(4, 4, 5.0)                               # valid (no raise)
