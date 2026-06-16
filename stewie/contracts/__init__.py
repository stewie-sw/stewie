"""FS-02 / §25 Phase 0: the typed onboard-autonomy CONTRACT SPINE.

Versioned pydantic models the backend APIs and cockpit views consume INSTEAD of ad hoc payloads --
one source of truth for the autonomy surfaces. Every schema is STRICT (``extra='forbid'`` -> unknown
fields are rejected at the route boundary, which is FS-02's "schema validation at route boundaries")
and carries ``schema_version`` for migratability. Models are frozen (a contract snapshot is immutable).

The codebase is not missing capability -- it is missing one typed contract unifying the surfaces. The
spine schemas are: WorldState, VehicleState, FleetState, BeliefState, PlanResult, ExecutionEvent,
EphemerisObservation, ARGUSFactor, ModelArtifact, ConstructionSkill. This first brick lands the base +
EphemerisObservation / VehicleState / FleetState (with ResourceReservation); the rest follow in
subsequent Phase-0 bricks, then Phase 1 wires route handlers to them.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

#: bump on any backwards-incompatible spine change (drives migration; surfaced in every schema).
SPINE_VERSION = "1.0"


class Contract(BaseModel):
    """Base for every spine schema: strict (reject unknown fields = boundary validation), frozen
    (immutable snapshot), and version-stamped."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: str = SPINE_VERSION


class EphemerisObservation(Contract):
    """FS-06 / §25.3: the SINGLE ephemeris+azimuth authority record that every shadow, illumination,
    navigation-risk, camera-policy, and ARGUS consumer reads. ``azimuth_convention`` is REQUIRED and
    explicit -- no consumer may assume a private convention; it is shared, tested, and UI-displayed."""
    mission_t_s: float
    body: str = "moon"
    site_lat_deg: float = Field(ge=-90.0, le=90.0)
    site_lon_deg: float = Field(ge=-360.0, le=360.0)
    frame: str = "MOON_ME"
    sun_az_deg: float = Field(ge=0.0, lt=360.0)
    sun_el_deg: float = Field(ge=-90.0, le=90.0)
    azimuth_convention: str
    uncertainty_deg: float = Field(default=0.0, ge=0.0)
    source: str = "spice"


class VehicleState(Contract):
    """FS-04: one rover's live state -- the per-vehicle belief the Fleet pane and the coordinator
    consume. Domains are bounded (soc/slip in [0,1]) so a bad estimate is rejected at the boundary."""
    vehicle_id: str
    role: str = "ipex"
    row: float
    col: float
    yaw_rad: float = 0.0
    soc: float = Field(default=1.0, ge=0.0, le=1.0)
    slip: float = Field(default=0.0, ge=0.0, le=1.0)
    sinkage_m: float = Field(default=0.0, ge=0.0)
    entrapped: bool = False
    status: str = "idle"      # idle | driving | excavating | charging | blocked | safed


class ResourceReservation(Contract):
    """A fleet shared-resource claim over [t_start, t_end) -- the contract-layer mirror of
    lode.fleet_resources.Reservation (FL-03)."""
    resource_id: str
    vehicle_id: str
    t_start: float
    t_end: float


class FleetState(Contract):
    """FS-04: the coordinated fleet snapshot the Fleet pane renders -- per-vehicle state, the active
    shared-resource reservations, and the conflict count (0 = fully deconflicted; §25.3 requires both
    the backend result and the UI to represent conflicts)."""
    vehicles: list[VehicleState] = Field(default_factory=list)
    reservations: list[ResourceReservation] = Field(default_factory=list)
    conflicts: int = Field(default=0, ge=0)
