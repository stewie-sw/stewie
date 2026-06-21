"""CP-05: typed build-order footprint shapes (rectangle/circle/corridor/polygon + orientation). The
shape derives footprint_m2 from its area; a bare scalar footprint_m2 stays the legacy input."""
import math

import pytest

import lode.mission_planner as MP
import lode.planner_views as PV


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


def _cutfill_mission(cut_extra=None, fill_extra=None):
    """A real cut->fill mission whose plan_ir lowers to a CutHaulFill work action. The cut order carries
    the work-site footprint; pass cut_extra={'shape':...} to make it a typed footprint, or {} for scalar."""
    cut = {"action": "borrow", "kind": "cut", "x": 20.0, "y": 0.0, "depth_m": 0.3}
    fill = {"action": "pad", "kind": "fill", "x": 40.0, "y": 0.0, "depth_m": 0.3}
    cut.update(cut_extra if cut_extra is not None else {"footprint_m2": 16.0})
    fill.update(fill_extra if fill_extra is not None else {"footprint_m2": 16.0})
    return MP.mission_from_dict({"name": "S", "body": "moon", "charger": [0, 0], "orders": [cut, fill]})


def _work_action(ir):
    return next(a for a in ir["actions"] if a["op"] in PV._IR_DIG_OPS or a["op"] in ("Import", "Sinter"))


def test_plan_ir_work_action_carries_typed_footprint():
    # PLAN-IR-ECHO: a typed-footprint order's plan_ir work action must echo the footprint shape (kind +
    # dims + theta_deg) so a ROS executive sees the real footprint, not just the scalar area.
    shape = {"kind": "rectangle", "w": 4.0, "h": 4.0, "theta_deg": 30.0}
    ir = PV.plan_ir(_cutfill_mission(cut_extra={"shape": shape}))
    act = _work_action(ir)
    assert act["op"] == "CutHaulFill"
    fp = act["footprint"]
    assert fp["kind"] == "rectangle"
    assert fp["w"] == 4.0 and fp["h"] == 4.0 and fp["theta_deg"] == 30.0
    assert abs(fp["area_m2"] - 16.0) < 1e-9                        # derived area carried alongside the shape


def test_plan_ir_polygon_footprint_carries_vertices():
    shape = {"kind": "polygon", "vertices": [[0, 0], [4, 0], [4, 4], [0, 4]]}
    ir = PV.plan_ir(_cutfill_mission(cut_extra={"shape": shape}))
    fp = _work_action(ir)["footprint"]
    assert fp["kind"] == "polygon"
    assert fp["vertices"] == [[0, 0], [4, 0], [4, 4], [0, 4]]


def test_plan_ir_scalar_order_action_unchanged():
    # behavior-preserving default: a scalar (no-shape) order's work action carries NO footprint key.
    ir = PV.plan_ir(_cutfill_mission())
    act = _work_action(ir)
    assert act["op"] == "CutHaulFill"
    assert "footprint" not in act
