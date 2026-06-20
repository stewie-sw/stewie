"""FS-02 / §25 Phase 0: the typed contract spine. Each schema is strict (extra='forbid' -> unknown
fields rejected at the boundary), carries schema_version, and enforces physical domains. This first
brick covers the base + EphemerisObservation / VehicleState / FleetState; the remaining spine schemas
(WorldState, BeliefState, PlanResult, ExecutionEvent, ARGUSFactor, ModelArtifact, ConstructionSkill)
land in subsequent Phase-0 bricks.

Run: <venv>/bin/python -m pytest stewie/contracts/test_contracts.py -q
"""
import pytest
from pydantic import ValidationError

from stewie import contracts as C


# ---- EphemerisObservation (FS-06: the single azimuth authority; §25.3 explicit convention) ------

def test_ephemeris_valid_and_versioned():
    e = C.EphemerisObservation(mission_t_s=0.0, site_lat_deg=-87.4, site_lon_deg=10.0,
                               sun_az_deg=90.0, sun_el_deg=6.0, azimuth_convention="north_cw")
    assert e.schema_version == C.SPINE_VERSION
    assert e.azimuth_convention == "north_cw" and e.frame == "MOON_ME"


def test_ephemeris_azimuth_convention_is_required():
    with pytest.raises(ValidationError):                       # §25.3: no private/implicit convention
        C.EphemerisObservation(mission_t_s=0.0, site_lat_deg=0.0, site_lon_deg=0.0,
                               sun_az_deg=0.0, sun_el_deg=0.0)


def test_ephemeris_rejects_out_of_domain():  # [REQ:CT-05]
    base = dict(mission_t_s=0.0, site_lat_deg=0.0, site_lon_deg=0.0, sun_el_deg=0.0,
                azimuth_convention="north_cw")
    with pytest.raises(ValidationError):
        C.EphemerisObservation(sun_az_deg=360.0, **base)       # az must be [0,360)
    with pytest.raises(ValidationError):
        C.EphemerisObservation(sun_az_deg=10.0, **{**base, "sun_el_deg": 91.0})  # el must be [-90,90]


def test_strict_rejects_unknown_fields():
    with pytest.raises(ValidationError):                       # extra='forbid' = boundary validation
        C.EphemerisObservation.model_validate(
            {"mission_t_s": 0.0, "site_lat_deg": 0.0, "site_lon_deg": 0.0, "sun_az_deg": 0.0,
             "sun_el_deg": 0.0, "azimuth_convention": "north_cw", "rogue_field": 1})


# ---- VehicleState (FS-04: per-rover belief) ----------------------------------------------------

def test_vehicle_state_valid_and_domains():
    v = C.VehicleState(vehicle_id="ipex", row=10.0, col=20.0, soc=0.8, slip=0.1, status="driving")
    assert v.vehicle_id == "ipex" and v.schema_version == C.SPINE_VERSION
    with pytest.raises(ValidationError):
        C.VehicleState(vehicle_id="x", row=0.0, col=0.0, soc=1.5)     # soc must be [0,1]


def test_vehicle_state_round_trips():
    v = C.VehicleState(vehicle_id="r2", row=1.0, col=2.0, yaw_rad=0.5)
    assert C.VehicleState.model_validate(v.model_dump()) == v


# ---- FleetState (FS-04: coordinated snapshot, ties FL-03 reservations) -------------------------

def test_fleet_state_nests_and_defaults():
    fs = C.FleetState(
        vehicles=[C.VehicleState(vehicle_id="a", row=0.0, col=0.0),
                  C.VehicleState(vehicle_id="b", row=5.0, col=5.0)],
        reservations=[C.ResourceReservation(resource_id="chg", vehicle_id="a", t_start=0.0, t_end=10.0)])
    assert len(fs.vehicles) == 2 and fs.conflicts == 0           # deconflicted by default
    assert fs.reservations[0].resource_id == "chg"
    assert C.FleetState.model_validate(fs.model_dump()) == fs    # round-trip


def test_fleet_state_conflicts_nonnegative():
    with pytest.raises(ValidationError):
        C.FleetState(conflicts=-1)


# ---- the remaining Phase-0 spine schemas --------------------------------------------------------

def test_world_state_descriptor():
    w = C.WorldState(rows=2000, cols=2000, cell_m=5.0, dem_source="haworth_10km_5m", observed_fraction=0.3)
    assert w.datum_radius_m == 1737400 and w.schema_version == C.SPINE_VERSION
    with pytest.raises(ValidationError):
        C.WorldState(rows=0, cols=10, cell_m=5.0)                  # rows must be > 0


