"""Tests for ColumnState construction-time domain validation (T-09).

The conserved-state constructor must reject every out-of-domain field at construction (CT-02/RB-01)
so a caller cannot inject a physically-impossible state. These tests pin the COMPLETE declared domains
the finding T-09 calls out: disturbance in [0,1], state_label in the StateLabel enum, density in a
physical range (0, RHO_GRAIN], and ice in [0, W_ICE_MAX]. Boundary values are accepted.

Host-runnable + pytest-discoverable.
"""
from __future__ import annotations

import numpy as np
import pytest

from stewie.specs import constants as K
from stewie.physics import validation as V
from stewie.physics.column_state import ColumnState, StateLabel


def _full(shape, fill, dtype=np.float64):
    return np.full(shape, fill, dtype=dtype)


def _base_fields(h=4, w=5):
    """A valid in-domain field set; tests mutate ONE field out of domain at a time."""
    shape = (h, w)
    return dict(
        width=w, height=h, cell_m=0.02,
        mass_areal=_full(shape, K.RHO_SURFACE * K.Z_T),
        density=_full(shape, K.RHO_SURFACE),
        state_label=_full(shape, int(StateLabel.VIRGIN), dtype=np.uint8),
        disturbance=_full(shape, 0.0),
        datum=_full(shape, 0.0),
    )


def test_baseline_in_domain_constructs():
    """The unmutated base field set is valid -> the validator is not over-eager."""
    ColumnState(**_base_fields())   # must not raise


# -- disturbance <= 1 --------------------------------------------------------

def test_disturbance_above_one_rejected():
    f = _base_fields()
    f["disturbance"] = _full((f["height"], f["width"]), 1.5)
    with pytest.raises(V.DomainError):
        ColumnState(**f)


def test_disturbance_boundaries_accepted():
    f = _base_fields()
    d = _full((f["height"], f["width"]), 0.0)
    d[0, 0] = 1.0          # exactly the upper bound
    f["disturbance"] = d
    ColumnState(**f)        # 0 and 1 are in-domain


# -- state_label enum membership --------------------------------------------

def test_state_label_out_of_enum_rejected():
    f = _base_fields()
    bad = _full((f["height"], f["width"]), int(StateLabel.VIRGIN), dtype=np.uint8)
    bad[1, 1] = 99                                 # not a StateLabel member
    f["state_label"] = bad
    with pytest.raises(V.DomainError):
        ColumnState(**f)


def test_state_label_all_enum_members_accepted():
    f = _base_fields()
    members = [int(s) for s in StateLabel]
    lab = _full((f["height"], f["width"]), int(StateLabel.VIRGIN), dtype=np.uint8)
    lab.flat[:len(members)] = members              # every declared label is in-domain
    f["state_label"] = lab
    ColumnState(**f)


# -- density physical range --------------------------------------------------

def test_density_above_grain_rejected():
    """Bulk density cannot exceed the zero-void solid grain density (constants RHO_GRAIN)."""
    f = _base_fields()
    bad = _full((f["height"], f["width"]), K.RHO_SURFACE)
    bad[0, 0] = K.RHO_GRAIN + 1.0
    f["density"] = bad
    with pytest.raises(V.DomainError):
        ColumnState(**f)


def test_density_grain_boundary_accepted():
    f = _base_fields()
    d = _full((f["height"], f["width"]), K.RHO_SURFACE)
    d[0, 0] = K.RHO_GRAIN                           # exactly the ceiling is in-domain
    f["density"] = d
    ColumnState(**f)


# -- ice upper bound ---------------------------------------------------------

def test_ice_above_max_rejected():
    f = _base_fields()
    f["ice"] = _full((f["height"], f["width"]), K.W_ICE_MAX + 0.01)
    with pytest.raises(V.DomainError):
        ColumnState(**f)


def test_ice_boundaries_accepted():
    f = _base_fields()
    ice = _full((f["height"], f["width"]), 0.0)
    ice[0, 0] = K.W_ICE_MAX                         # exactly the bound is in-domain
    f["ice"] = ice
    ColumnState(**f)


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"[PASS] {fn.__name__}")
    print(f"\n{len(fns)}/{len(fns)} column_state validation checks passed.")


if __name__ == "__main__":
    _run_all()
