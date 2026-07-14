"""[REQ:PX-12] The live DUMP is metered by the drum's own scoops — the mirror of the bounded dig.

WHY THIS FILE EXISTS. Digging became genuinely physical (PX-09 drum capacity + the <=50%-scoop anti-bridging
bite, PX-10 the arm gates the cut, PX-11 the footprint IS the drum). Dumping stayed crude: `_apply_dump`
called `ws.dump(mask)` with no kg, which discharges **the ENTIRE drum ledger in a single frame** -- up to
24.98 kg of regolith teleporting onto a 0.35 m box in one tick, after which the sandpile relax spreads the
resulting mound. A bucket drum cannot do that. It empties the way it fills: through its scoops, a bite at a
time.

THE QUANTUM, and the one assumption in it. A drum digs and dumps with the SAME scoops. The dig is bounded per
pass by the sourced [BDSCALE] anti-bridging rule -- bite <= 50% of the scoop opening, taken over the
drum-width footprint -- so ONE pass of scoops carries

    scoop_pass_kg = drum-width footprint area  x  max_cut_per_pass_m  x  in-situ density

(the scoops carry what they CUT, so the in-situ density is the right one; RHO_SPOIL happens to equal
RHO_SURFACE here, since bulking arises from the RHO_DEEP->spoil gap, not from a lighter spoil). Emptying is
the same scoops turning the other way, so ONE dump pass discharges at most that same mass:

    small 0.39 kg   medium 1.40 kg   large 3.81 kg     (measured, 5 cm cell)
    -> 9.8 / 5.2 / 6.6 metered passes to empty a full drum (capacity 3.80 / 7.30 / 24.98 kg)

Passes-to-empty is NOT monotonic in drum size, and that is real, not a bug: the footprint is quantised to a
whole number of cells (PX-11), so the small drum's 0.3526 m width rounds to a box that is proportionally
smaller relative to its hold than the medium drum's. The quantum falls out of the drum geometry; it is not
tuned.

The SYMMETRY (a discharge pass carries what a dig pass carries) is the [ASSUMPTION]; the geometry it rests on
is sourced. What it buys is the thing that was missing: a dump is now a FINITE, repeatable quantum, so a berm
is built by metered passes you can plan, cost, and learn from -- not by one instantaneous mound.
"""
from __future__ import annotations

import math
import os
import tempfile

import numpy as np
import pytest

from stewie.runtime.viz2_runtime import Viz2Runtime
from stewie.specs import constants as K
from stewie.specs.ipex_specs import DRUM_CAPACITY_KG, DRUM_DIMENSIONS_M, max_cut_per_pass_m

_SAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "samples", "lunar_dem")
SFS = os.path.join(_SAMPLES, "haworth_sfs_2km_1m")
pytestmark = pytest.mark.skipif(not os.path.isdir(SFS), reason="real Haworth SfS bundle not on disk")

DRUM = "small"                      # the tightest drum: fills fast, so the metering is easy to see


def _spawn() -> tuple[float, float]:
    from stewie.physics.worksite import coarse_base_from_bundle
    base, meta = coarse_base_from_bundle(SFS)
    wb = meta["world_bounds_m"]
    return (float(wb["x0"]) + base.width * meta["grid"]["cell_m"] * 0.5,
            float(wb["y0"]) + base.height * meta["grid"]["cell_m"] * 0.5)


def _runtime(tmp: str, drum: str = DRUM) -> Viz2Runtime:
    return Viz2Runtime(SFS, session_dir=tmp, fine_cell_m=0.05, start_xy=_spawn(), drum=drum)


def _expected_quantum(rt: Viz2Runtime) -> float:
    """The scoop-pass mass, from the drum's own sourced geometry."""
    side = (2 * rt.dig_half_cells + 1) * float(rt.ws.fine_cell_m)
    return side * side * max_cut_per_pass_m(rt.drum) * K.RHO_SURFACE


def _fill_drum(rt: Viz2Runtime) -> float:
    """Dig until the drum refuses (PX-09 caps it at the sourced hold)."""
    for _ in range(80):
        if not rt._apply_dig():
            break
    return float(rt.ws.inventory_kg)


def test_one_dump_discharges_at_most_one_scoop_pass_not_the_whole_drum() -> None:
    """[REQ:PX-12] THE REQUIREMENT. A full drum must not empty itself in a single frame."""
    with tempfile.TemporaryDirectory() as d:
        rt = _runtime(d)
        try:
            held = _fill_drum(rt)
            assert held > 0.0, "the test never filled the drum"
            quantum = _expected_quantum(rt)
            assert held > quantum, "test premise: the drum must hold more than one scoop pass"

            rt._apply_dump()
            discharged = held - float(rt.ws.inventory_kg)
            assert discharged <= quantum + 1e-6, (
                f"one dump discharged {discharged:.3f} kg, more than the {quantum:.3f} kg a single pass of "
                "scoops can carry -- the drum is still teleporting its whole load in one frame")
            assert discharged > 0.0, "the dump moved nothing"
        finally:
            rt.stop()