def test_belief_state():
    b = C.BeliefState(vehicle_id="ipex", row=10.0, col=20.0, pos_sigma_m=0.5, localized=True)
    assert b.localized and b.last_relocalization_t_s is None
    with pytest.raises(ValidationError):
        C.BeliefState(vehicle_id="x", row=0.0, col=0.0, pos_sigma_m=-1.0)    # sigma >= 0


def test_plan_result():
    p = C.PlanResult(plan_id="abc", feasible=True, n_orders=5, vehicles=2, makespan_s=100.0, energy_j=5e5)
    assert p.feasible and p.vehicles == 2
    assert p.recharges == 0 and p.drum_cycles == 0 and p.cut_passes == 1 and p.resolved_algorithm == ""
    with pytest.raises(ValidationError):
        C.PlanResult(plan_id="x", feasible=True, n_orders=1, vehicles=0, makespan_s=1.0, energy_j=1.0)
    # FS-15 headline totals the dashboard/CONOPS consume
    q = C.PlanResult(plan_id="d", feasible=True, n_orders=2, vehicles=1, makespan_s=1.0, energy_j=1.0,
                     recharges=2, drum_cycles=61, cut_passes=2, resolved_algorithm="nearest")
    assert q.recharges == 2 and q.drum_cycles == 61 and q.cut_passes == 2 and q.resolved_algorithm == "nearest"
    with pytest.raises(ValidationError):
        C.PlanResult(plan_id="n", feasible=True, n_orders=1, vehicles=1, makespan_s=1.0, energy_j=1.0,
                     recharges=-1)                          # ge=0 boundary holds


def test_execution_event_round_trips():
    e = C.ExecutionEvent(t_s=1.0, vehicle_id="ipex", kind="leg", outcome="ok")
    assert C.ExecutionEvent.model_validate(e.model_dump()) == e


def test_timeline_frame():
    f = C.TimelineFrame(t0=0.0, t1=174.7, phase="drive", x0=0.0, y0=0.0, x1=40.0, y1=30.0,
                        batt0_frac=1.0, batt1_frac=0.9985, cum_mass_kg=0.0)
    assert f.phase == "drive" and C.TimelineFrame.model_validate(f.model_dump()) == f
    with pytest.raises(ValidationError):
        C.TimelineFrame(t0=0.0, t1=1.0, phase="dig", batt0_frac=1.2)   # battery fraction in [0,1]


def test_argus_factor():
    f = C.ARGUSFactor(factor_id="f1", kind="shadow", keyframe_i=0, keyframe_j=3, residual=0.02, accepted=True)
    assert f.accepted and f.information >= 0
    with pytest.raises(ValidationError):
        C.ARGUSFactor(factor_id="f", kind="loop", keyframe_i=-1, keyframe_j=0, residual=0.0, accepted=False)


def test_model_artifact_cannot_be_on_command_path():
    m = C.ModelArtifact(model_id="m1", name="rocknet", version="1", task="rock_classify",
                        dataset_lineage="nac-2024", eval_split="80/20")
    assert m.command_path is False
    with pytest.raises(ValidationError):                          # §25.3: no model on the command path
        C.ModelArtifact(model_id="m2", name="x", version="1", task="llm_planner",
                        dataset_lineage="d", eval_split="s", command_path=True)


def test_model_artifact_deployment_requires_declared_schemas_and_budgets():  # [REQ:ML-01]
    # ML-01: a minimally-defined model is NOT deployment-ready (no typed schemas / budgets declared)
    bare = C.ModelArtifact(model_id="m1", name="rocknet", version="1", task="rock_classify",
                           dataset_lineage="nac-2024", eval_split="80/20")
    assert bare.deployment_ready is False
    # fully declared (typed I/O + positive budgets + calibration + OOD + fallback, off command path) -> ready
    ready = C.ModelArtifact(model_id="m1", name="rocknet", version="1", task="rock_classify",
                            dataset_lineage="nac-2024", eval_split="80/20",
                            input_schema="GrayFrame", output_schema="RockDetections",
                            latency_budget_ms=50.0, memory_budget_mb=512.0,
                            calibrated=True, ood_detector=True, fallback="classical_cv_detector")
    assert ready.deployment_ready is True
    with pytest.raises(ValidationError):                          # negative inference budget rejected
        C.ModelArtifact(model_id="m3", name="x", version="1", task="rock_classify",
                        dataset_lineage="d", eval_split="s", latency_budget_ms=-1.0)


def test_construction_skill_must_be_closed_loop():
    s = C.ConstructionSkill(skill_id="dock1", name="dock", kind="dock", version="1", n_steps=20)
    assert s.closed_loop is True and s.approved is False
    with pytest.raises(ValidationError):                          # §25.3: no open-loop replay
        C.ConstructionSkill(skill_id="s2", name="x", kind="excavate", version="1", n_steps=5,
                            closed_loop=False)
