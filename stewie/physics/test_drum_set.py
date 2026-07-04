"""Tests for DrumSet -- IPEx four-drum per-drum fill tracking (VT-04).

VT-04 replaces the single global ``ColumnState.drum_inventory`` scalar with four-drum resolution:
per-drum fill (kg) whose sum equals the platform drum mass, excavate/deposit routing to specific
drums, per-drum fill non-negative + capacity-bounded, and the grid+drum mass invariant round-tripping.
Capacities are the SOURCED IPEx hold (30 kg/cycle) split across the four identical drums; nothing is
fabricated. The primary round-trip drives a REAL ``ColumnState`` (default Lunar Sourcebook surface
layer), not synthetic data.

Host-runnable + pytest-discoverable.
"""
from __future__ import annotations

import numpy as np
import pytest

from stewie.specs import constants as K
from stewie.specs import ipex_specs as S
from stewie.specs import system_profile as SP
from stewie.specs import vehicles as V
from stewie.physics.column_state import ColumnState
from stewie.physics.drum_set import DrumSet


# ---- capacity composition (sourced, not fabricated) ---------------------------------------------

def test_for_ipex_composes_sourced_capacity():
    """DrumSet.for_ipex() = the sourced 30 kg platform hold split across the sourced 4 drums = 7.5 kg
    each, empty at construction. Both inputs come from the real registries (no invented numbers)."""
    drums = DrumSet.for_ipex()
    assert drums.n_drums == int(SP.IPEX.n_drums) == 4
    total = V.get_vehicle("ipex").drum_capacity_kg
    assert total == S.REGOLITH_PER_CYCLE_KG == 30.0
    assert drums.total_capacity == pytest.approx(total)
    assert drums.per_drum_fill == (0.0, 0.0, 0.0, 0.0)
    for cap in drums.capacities:
        assert cap == pytest.approx(total / 4)          # 7.5 kg/drum


def test_add_is_capacity_bounded_and_reports_overflow():
    """Adding more than the platform can hold fills every drum to capacity and returns the ACCEPTED kg;
    the shortfall is reported to the caller (mass conserved), never silently absorbed."""
    drums = DrumSet.for_ipex()
    accepted = drums.add(100.0)                          # 100 kg into a 30 kg platform
    assert accepted == pytest.approx(30.0)              # only the real capacity is accepted
    assert 100.0 - accepted == pytest.approx(70.0)     # the shortfall the caller must offload
    assert drums.total_fill == pytest.approx(drums.total_capacity)
    drums.check_capacity_bounds()                        # every drum <= its capacity, none negative


def test_add_routes_to_a_specific_drum_and_spills_the_shortfall():
    """Excavation routes cut mass to one arm's drum; a request beyond that drum's capacity fills it and
    returns the shortfall (it does NOT overflow into other drums when a drum is named)."""
    drums = DrumSet.for_ipex()
    accepted = drums.add(10.0, drum=0)                   # 10 kg into a 7.5 kg drum
    assert accepted == pytest.approx(7.5)
    assert drums.per_drum_fill == pytest.approx((7.5, 0.0, 0.0, 0.0))
    assert drums.total_fill == pytest.approx(7.5)


def test_remove_never_goes_negative():
    """A deposit/offload larger than the held mass empties the drums and returns only what was held."""
    drums = DrumSet.for_ipex()
    drums.add(5.0, drum=2)
    removed = drums.remove(20.0, drum=2)                 # ask for 20, only 5 held
    assert removed == pytest.approx(5.0)
    assert drums.per_drum_fill == pytest.approx((0.0, 0.0, 0.0, 0.0))
    assert drums.total_fill == pytest.approx(0.0)


def test_level_fill_conserves_and_balances():
    """Unnamed add levels across drums and conserves mass: sum of per-drum == accepted, each <= cap."""
    drums = DrumSet.for_ipex()
    accepted = drums.add(6.0)                            # 6 kg across four 7.5 kg drums
    assert accepted == pytest.approx(6.0)
    assert drums.total_fill == pytest.approx(6.0)
    assert sum(drums.per_drum_fill) == pytest.approx(drums.total_fill)
    assert all(0.0 <= f <= cap for f, cap in zip(drums.per_drum_fill, drums.capacities))
    # Unnamed remove levels the withdrawal the same way, staying non-negative and conserved.
    removed = drums.remove(4.0)                           # draw 4 kg evenly back out
    assert removed == pytest.approx(4.0)
    assert drums.total_fill == pytest.approx(2.0)
    assert sum(drums.per_drum_fill) == pytest.approx(drums.total_fill)
    assert all(f >= 0.0 for f in drums.per_drum_fill)