def test_emptying_the_drum_takes_several_metered_passes() -> None:
    """[REQ:PX-12] The consequence that makes a berm plannable: emptying is a COUNTABLE number of passes,
    and the drum drains monotonically rather than in one step."""
    with tempfile.TemporaryDirectory() as d:
        rt = _runtime(d)
        try:
            held = _fill_drum(rt)
            quantum = _expected_quantum(rt)
            need = math.ceil(held / quantum)

            levels = [held]
            for _ in range(need + 5):
                if float(rt.ws.inventory_kg) <= 1e-9:
                    break
                rt._apply_dump()
                levels.append(float(rt.ws.inventory_kg))

            assert levels[-1] == pytest.approx(0.0, abs=1e-6), f"the drum never emptied: {levels}"
            passes = len(levels) - 1
            assert passes >= need, (
                f"emptied {held:.2f} kg in {passes} pass(es); one pass carries only {quantum:.2f} kg, so it "
                f"should take at least {need}")
            # strict=False is deliberate: pairwise (n, n+1) iteration is unequal-length BY DESIGN.
            assert all(b <= a + 1e-9 for a, b in zip(levels, levels[1:], strict=False)), \
                "the drum level went UP"
        finally:
            rt.stop()


def test_a_metered_dump_conserves_mass() -> None:
    """[REQ:PX-12] Metering must not break conservation: the grid gains exactly what the drum loses."""
    with tempfile.TemporaryDirectory() as d:
        rt = _runtime(d)
        try:
            _fill_drum(rt)
            grid0 = float(rt.ws._require_fine().grid_mass())
            drum0 = float(rt.ws.inventory_kg)
            rt._apply_dump()
            grid1 = float(rt.ws._require_fine().grid_mass())
            drum1 = float(rt.ws.inventory_kg)
            assert (drum0 - drum1) == pytest.approx(grid1 - grid0, rel=1e-6, abs=1e-6), \
                "the metered dump is not mass-conserving"
        finally:
            rt.stop()


def test_an_empty_drum_dumps_nothing() -> None:
    """[REQ:PX-12] Nothing to discharge -> no terrain change, no phantom spoil."""
    with tempfile.TemporaryDirectory() as d:
        rt = _runtime(d)
        try:
            assert float(rt.ws.inventory_kg) == 0.0
            grid0 = float(rt.ws._require_fine().grid_mass())
            assert rt._apply_dump() == []
            assert float(rt.ws._require_fine().grid_mass()) == pytest.approx(grid0, abs=1e-9)
        finally:
            rt.stop()


def test_the_dump_actually_raises_the_ground() -> None:
    """[REQ:PX-12] A metered dump still BUILDS: the surface under the drum rises (it is a berm, not a
    bookkeeping entry)."""
    with tempfile.TemporaryDirectory() as d:
        rt = _runtime(d)
        try:
            _fill_drum(rt)
            before = rt.ws._require_fine().derive_height().copy()
            dirty = rt._apply_dump()
            assert dirty, "the dump reported no dirty region"
            after = rt.ws._require_fine().derive_height()
            assert float(np.max(after - before)) > 0.0, "nothing rose: the spoil did not land"
        finally:
            rt.stop()


def test_the_dump_quantum_is_the_dig_quantum_same_scoops() -> None:
    """[REQ:PX-12] The symmetry the model rests on, stated as a test: a discharge pass carries what a dig
    pass carries, because it is the same scoops. If the dig's sourced bite or the drum's footprint changes,
    the dump must move with it -- they cannot drift apart."""
    for drum in ("small", "medium", "large"):
        with tempfile.TemporaryDirectory() as d:
            rt = _runtime(d, drum=drum)
            try:
                side = (2 * rt.dig_half_cells + 1) * float(rt.ws.fine_cell_m)
                assert abs(side - DRUM_DIMENSIONS_M[drum]["width"]) <= rt.ws.fine_cell_m  # PX-11
                assert rt._max_discharge_per_pass_kg == pytest.approx(_expected_quantum(rt), rel=1e-9)
                # and a full drum genuinely needs several of them
                assert DRUM_CAPACITY_KG[drum] > rt._max_discharge_per_pass_kg
            finally:
                rt.stop()
