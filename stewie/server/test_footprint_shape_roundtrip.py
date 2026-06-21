"""GIS S-3: a typed-footprint build order authored in the Plan pane must round-trip through /plan into
the planner as REAL geometry -- an oriented rectangle/corridor/polygon, NOT the legacy axis-aligned
square. This is the server-side half of the lane (the JS authoring is covered by footprint_geom.test.js;
the live 2D-canvas path is covered by the signed-in Playwright check). It asserts:

  1. PlanRequest carries the `shape` field through to mission_from_dict (the cockpit sends ORDERS verbatim).
  2. mission_from_dict derives footprint_m2 from the shape's planar area -- a 15x2 road is 30 m^2, NOT the
     36 m^2 a 6x6 square (the old scalar default) would give -> the planner uses the real footprint.
  3. the oriented footprint rasterizes to a NON-SQUARE ring (unequal x/y spans), and theta_deg rotates it
     -> the planner's footprint geometry is the authored shape, not a square.
  4. the live /plan endpoint accepts a shape-typed order and plans it (the real product boundary).
  5. the legacy scalar order (no shape) is byte-for-byte unchanged (behaviour-preserving default).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from lode import gis_export as GE
from lode import mission_planner as MP
from stewie.server.routers.plan import PlanRequest
from stewie.server.server import app


def _span(ring, axis):
    vals = [p[axis] for p in ring]
    return max(vals) - min(vals)


def test_planrequest_passes_shape_through_to_mission_from_dict():
    # the cockpit qadd handler attaches order.shape; PlanRequest.Order has extra="allow" so it survives
    req = PlanRequest(name="road", body="moon", orders=[
        {"action": "Grade road", "kind": "cut", "x": 10.0, "y": 10.0, "depth_m": 0.1,
         "shape": {"kind": "rectangle", "w": 15.0, "h": 2.0, "theta_deg": 30.0}}])
    payload = req.model_dump(exclude_unset=True)
    assert payload["orders"][0]["shape"] == {"kind": "rectangle", "w": 15.0, "h": 2.0, "theta_deg": 30.0}
    m = MP.mission_from_dict({"name": "road", "body": "moon", "orders": payload["orders"]})
    assert m.orders[0].shape == {"kind": "rectangle", "w": 15.0, "h": 2.0, "theta_deg": 30.0}


def test_footprint_area_is_the_real_shape_not_a_square():
    # a 15x2 m road -> 30 m^2 from the rectangle, NOT 36 m^2 (a 6x6 square) and NOT the default scalar.
    m = MP.mission_from_dict({"name": "road", "body": "moon", "orders": [
        {"action": "Grade road", "kind": "cut", "x": 0.0, "y": 0.0, "depth_m": 0.1,
         "shape": {"kind": "rectangle", "w": 15.0, "h": 2.0}}]})
    assert m.orders[0].footprint_m2 == pytest.approx(30.0)
    # the same scalar area as a square would be sqrt(30)=5.477 per side -> the shape is NOT that square
    assert abs(m.orders[0].footprint_m2 - 36.0) > 1.0


def test_planner_footprint_geometry_is_a_non_square_oriented_ring():
    # the planner's footprint rasterizer (the JS twin of footprint_geom.footprintRingXY) -- the
    # canonical geometry the as-built/acceptance + GIS export use -- yields a NON-SQUARE oriented ring.
    class _O:
        x, y = 0.0, 0.0
        shape = {"kind": "rectangle", "w": 15.0, "h": 2.0, "theta_deg": 0.0}
    ring0 = GE._footprint_ring_xy(_O())
    assert ring0 is not None
    assert _span(ring0, 0) == pytest.approx(15.0)   # 15 m along x
    assert _span(ring0, 1) == pytest.approx(2.0)    # 2 m along y -> NOT a square
    assert abs(_span(ring0, 0) - _span(ring0, 1)) > 1.0

    class _O90(_O):
        shape = {"kind": "rectangle", "w": 15.0, "h": 2.0, "theta_deg": 90.0}
    ring90 = GE._footprint_ring_xy(_O90())
    assert _span(ring90, 0) == pytest.approx(2.0)    # rotated: long axis now on y
    assert _span(ring90, 1) == pytest.approx(15.0)


def test_corridor_and_polygon_shapes_round_trip():
    m = MP.mission_from_dict({"name": "corr", "body": "moon", "orders": [
        {"action": "Haul strip", "kind": "cut", "x": 5.0, "y": 5.0, "depth_m": 0.05,
         "shape": {"kind": "corridor", "length": 40.0, "width": 3.0, "theta_deg": 0.0}},
        {"action": "Pad", "kind": "fill", "x": 20.0, "y": 20.0, "depth_m": 0.1,
         "shape": {"kind": "polygon", "vertices": [[0, 0], [10, 0], [10, 6], [0, 6]]}}]})
    assert m.orders[0].footprint_m2 == pytest.approx(120.0)   # 40x3 corridor
    assert m.orders[1].footprint_m2 == pytest.approx(60.0)    # 10x6 polygon (shoelace)
    assert m.orders[0].shape["kind"] == "corridor"
    assert m.orders[1].shape["kind"] == "polygon"


def test_plan_endpoint_accepts_a_shape_typed_order():
    c = TestClient(app)
    body = {"name": "road", "body": "moon", "site": "haworth",
            "orders": [{"action": "Grade road", "kind": "cut", "x": 10.0, "y": 10.0, "depth_m": 0.05,
                        "shape": {"kind": "rectangle", "w": 15.0, "h": 2.0, "theta_deg": 20.0}}]}
    r = c.post("/plan", json=body)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] is True
    assert j["plan_result"]["n_orders"] == 1


def test_legacy_scalar_order_is_unchanged():
    # behaviour-preserving default: no shape -> the scalar footprint_m2 is used verbatim, no shape stored.
    m = MP.mission_from_dict({"name": "legacy", "body": "moon", "orders": [
        {"action": "Pad", "kind": "cut", "x": 0.0, "y": 0.0, "footprint_m2": 36.0, "depth_m": 0.1}]})
    assert m.orders[0].footprint_m2 == pytest.approx(36.0)
    assert m.orders[0].shape is None
    assert GE._footprint_ring_xy(m.orders[0]) is None   # no fabricated typed geometry for a scalar order
