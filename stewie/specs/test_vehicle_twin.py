"""The VehicleTwin contract: ONE pluggable record per vehicle instance (extensibility directive).

Assembles everything the stack needs about a vehicle from the registries (Body/Vehicle/Tool/
Placement + physics params + energy model + geometry + render assets) and proves EXTENSIBILITY by
driving a SECOND vehicle (ez_rassor) end-to-end through the conserved drive loop and the mission
planner with ITS OWN numbers -- not ipex's.
"""
import numpy as np
import pytest

from stewie.specs import vehicle_twin as vtw


def test_assembles_ipex_complete():
    tw = vtw.VehicleTwin.assemble("rover_1", vehicle="ipex", body="moon")
    assert tw.instance == "rover_1" and tw.vehicle == "ipex"
    assert tw.gravity_ms2 == pytest.approx(1.62, abs=0.01)
    assert tw.geometry["wheel_radius_m"] > 0 and tw.geometry["gauge_m"] > 0
    assert tw.energy["dig_j_per_kg"] > 0 and tw.energy["drive_j_per_m"] > 0
    assert "drive" in tw.capabilities and isinstance(tw.render_assets, str)
    assert tw.params is not None                          # terramechanics params resolved


def test_unknown_vehicle_and_body_refused():
    with pytest.raises(KeyError):
        vtw.VehicleTwin.assemble("x", vehicle="starship", body="moon")
    with pytest.raises(KeyError):
        vtw.VehicleTwin.assemble("x", vehicle="ipex", body="krypton")


def test_two_vehicles_differ_where_their_specs_differ():
    a = vtw.VehicleTwin.assemble("a", vehicle="ipex", body="moon")
    b = vtw.VehicleTwin.assemble("b", vehicle="ez_rassor", body="moon")
    assert a.geometry != b.geometry or a.energy != b.energy or a.mass_kg != b.mass_kg
    assert a.gravity_ms2 == b.gravity_ms2                 # same world


def test_second_vehicle_drives_the_conserved_loop():
    """ez_rassor end-to-end through drive_step on a REAL sample scene with ITS twin context."""
    from stewie.physics import drive
    from stewie.physics.column_state import ColumnState
    from stewie.twin.io_fields import load_scene
    tw = vtw.VehicleTwin.assemble("ez1", vehicle="ez_rassor", body="moon")
    fields, meta = load_scene(vtw.sample_scene_dir("rolling_hills"))
    cell_m = float(meta["grid"]["cell_m"])
    H, W = fields["mass_areal"].shape
    cs = ColumnState(width=W, height=H, cell_m=cell_m,
                     mass_areal=np.asarray(fields["mass_areal"], dtype=np.float64).copy())
    rc, yaw = (40.0, 40.0), 0.0
    ctx = tw.drive_context()
    for _ in range(10):
        rc, yaw, telem = drive.drive_step(cs, rc, yaw, 0.2, 0.0, **ctx)
    assert rc != (40.0, 40.0) and 0.0 <= telem["slip"] < 1.0


def test_second_vehicle_plans_with_its_own_numbers():
    """The planner consumes the vehicle's OWN registry numbers where they are SOURCED.

    rassor2's 2x24.98 kg drum (Schuler 2022 BD-scaling) vs IPEx's 30 kg is the genuinely sourced
    cross-vehicle difference today -> the same mission needs FEWER drum cycles on rassor2. Energy
    deliberately reuses the IPEx-grounded model for all vehicles (the registries disclose this in
    provenance; un-sourced per-vehicle power would be fabrication)."""
    from lode import mission_planner as MP
    doc = {"name": "vt", "body": "moon", "charger": [0, 0],
           "orders": [{"action": "cut", "kind": "cut", "x": 8, "y": 6, "footprint_m2": 36,
                       "depth_m": 0.25},
                      {"action": "fill", "kind": "fill", "x": 30, "y": 18, "footprint_m2": 36,
                       "depth_m": 0.25}]}
    _, _, ta = MP.run(MP.mission_from_dict({**doc, "vehicle": "ipex"}), stem="vt_ipex")
    _, _, tb = MP.run(MP.mission_from_dict({**doc, "vehicle": "rassor2"}), stem="vt_r2")
    assert ta["drum_cycles"] > tb["drum_cycles"], \
        "the sourced drum-capacity difference must flow through the plan"
    # and the twin record carries exactly the registry numbers the planner used
    tw = vtw.VehicleTwin.assemble("r2", vehicle="rassor2", body="moon")
    assert tw.energy["drum_capacity_kg"] == pytest.approx(49.96)
