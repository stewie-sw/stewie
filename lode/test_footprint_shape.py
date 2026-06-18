"""CP-05: typed build-order footprint shapes (rectangle/circle/corridor/polygon + orientation). The
shape derives footprint_m2 from its area; a bare scalar footprint_m2 stays the legacy input."""
import math

import pytest

import lode.mission_planner as MP


def test_shape_areas():
    assert MP.footprint_shape_area_m2({"kind": "rectangle", "w": 4.0, "h": 2.0}) == 8.0
    assert abs(MP.footprint_shape_area_m2({"kind": "circle", "r": 2.0}) - math.pi * 4.0) < 1e-9
    assert MP.footprint_shape_area_m2({"kind": "corridor", "length": 10.0, "width": 1.5}) == 15.0
    # a unit square as a polygon -> area 1.0 (shoelace), orientation-independent
    assert abs(MP.footprint_shape_area_m2(
        {"kind": "polygon", "vertices": [[0, 0], [2, 0], [2, 3], [0, 3]]}) - 6.0) < 1e-9


def test_bad_shapes_raise():
    for bad in ({"kind": "rectangle", "w": 0, "h": 2}, {"kind": "circle", "r": -1},
                {"kind": "polygon", "vertices": [[0, 0], [1, 1]]}, {"kind": "blob"}):
        with pytest.raises(ValueError):
            MP.footprint_shape_area_m2(bad)


def _payload(order):
    return {"name": "S", "body": "moon", "charger": [0, 0], "orders": [order]}


def test_shape_order_derives_footprint_and_is_carried():
    m = MP.mission_from_dict(_payload(
        {"action": "pad", "kind": "cut", "x": 5.0, "y": 5.0, "depth_m": 0.1,
         "shape": {"kind": "rectangle", "w": 4.0, "h": 2.0, "theta_deg": 30.0}}))
    o = m.orders[0]
    assert o.footprint_m2 == 8.0                                  # derived from the shape area
    assert o.shape["kind"] == "rectangle" and o.shape["theta_deg"] == 30.0   # orientation carried
    assert abs(o.mass_kg(1500.0) - 8.0 * 0.1 * 1500.0) < 1e-6     # mass uses the derived area


def test_legacy_scalar_order_unchanged():
    m = MP.mission_from_dict(_payload(
        {"action": "pad", "kind": "cut", "x": 5.0, "y": 5.0, "footprint_m2": 9.0, "depth_m": 0.1}))
    o = m.orders[0]
    assert o.footprint_m2 == 9.0 and o.shape is None              # legacy path, byte-identical
