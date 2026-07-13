"""[REQ:PX-11] The excavation footprint is a PHYSICAL dimension (the drum's width), so the operator's
render-resolution toggle cannot silently change the vehicle. On the REAL Haworth SfS 1 m bundle.

WHY THIS FILE EXISTS. The setup page offers a "cell size" choice (5 cm / 2 cm), which any operator reads as
a RENDER-RESOLUTION knob. It was not one. `_apply_dig` built its footprint from `dig_half_cells = 6` -- a
CELL COUNT -- so picking a finer grid silently shrank the excavator:

    cell    dig box      physical footprint   vs the drum (0.3526 m)   mass cut by ONE dig
    5 cm    13 x 13      0.650 m              1.84x too WIDE           15.832 kg
    2 cm    13 x 13      0.260 m              0.74x too NARROW          2.231 kg

Same dig command, same terrain, same rover -> 7.1x different mass excavated, purely from a display setting.
And neither footprint was the drum's actual width, while `_dig_fee` bills the pass using
`width_m=self._drum_width_m` (the REAL sourced width) -- so the cut geometry and the energy model described
different tools. That is the same class of self-contradiction as PX-09 (energy billed for a bite the terrain
never gave up), one level further out.

The footprint is now DERIVED from the drum width: the box side is the closest odd cell count to
DRUM_DIMENSIONS_M[drum]["width"], so the excavator is the same physical machine at every resolution and the
tool the FEE bills is the tool that cuts.
"""
from __future__ import annotations

import os
import tempfile

import pytest

from stewie.runtime.viz2_runtime import Viz2Runtime
from stewie.specs.ipex_specs import DRUM_DIMENSIONS_M

_SAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "samples", "lunar_dem")
SFS = os.path.join(_SAMPLES, "haworth_sfs_2km_1m")
pytestmark = pytest.mark.skipif(not os.path.isdir(SFS), reason="real Haworth SfS bundle not on disk")

DRUM = "large"
DRUM_W = float(DRUM_DIMENSIONS_M[DRUM]["width"])          # 0.3526 m, sourced [BDSCALE]


def _spawn() -> tuple[float, float]:
    from stewie.physics.worksite import coarse_base_from_bundle
    base, meta = coarse_base_from_bundle(SFS)
    wb = meta["world_bounds_m"]
    cx = float(wb["x0"]) + base.width * meta["grid"]["cell_m"] * 0.5
    cy = float(wb["y0"]) + base.height * meta["grid"]["cell_m"] * 0.5
    return cx, cy


def _runtime(tmp: str, cell: float) -> Viz2Runtime:
    return Viz2Runtime(SFS, session_dir=tmp, fine_cell_m=cell, start_xy=_spawn(), drum=DRUM)


def _footprint_m(rt: Viz2Runtime) -> float:
    """The dig box's physical side length [m] -- what the excavator actually carves."""
    return (2 * rt.dig_half_cells + 1) * float(rt.ws.fine_cell_m)


def test_footprint_matches_the_sourced_drum_width_at_every_resolution() -> None:
    """[REQ:PX-11] The dig footprint IS the drum, not a cell count. At each offered cell size it must land
    within one cell of the drum's real width -- the best a discrete grid can do."""
    for cell in (0.05, 0.02):
        with tempfile.TemporaryDirectory() as d:
            rt = _runtime(d, cell)
            fp = _footprint_m(rt)
            assert abs(fp - DRUM_W) <= cell, (
                f"at {cell*100:.0f} cm the dig carves {fp:.3f} m but the {DRUM} drum is {DRUM_W:.4f} m wide "
                f"-- the excavation footprint is not the drum ({fp/DRUM_W:.2f}x)")


def test_the_render_resolution_toggle_does_not_resize_the_excavator() -> None:
    """[REQ:PX-11] THE REQUIREMENT: 'cell size' is a DISPLAY choice. Switching 5 cm -> 2 cm must not change
    the machine. The physical footprint must agree across resolutions to within a cell."""
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        coarse, fine = _runtime(a, 0.05), _runtime(b, 0.02)
        fp_coarse, fp_fine = _footprint_m(coarse), _footprint_m(fine)
        assert abs(fp_coarse - fp_fine) <= 0.05, (
            f"the resolution toggle resized the excavator: {fp_coarse:.3f} m at 5 cm vs {fp_fine:.3f} m at "
            "2 cm -- a display setting is changing the vehicle's physical geometry")


def test_the_same_dig_moves_comparable_mass_at_either_resolution() -> None:
    """[REQ:PX-11] The consequence that actually bit: one dig command on identical terrain used to move 7.1x
    more mass at 5 cm than at 2 cm. With a physical footprint the two must agree to within the grid's own
    quantisation (a coarse grid still cannot resolve the box exactly), NOT by a factor of seven."""
    masses = {}
    for cell in (0.05, 0.02):
        with tempfile.TemporaryDirectory() as d:
            rt = _runtime(d, cell)
            g0 = float(rt.ws._require_fine().grid_mass())
            rt._apply_dig()
            masses[cell] = g0 - float(rt.ws._require_fine().grid_mass())

    assert min(masses.values()) > 0.0, f"a dig moved nothing: {masses}"
    ratio = max(masses.values()) / min(masses.values())
    assert ratio < 1.6, (
        f"one dig moved {masses[0.05]:.3f} kg at 5 cm but {masses[0.02]:.3f} kg at 2 cm ({ratio:.1f}x) -- "
        "the render-resolution toggle is still changing how much regolith the rover excavates")


def test_the_tool_that_cuts_is_the_tool_the_fee_bills() -> None:
    """[REQ:PX-11] `_dig_fee` bills the pass with width_m = the drum's real width. The cut must be made with
    that same width, or the energy model and the geometry describe different machines (the PX-09 class of
    bug). Pin them to each other."""
    for cell in (0.05, 0.02):
        with tempfile.TemporaryDirectory() as d:
            rt = _runtime(d, cell)
            assert rt._drum_width_m == pytest.approx(DRUM_W)
            assert abs(_footprint_m(rt) - rt._drum_width_m) <= cell, (
                "the FEE bills a "
                f"{rt._drum_width_m:.4f} m tool while the terrain is cut by a {_footprint_m(rt):.3f} m box")