# ---- the VT-04 acceptance: per-drum sum == scalar total, routing, bounds, round-trip ------------

def test_vt04_per_drum_fill_conserves_total():  # [REQ:VT-04]
    """VT-04: four-drum per-drum fill whose SUM equals the platform drum mass (the scalar
    ColumnState.drum_inventory), excavate/deposit routing to specific drums, per-drum non-negative +
    capacity-bounded, and the grid+drum mass invariant round-tripping across a real cut then dump.

    The DrumSet is the per-drum decomposition of ColumnState's scalar inventory; the caller mirrors
    each grid transfer into the drums so ``drums.total_fill == cs.drum_inventory`` holds throughout."""
    # A real conserved column grid (default = the Lunar Sourcebook surface layer, RHO_SURFACE * Z_T).
    cs = ColumnState(width=6, height=6, cell_m=0.1)
    drums = DrumSet.for_ipex()
    total0 = cs.total_mass()                              # grid + drum invariant reference [kg]
    per_cell_kg = K.RHO_SURFACE * K.Z_T * cs.cell_area   # one full-layer cell = 1.56 kg at 0.1 m

    assert drums.total_fill == pytest.approx(cs.drum_inventory) == 0.0

    # --- excavate: cut two cells, route the cut mass to drum 0 -------------------------------------
    mask_a = np.zeros((cs.height, cs.width), dtype=bool)
    mask_a[0, 0] = mask_a[0, 1] = True
    moved_a = cs.cut_to_inventory(mask_a, 1e6)            # 1e6 clamps to available -> full layer
    assert moved_a == pytest.approx(2 * per_cell_kg)     # 3.12 kg, sourced from the real layer
    assert drums.add(moved_a, drum=0) == pytest.approx(moved_a)   # fits a 7.5 kg drum
    assert drums.per_drum_fill[0] == pytest.approx(moved_a)
    assert drums.per_drum_fill[1:] == pytest.approx((0.0, 0.0, 0.0))   # routed to drum 0 only

    # --- excavate again: route the next cut to drum 1 ---------------------------------------------
    mask_b = np.zeros((cs.height, cs.width), dtype=bool)
    mask_b[1, 0] = mask_b[1, 1] = True
    moved_b = cs.cut_to_inventory(mask_b, 1e6)
    assert drums.add(moved_b, drum=1) == pytest.approx(moved_b)

    # Acceptance clause 1: a 4-element per-drum fill whose SUM equals the total drum mass (scalar).
    assert len(drums.per_drum_fill) == 4
    assert sum(drums.per_drum_fill) == pytest.approx(drums.total_fill)
    assert drums.total_fill == pytest.approx(cs.drum_inventory)
    assert cs.drum_inventory == pytest.approx(moved_a + moved_b)

    # Acceptance clause 2: per-drum fill non-negative + capacity-bounded.
    drums.check_capacity_bounds()
    assert all(0.0 <= f <= cap for f, cap in zip(drums.per_drum_fill, drums.capacities))

    # Acceptance clause 3: cutting grid -> drum conserves the grid+drum total.
    assert cs.total_mass() == pytest.approx(total0)

    # --- deposit: withdraw from a specific drum and dump onto a fresh grid cell -------------------
    dump_mask = np.zeros((cs.height, cs.width), dtype=bool)
    dump_mask[5, 5] = True
    removed = drums.remove(2.0, drum=0)                  # take 2 kg out of drum 0
    assert removed == pytest.approx(2.0)
    placed = cs.dump_from_inventory(dump_mask, removed)  # drum -> grid (removed <= drum_inventory)
    assert placed == pytest.approx(removed)

    # Invariant still holds after the round-trip, and total mass is conserved end-to-end.
    assert drums.per_drum_fill[0] == pytest.approx(moved_a - 2.0)
    assert drums.total_fill == pytest.approx(cs.drum_inventory)
    assert cs.total_mass() == pytest.approx(total0)
