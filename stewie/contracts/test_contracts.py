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


def test_ephemeris_rejects_out_of_domain():
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
