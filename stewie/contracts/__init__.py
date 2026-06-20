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

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
    """FS-04: one rover's PHYSICAL state -- the actual pose + soc/slip/sinkage/status, i.e. simulation
    TRUTH or live TELEMETRY. This is DISTINCT from BeliefState (the onboard estimator's belief about its
    pose + uncertainty): the same rover from two stances -- what it IS vs what it THINKS it is, whose
    difference is the drift the cockpit shows. PO-10 / §25.3 require labelling truth vs belief vs live;
    this is the truth/telemetry side. Domains are bounded (soc/slip in [0,1]) so a bad value is rejected
    at the boundary."""
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


class WorldState(Contract):
    """FS-02 (TW-05): the authoritative terrain/twin snapshot DESCRIPTOR -- grid geometry, datum,
    provenance, observed coverage, and whether construction has mutated the terrain vs the prior DEM.
    The raw rasters live in the twin store; the contract carries the metadata a consumer reasons over."""
    body: str = "moon"
    frame: str = "MOON_ME"
    rows: int = Field(gt=0)
    cols: int = Field(gt=0)
    cell_m: float = Field(gt=0.0)
    datum_radius_m: int = 1737400
    observed_fraction: float = Field(default=0.0, ge=0.0, le=1.0)
    dem_source: str = "haworth_10km_5m"            # a dart.dem_sources id
    mutated: bool = False


class BeliefState(Contract):
    """FS-04/FS-07: one rover's estimator belief -- map-relative pose + uncertainty + localization
    health. localized=False means the estimate has diverged and a relocalization stop is due (SN-10)."""
    vehicle_id: str
    row: float
    col: float
    yaw_rad: float = 0.0
    pos_sigma_m: float = Field(default=0.0, ge=0.0)
    yaw_sigma_rad: float = Field(default=0.0, ge=0.0)
    localized: bool = True
    last_relocalization_t_s: float | None = None


class PlanResult(Contract):
    """CP-01/FS-02: the immutable plan SUMMARY one plan produces and every consumer shares (totals,
    feasibility, makespan). The full per-leg Plan IR lives in the planner; this is the typed headline.
    The cockpit's dashboard strip + CONOPS line consume this via the adapters.js view model (FS-15)."""
    plan_id: str
    feasible: bool
    n_orders: int = Field(ge=0)
    vehicles: int = Field(ge=1)
    makespan_s: float = Field(ge=0.0)
    energy_j: float = Field(ge=0.0)
    mass_moved_kg: float = Field(default=0.0, ge=0.0)
    blocked_legs: int = Field(default=0, ge=0)
    # FS-15: the headline totals the Report-pane dashboard + CONOPS line display (so the cockpit can
    # consume a typed view model instead of reaching into the legacy /plan `totals` dict by ad-hoc key).
    recharges: int = Field(default=0, ge=0)            # mid-mission charger returns (totals['charges'])
    drum_cycles: int = Field(default=0, ge=0)          # drum offload cycles
    cut_passes: int = Field(default=1, ge=0)           # excavation passes
    resolved_algorithm: str = ""                       # the solver actually used (e.g. 'nearest', 'beam')


class ExecutionEvent(Contract):
    """FS-04: one timestamped event on the execution timeline -- command issued, leg complete, conflict,
    acceptance, safe, replan. The Fleet/Report panes render these; the mission executive emits them."""
    t_s: float
    vehicle_id: str
    kind: str          # command | leg | conflict | acceptance | safe | replan
    detail: str = ""
    outcome: str = "ok"   # ok | blocked | entrapped | rejected | safed


class ARGUSFactor(Contract):
    """FS-07 (PM-07): one pose-graph factor from the ARGUS articulation/shadow/parallax loop. `accepted`
    is the residual-gate verdict -- a rejected factor (false closure / bad shadow match) never enters the
    graph. `information` (inverse-covariance scale) is non-negative."""
    factor_id: str
    kind: str          # shadow | parallax | loop | absolute
    keyframe_i: int = Field(ge=0)
    keyframe_j: int = Field(ge=0)
    residual: float
    information: float = Field(default=1.0, ge=0.0)
    accepted: bool


class ModelArtifact(Contract):
    """FS-12 / §25.3: a registered learned model. Every field that gates safe deployment is explicit;
    `command_path` MUST be False -- no learned model directly controls the rover (it emits typed
    estimates; deterministic planners + safety + role gates + the executive decide command emission)."""
    model_id: str
    name: str
    version: str
    task: str          # terrain_assess | rock_classify | shadow_slam | excavation_state | volume | llm_planner | assistant
    dataset_lineage: str
    eval_split: str
    # ML-01: every model DECLARES its typed I/O contract + its inference budgets. Empty/zero = undeclared,
    # which fails `deployment_ready` (a model may be defined without these, but not DEPLOYED).
    input_schema: str = ""        # the typed input contract name the executive feeds it
    output_schema: str = ""       # the typed estimate contract it emits (the executive consumes typed only)
    latency_budget_ms: float = 0.0
    memory_budget_mb: float = 0.0
    calibrated: bool = False
    ood_detector: bool = False
    fallback: str | None = None   # the deterministic safe-default when OOD / low-confidence (runtime fallback)
    quantization: str = "fp32"
    rollback_to: str | None = None  # the prior model version to roll back to (deploy-time)
    command_path: bool = False

    @field_validator("command_path")
    @classmethod
    def _no_command_path(cls, v: bool) -> bool:
        if v:
            raise ValueError("§25.3: no learned model may be on the rover command path")
        return v

    @field_validator("latency_budget_ms", "memory_budget_mb")
    @classmethod
    def _budgets_nonneg(cls, v: float) -> float:
        if v < 0:
            raise ValueError("§25.3: model inference budgets must be >= 0")
        return v

    @property
    def deployment_ready(self) -> bool:
        """ML-01 gate: a model may be DEPLOYED only when it has declared both typed schemas, positive
        latency+memory budgets, calibration, an OOD detector, a deterministic fallback, and is off the
        command path. Definition without these is allowed; deployment is not."""
        return bool(
            self.input_schema and self.output_schema
            and self.latency_budget_ms > 0 and self.memory_budget_mb > 0
            and self.calibrated and self.ood_detector
            and (self.fallback or self.rollback_to)
            and not self.command_path)


class ConstructionSkill(Contract):
    """FS-13 / §25.3: a recorded construction/docking movement primitive. `closed_loop` MUST be True --
    no primitive replays open-loop; estimator feedback + safing checks are part of it. Carries the step
    count, the approval gate, and an acceptance note (uncertainty bands live with the acceptance event)."""
    skill_id: str
    name: str
    kind: str          # excavate | dump | berm | traverse | dock
    version: str
    n_steps: int = Field(ge=1)
    closed_loop: bool = True
    approved: bool = False
    acceptance_note: str = ""

    @field_validator("closed_loop")
    @classmethod
    def _must_close_loop(cls, v: bool) -> bool:
        if not v:
            raise ValueError("§25.3: no construction/docking primitive may replay open-loop")
        return v
