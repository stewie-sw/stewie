"""N14: ColumnState public-constructor validation + runtime invariant guards (production reliability).

These make the conserved-state guarantees checkable at runtime (not only in the legacy assertion tests):
a malformed grid is rejected at construction, and the invariants / mass conservation can be asserted live.
"""
import numpy as np
import pytest

from stewie.physics.column_state import ColumnState
from stewie.specs import constants as K


def test_constructor_rejects_nonpositive_dims_and_cell():
    # [REQ:CT-02] ColumnState validates dims/shapes/domains at construction
    with pytest.raises(ValueError):
        ColumnState(0, 0, 0.02)          # zero-size grid
    with pytest.raises(ValueError):
        ColumnState(8, 8, -0.02)         # negative cell size
    with pytest.raises(ValueError):
        ColumnState(8, 8, 0.0)           # zero cell size


def test_constructor_accepts_valid():
    cs = ColumnState(8, 8, 0.02)
    assert cs.width == 8 and cs.height == 8 and cs.cell_m == 0.02


def test_check_invariants_passes_on_fresh_state():
    ColumnState(16, 16, 0.02).check_invariants()        # no raise on a well-formed state


def test_check_invariants_catches_density_mass_and_nonfinite():
    # [REQ:CT-03] mutations leave all invariants valid (mass/density/finiteness guards)
    cs = ColumnState(8, 8, 0.02)
    cs.density[0, 0] = 0.0
    with pytest.raises(ValueError, match="density"):
        cs.check_invariants()
    cs2 = ColumnState(8, 8, 0.02)
    cs2.mass_areal[0, 0] = -1.0
    with pytest.raises(ValueError, match="mass"):
        cs2.check_invariants()
    cs3 = ColumnState(8, 8, 0.02)
    cs3.mass_areal[0, 0] = np.inf
    with pytest.raises(ValueError):
        cs3.check_invariants()


def test_conserves_mass_guard():
    cs = ColumnState(8, 8, 0.02)
    with cs.conserves_mass():            # a no-op block conserves mass -> no raise
        pass
    with pytest.raises(ValueError, match="conserved"):
        with cs.conserves_mass():        # creating mass inside the block must raise
            cs.mass_areal += 1.0


# --- CT-02 construction-time FIELD validation (the requirement lists shapes, dtypes/domains, density,
# labels, disturbance, datum, ice, inventory -- the suite above covered only dims/cell + runtime invariants).
# Real ColumnState + real constants; each test injects ONE deliberately-malformed field and asserts the
# constructor rejects it (validation.DomainError is a ValueError). If any "bad" input is NOT rejected, that
# is a real validation gap, not a test artifact.

def _construct(**override):
    """Build a valid 8x8 column, then override exactly one field with a malformed value."""
    base = ColumnState(8, 8, 0.02)                                   # defaults filled + validated
    kw = dict(mass_areal=base.mass_areal.copy(), density=base.density.copy(),
              state_label=base.state_label.copy(), disturbance=base.disturbance.copy(),
              datum=base.datum.copy())
    kw.update(override)
    return ColumnState(8, 8, 0.02, **kw)


def test_ct02_rejects_wrong_array_shape():
    # [REQ:CT-02] every field must match the (height, width) grid shape
    with pytest.raises(ValueError):
        _construct(density=np.full((4, 4), float(K.RHO_SURFACE)))


def test_ct02_rejects_wrong_dtype_kind():
    # [REQ:CT-02] mass_areal is a float field; state_label is an integer enum field -- wrong kinds rejected
    with pytest.raises(ValueError):
        _construct(mass_areal=np.zeros((8, 8), dtype=np.int64))
    with pytest.raises(ValueError):
        _construct(state_label=np.zeros((8, 8), dtype=np.float64))


def test_ct02_rejects_density_outside_zero_to_grain():
    # [REQ:CT-02] bulk density domain is (0, RHO_GRAIN]: zero, negative, NaN, and super-grain are rejected
    for bad in (0.0, -10.0, np.nan, float(K.RHO_GRAIN) * 2.0):
        d = np.full((8, 8), float(K.RHO_SURFACE)); d[0, 0] = bad
        with pytest.raises(ValueError):
            _construct(density=d)


def test_ct02_rejects_disturbance_outside_unit_interval():
    # [REQ:CT-02] disturbance domain is [0, 1]
    for bad in (-0.01, 1.5):
        x = np.zeros((8, 8)); x[0, 0] = bad
        with pytest.raises(ValueError):
            _construct(disturbance=x)


def test_ct02_datum_must_be_finite_but_may_be_negative():
    # [REQ:CT-02] datum is finite (NaN/Inf rejected) yet may be negative -- it is an elevation
    bad = np.zeros((8, 8)); bad[0, 0] = np.inf
    with pytest.raises(ValueError):
        _construct(datum=bad)
    ok = np.zeros((8, 8)); ok[0, 0] = -3.0
    _construct(datum=ok)                                            # a negative elevation is valid -> no raise


def test_ct02_rejects_out_of_enum_state_label():
    # [REQ:CT-02] state_label codes must be declared StateLabel members (no silent class widening)
    lbl = np.zeros((8, 8), dtype=np.uint8); lbl[0, 0] = 99
    with pytest.raises(ValueError):
        _construct(state_label=lbl)


def test_ct02_rejects_ice_above_volatile_ceiling():
    # [REQ:CT-02] optional ice fraction domain is [0, W_ICE_MAX]; a dry column (ice=None) stays valid
    with pytest.raises(ValueError):
        _construct(ice=np.full((8, 8), float(K.W_ICE_MAX) * 2.0))
    _construct(ice=None)                                            # dry column -> no raise


def test_ct02_rejects_negative_mass_and_drum_inventory():
    # [REQ:CT-02] mass_areal >= 0 (field) and drum_inventory >= 0 (scalar)
    m = np.full((8, 8), 100.0); m[0, 0] = -1.0
    with pytest.raises(ValueError):
        _construct(mass_areal=m)
    with pytest.raises(ValueError):
        _construct(drum_inventory=-1.0)
