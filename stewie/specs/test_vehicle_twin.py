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
    assert tw.energy["drum_capacity_kg"] == pytest.approx(80.0)   # R2D p.7 design hold


def test_cut_depth_rule_flows_into_planning():
    """T2.3: a cut DEEPER than 50% of the scoop opening needs multiple passes -- the plan's dig
    duration must scale with the documented per-pass limit (BDS p.7), not assume one pass."""
    from lode import mission_planner as MP
    base = {"name": "cut", "body": "moon", "charger": [0, 0],
            "orders": [{"action": "cut", "kind": "cut", "x": 8, "y": 6, "footprint_m2": 16,
                        "depth_m": 0.02},
                       {"action": "fill", "kind": "fill", "x": 24, "y": 12, "footprint_m2": 16,
                        "depth_m": 0.02}]}
    deep = {**base, "orders": [dict(base["orders"][0], depth_m=0.10),
                               dict(base["orders"][1], depth_m=0.10)]}
    _, _, t_shallow = MP.run(MP.mission_from_dict(base), stem="cut_shallow")
    _, _, t_deep = MP.run(MP.mission_from_dict(deep), stem="cut_deep")
    assert t_shallow.get("cut_passes", 1) == 1            # 0.02 m <= 0.0239 m/pass
    assert t_deep["cut_passes"] >= 5                      # 0.10 / 0.0239 -> 5 passes


def test_t11_drive_context_binds_the_registry_contact_geometry():
    """ARGUS T1.1: the contact patch comes VERBATIM from the vehicle registry (wheel_width_m,
    contact_len_m -- [ASSUMPTION]-tagged there until the WHEEL doc's figure dims are read), not
    from a derived heuristic. Vehicle choice must change the contact patch."""
    tw = vtw.VehicleTwin.assemble("a", vehicle="ipex", body="moon")
    from stewie.specs import vehicles as V
    v = V.get_vehicle("ipex")
    ctx = tw.drive_context()
    assert ctx["wheel_width_m"] == v.wheel_width_m        # registry verbatim, no 0.6*radius heuristic
    assert ctx["contact_len_m"] == v.contact_len_m


def test_t71_bp1_testbed_soil_binds_measured_density():
    """ARGUS T7.1: the GMRO BP-1 bed is selectable; density is the MEASURED 1750, moduli are the
    DISCLOSED Wong analog (a BP-1 Bekker fit is unpublished -- never fabricated)."""
    from stewie.specs import bodies as B
    bp1 = B.get_body("bp1_testbed")
    assert bp1.bulk_density == 1750.0 and bp1.g == 9.81
    assert "ANALOG" in bp1.confidence and "NOT fabricated" in bp1.confidence
    tw = vtw.VehicleTwin.assemble("v", vehicle="ipex", body="earth", soil="bp1_testbed")
    moon = vtw.VehicleTwin.assemble("m", vehicle="ipex", body="moon")
    assert tw.gravity_ms2 == 9.81 and moon.gravity_ms2 != tw.gravity_ms2
