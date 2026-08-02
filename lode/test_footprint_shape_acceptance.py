"""SR-14 [REQ:CP-05]: acceptance must measure the TYPED footprint, not an area-equivalent square.

`validate_plan` and `execute_plan_acceptance` both rasterized every order as `sqrt(footprint_m2)` --
a square -- and never read `order.shape`, even though `planner_model.py` asserts "the shape carries
orientation for acceptance" and `gis_export` publishes the true oriented ring. The map and the
acceptance check therefore described different ground.

Measured by the 2026-07-28 review on `{kind:'corridor', length:50, width:2}` (100 m2):

  * the mask was a 10 x 10 m square, so 40 m of the 50 m corridor was never measured at all,
    and `as_built_pass` came back True;
  * bearing reported `width_m=10.0`. Against forge.bearing.allowable_bearing_pa with the mission's
    own soil and gravity: B=2 -> 36,330 Pa, B=10 -> 171,195 Pa. Allowable overstated 4.7x, for a
    strip footing a lander leg may sit on.

The only existing shape test (test_footprint_shape.py:65) is a plan_ir ECHO -- it asserts the shape
survives serialization, never that anything consumes it. That is why this went unnoticed.

Run: <venv>/bin/python -m pytest lode/test_footprint_shape_acceptance.py -q
"""
from __future__ import annotations

import math

import numpy as np

from lode.planner_acceptance import _footing_width_m, _order_ring, _ring_mask


class _O:
    """Minimal order stand-in carrying just what the mask and bearing read."""

    def __init__(self, x, y, footprint_m2, shape=None, action="fill"):
        self.x, self.y, self.footprint_m2, self.shape, self.action = x, y, footprint_m2, shape, action


_CORRIDOR = _O(0.0, 0.0, 100.0, {"kind": "corridor", "length": 50.0, "width": 2.0, "theta_deg": 0.0})
_SQUARE = _O(0.0, 0.0, 100.0)                       # legacy: bare scalar, no typed shape


def _grid(n=140, cell_m=0.5):
    rr, cc = np.meshgrid(np.arange(n), np.arange(n), indexing="ij")
    return rr, cc, cell_m, -(n * cell_m) / 2.0      # x0 == y0, centred on the order


# ---- the footing width (bearing) -------------------------------------------------------------

def test_corridor_footing_width_is_its_short_side_not_the_area_square():
    """B must be 2 m (the strip's width), not sqrt(100)=10."""
    assert abs(_footing_width_m(_CORRIDOR) - 2.0) < 1e-6, _footing_width_m(_CORRIDOR)
    assert abs(_footing_width_m(_SQUARE) - 10.0) < 1e-9      # legacy path unchanged


def test_the_overstatement_is_actually_removed():
    """Pin the consequence in Pascals, with the same solver the acceptance report uses."""
    from stewie_forge.bearing import allowable_bearing_pa
    kw = dict(factor_of_safety=3.0)
    at_2 = allowable_bearing_pa(170.0, math.radians(37.0), 1300.0 * 1.62, 2.0, **kw)
    at_10 = allowable_bearing_pa(170.0, math.radians(37.0), 1300.0 * 1.62, 10.0, **kw)
    assert at_10 > at_2 * 2.0, "bearing no longer grows with B -- this guard has gone vacuous"
    assert abs(_footing_width_m(_CORRIDOR) - 2.0) < 1e-6      # so acceptance now reports the lower one


def test_rectangle_and_circle_widths():
    rect = _O(0.0, 0.0, 24.0, {"kind": "rectangle", "w": 12.0, "h": 2.0, "theta_deg": 0.0})
    assert abs(_footing_width_m(rect) - 2.0) < 1e-6
    circ = _O(0.0, 0.0, math.pi * 9.0, {"kind": "circle", "r": 3.0})
    assert abs(_footing_width_m(circ) - 6.0) < 0.15           # diameter, within polygon discretisation


def test_orientation_changes_nothing_about_the_width():
    """A rotated strip is still 2 m wide -- the width is a property of the shape, not the frame."""
    rot = _O(0.0, 0.0, 100.0, {"kind": "corridor", "length": 50.0, "width": 2.0, "theta_deg": 37.0})
    assert abs(_footing_width_m(rot) - 2.0) < 1e-6


# ---- the rasterized mask ---------------------------------------------------------------------

def test_corridor_mask_covers_the_whole_corridor_not_a_square():
    """The 40 m that was never measured must now be measured."""
    rr, cc, cell_m, x0 = _grid()
    ring = _order_ring(_CORRIDOR)
    assert ring is not None
    mask = _ring_mask(ring, x0, x0, cell_m, cc, rr)
    area = int(mask.sum()) * cell_m * cell_m
    assert abs(area - 100.0) < 6.0, f"corridor area {area} m2 != ~100"
    xs = (cc[mask] + 0.5) * cell_m + x0
    assert xs.max() - xs.min() > 45.0, f"corridor spans only {xs.max() - xs.min()} m, not ~50"


def test_rotated_corridor_mask_follows_the_orientation():
    """The claim planner_model makes -- the shape carries ORIENTATION for acceptance."""
    rr, cc, cell_m, x0 = _grid()
    rot = _O(0.0, 0.0, 100.0, {"kind": "corridor", "length": 50.0, "width": 2.0, "theta_deg": 90.0})
    mask = _ring_mask(_order_ring(rot), x0, x0, cell_m, cc, rr)
    ys = (rr[mask] + 0.5) * cell_m + x0
    xs = (cc[mask] + 0.5) * cell_m + x0
    assert ys.max() - ys.min() > 45.0, "a 90-degree corridor did not run along y"
    assert xs.max() - xs.min() < 6.0


def test_a_bare_scalar_order_keeps_the_legacy_square():
    """Back-compat: an order with no typed shape is unchanged."""
    assert _order_ring(_SQUARE) is None


def test_mask_area_matches_the_declared_footprint_for_a_rectangle():
    rr, cc, cell_m, x0 = _grid()
    rect = _O(0.0, 0.0, 24.0, {"kind": "rectangle", "w": 12.0, "h": 2.0, "theta_deg": 0.0})
    mask = _ring_mask(_order_ring(rect), x0, x0, cell_m, cc, rr)
    assert abs(int(mask.sum()) * cell_m * cell_m - 24.0) < 3.0
