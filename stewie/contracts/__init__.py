"""FS-02 / §25 Phase 0: the typed onboard-autonomy CONTRACT SPINE.

Versioned pydantic models the backend APIs and cockpit views consume INSTEAD of ad hoc payloads --
one source of truth for the autonomy surfaces. Every schema is STRICT (``extra='forbid'`` -> unknown
fields are rejected at the route boundary, which is FS-02's "schema validation at route boundaries")
and carries ``schema_version`` for migratability. Models are frozen (a contract snapshot is immutable).

The codebase is not missing capability -- it is missing one typed contract unifying the surfaces. The
spine schemas are: WorldState, VehicleState, FleetState, BeliefState, PlanResult, ExecutionEvent,
EphemerisObservation, NavFactor, ModelArtifact, ConstructionSkill. This first brick lands the base +
EphemerisObservation / VehicleState / FleetState (with ResourceReservation); the rest follow in
subsequent Phase-0 bricks, then Phase 1 wires route handlers to them.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

#: bump on any backwards-incompatible spine change (drives migration; surfaced in every schema).
SPINE_VERSION = "1.0"


class Contract(BaseModel):
    """Base for every spine schema: strict (reject unknown fields = boundary validation), frozen
    (immutable snapshot), and version-stamped."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: str = SPINE_VERSION


class EphemerisObservation(Contract):
    """FS-06 / §25.3: the SINGLE ephemeris+azimuth authority record that every shadow, illumination,
    navigation-risk, camera-policy, and Navigation consumer reads. ``azimuth_convention`` is REQUIRED and
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


class TimelineFrame(Contract):
    """FS-04/FS-15: one motion segment on the mission ACTIVITY timeline -- a [t0, t1] interval in one
    `phase` (drive | dig | cut | dump | fill | haul | recharge | goto), the rover moving (x0,y0)->(x1,y1)
    with the battery going `batt0_frac`->`batt1_frac` and `cum_mass_kg` regolith moved so far. The cockpit
    Report-pane ACTIVITY gantt + battery curve + the 3-D playback render these; `build_timeline` emits them.
    Distinct from ExecutionEvent (a discrete event); a frame is a continuous segment."""
    t0: float = Field(ge=0.0)
    t1: float = Field(ge=0.0)
    phase: str             # drive | dig | cut | dump | fill | haul | recharge | goto
    x0: float = 0.0
    y0: float = 0.0
    x1: float = 0.0
    y1: float = 0.0
    batt0_frac: float = Field(default=1.0, ge=0.0, le=1.0)
    batt1_frac: float = Field(default=1.0, ge=0.0, le=1.0)
    cum_mass_kg: float = Field(default=0.0, ge=0.0)


class LocalizationFix(Contract):
    """FS-07/FS-15: one leg on the mission est-vs-truth localization trace -- the believed pose `est`, the
    eval-only `true` pose, the position `sigma`, and which real fix (`dem`|`beacon`|`none`) corrected this
    leg. The cockpit Nav pane's mission-localization plot renders these. The I3 truth firewall governs the
    ESTIMATOR (which never sees truth); this is the after-the-fact DIAGNOSTIC display of how the estimate did
    vs truth, which `run_closed_loop` already emits. A frozen typed view of that trace."""
    est: tuple[float, float]
    true: tuple[float, float]      # eval-only ground-truth pose (display/diagnostic, not an estimator input)
    sigma: float = Field(ge=0.0)
    fix: str                       # dem | beacon | none


class NavFactor(Contract):
    """FS-07 (PM-07): one pose-graph factor from the Navigation articulation/shadow/parallax loop. `accepted`
    is the residual-gate verdict -- a rejected factor (false closure / bad shadow match) never enters the
    graph. `information` (inverse-covariance scale) is non-negative."""
    factor_id: str
    kind: str          # shadow | parallax | loop | absolute
    keyframe_i: int = Field(ge=0)
    keyframe_j: int = Field(ge=0)
    residual: float
    information: float = Field(default=1.0, ge=0.0)
    accepted: bool


class PerceptionState(Contract):
    """FS-15 / PRD §26.2: the Perception pane's normalized sensor-health snapshot. This is not the dense
    point cloud itself; it is the typed status/card payload the cockpit renders for the selected depth
    source, panorama/shadow egress, covariance, and truth-denial state."""
    source_profile: str = "stereo_sgbm"       # stereo_sgbm | stereo_neural | lidar | rgbd | replay
    frame_id: str = "ipex_front_stereo_optical"
    point_topic: str = "/stewie/perception/points"
    point_count: int = Field(default=0, ge=0)
    valid_fraction: float = Field(default=0.0, ge=0.0, le=1.0)
    range_min_m: float = Field(default=0.0, ge=0.0)
    range_max_m: float = Field(default=0.0, ge=0.0)
    covariance_m: float = Field(default=0.0, ge=0.0)
    panorama_cameras: int = Field(default=0, ge=0)
    shadow_landmarks: int = Field(default=0, ge=0)
    accepted_factors: int = Field(default=0, ge=0)
    no_truth: bool = True
    evidence_class: str = "simulation"        # simulation | replay | bench | hil | live

    @field_validator("source_profile")
    @classmethod
    def _known_source_profile(cls, v: str) -> str:
        allowed = {"stereo_sgbm", "stereo_neural", "lidar", "rgbd", "replay"}
        if v not in allowed:
            raise ValueError(f"unknown depth source profile: {v}")
        return v

    @field_validator("evidence_class")
    @classmethod
    def _known_evidence_class(cls, v: str) -> str:
        allowed = {"simulation", "replay", "bench", "hil", "live"}
        if v not in allowed:
            raise ValueError(f"unknown perception evidence class: {v}")
        return v

    @field_validator("no_truth")
    @classmethod
    def _must_be_truth_denied(cls, v: bool) -> bool:
        if not v:
            raise ValueError("PerceptionState exposed to the cockpit must be truth-denied")
        return v

    @model_validator(mode="after")
    def _range_order(self) -> "PerceptionState":
        if self.range_max_m and self.range_max_m < self.range_min_m:
            raise ValueError("range_max_m must be >= range_min_m")
        return self


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
        """ML-01/RL-01 gate: a model may be DEPLOYED only when it has recorded training/eval lineage
        (non-empty -- RL-01: training scripts alone never make a policy operational), declared both typed
        schemas, positive latency+memory budgets, calibration, an OOD detector, a deterministic fallback,
        and is off the command path. Definition without these is allowed; deployment is not."""
        return bool(
            self.dataset_lineage and self.eval_split
            and self.input_schema and self.output_schema
            and self.latency_budget_ms > 0 and self.memory_budget_mb > 0
            and self.calibrated and self.ood_detector
            and (self.fallback or self.rollback_to)
            and not self.command_path)


class ExcavationState(Contract):
    """ML-05: the unified excavation-state ESTIMATE the estimator layer emits -- digging state, drum
    fill, wheel slip, stall risk, and the estimator's own confidence, each in a bounded domain so a
    bad value is rejected at the boundary. HONESTY GATE: the fusion is built on conserved-sim signals
    and the published ICE-RASSOR FDC uncertainty band (NTRS 20210022781), NOT on real IPEx/AutoDig
    telemetry (external, gated) -- so while ``calibration`` is "uncalibrated" the estimate MUST stay
    ``advisory`` (a validator enforces it; no consumer may treat it as flight-calibrated)."""
    digging_state: str                                    # idle | driving | hauling | digging | offload_due
    fill_fraction: float = Field(ge=0.0, le=1.0)
    slip: float = Field(ge=0.0, le=1.0)
    stall_risk: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    advisory: bool = True
    calibration: str = "uncalibrated"                     # uncalibrated | ipex_autodig
    source: str = ""

    @field_validator("digging_state")
    @classmethod
    def _known_digging_state(cls, v: str) -> str:
        allowed = {"idle", "driving", "hauling", "digging", "offload_due"}
        if v not in allowed:
            raise ValueError(f"unknown digging_state: {v}")
        return v

    @field_validator("calibration")
    @classmethod
    def _known_calibration(cls, v: str) -> str:
        allowed = {"uncalibrated", "ipex_autodig"}
        if v not in allowed:
            raise ValueError(f"unknown calibration: {v}")
        return v

    @model_validator(mode="after")
    def _uncalibrated_stays_advisory(self) -> "ExcavationState":
        if self.calibration == "uncalibrated" and not self.advisory:
            raise ValueError("ML-05: an uncalibrated excavation-state estimate must stay advisory")
        return self


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


# MO-01 / MO-03 / MO-04 (§27 mission-ops): the mission-intent, provenance, and labeling contracts the
# operational UI renders. Defined in `mission_ops` to keep this base module small; re-exported here so
# consumers use the same `from stewie import contracts as C; C.MissionIntent` access as the spine above.
from .mission_ops import (  # noqa: E402  (re-export after the base Contract it builds on)
    AcceptanceCriterion,
    CompiledOrder,
    Constraint,
    ConstraintKind,
    Contingency,
    ContingencyPolicy,
    DataLabel,
    KeepOutRegion,
    LabeledValue,
    MissionIntent,
    Objective,
    PriorityTier,
    Provenance,
    ProvenancedValue,
    combine_provenance,
    compile_order,
)

# MO-02 (§27.2.C / review P1-2): the mission-executive STATE MACHINE. Lands in its own `executive`
# module (the spine for live execution that gates the Execute screen); re-exported here so consumers
# use `C.MissionExecutive` like the MO-01 spine. The state machine itself is pure + on-host (not wired
# to live ROS/hardware -- that tier is gated).
from .executive import (  # noqa: E402  (re-export after the base Contract it builds on)
    ExecutiveState,
    IllegalTransition,
    MissionExecutive,
    SignedRevision,
)

# re-export the mission-ops contracts as the public surface of this package (so pyflakes sees the
# above imports as used and `from stewie.contracts import MissionIntent` works without reaching in).
class RegolithVolumeEstimate(Contract):
    """[REQ:FR-13] Observed before/after volume + uncertainty evidence for surface design. A conserved,
    uncertainty-carrying moved-regolith estimate from a before/after terrain delta, cross-checked against
    the conserved-authority mass and (when available) the drum sensor, with a confidence class + acceptance
    status, linked to a world transaction. Extends ML-06's estimate_moved_regolith into a typed contract."""
    work_order_id: str
    before_source: str
    after_source: str
    change_cells: int = Field(ge=0)
    observed_mass_kg: float = Field(ge=0.0)
    fill_mass_kg: float = Field(ge=0.0)
    uncertainty_kg: float = Field(ge=0.0)
    uncertainty_frac: float = Field(ge=0.0)
    lower_kg: float
    upper_kg: float
    conserved_err_kg: float | None = None
    agreement_conserved: bool | None = None
    drum_inferred_kg: float | None = None
    agreement_drum: bool | None = None
    confidence_class: str          # high | medium | low, from uncertainty_frac
    acceptance: str                # accepted | review, from the cross-check agreements
    transaction_id: str

    @field_validator("confidence_class")
    @classmethod
    def _known_confidence(cls, v: str) -> str:
        if v not in ("high", "medium", "low"):
            raise ValueError(f"unknown confidence_class: {v}")
        return v

    @field_validator("acceptance")
    @classmethod
    def _known_acceptance(cls, v: str) -> str:
        if v not in ("accepted", "review"):
            raise ValueError(f"unknown acceptance: {v}")
        return v

    @classmethod
    def from_delta(cls, before_h, after_h, cell_m, *, work_order_id, before_source, after_source,
                   transaction_id, density_kg_m3, height_rmse_m=0.0, density_frac=0.0,
                   conserved_mass_kg=None, drum_inferred_kg=None):
        """Build the typed evidence from a before/after terrain delta via estimate_moved_regolith (ML-06).
        ``height_rmse_m`` (observation RMSE) and ``density_frac`` (in-situ density envelope) widen the
        uncertainty band; confidence_class is derived from the uncertainty fraction; acceptance is
        'accepted' only when every available cross-check (conservation, drum) AGREES, else 'review'."""
        import numpy as np

        from lode.regolith_volume import estimate_moved_regolith
        e = estimate_moved_regolith(before_h, after_h, cell_m, density_kg_m3=density_kg_m3,
                                    height_rmse_m=height_rmse_m, density_frac=density_frac,
                                    conserved_mass_kg=conserved_mass_kg, drum_inferred_kg=drum_inferred_kg)
        change = int(np.count_nonzero(np.asarray(after_h, dtype=float) - np.asarray(before_h, dtype=float)))
        uf = float(e["uncertainty_frac"])
        conf = "high" if uf <= 0.05 else ("medium" if uf <= 0.15 else "low")
        present = [c for c in (e.get("agreement_conserved"), e.get("agreement_drum")) if c is not None]
        accept = "accepted" if present and all(present) else "review"
        return cls(work_order_id=work_order_id, before_source=before_source, after_source=after_source,
                   change_cells=change, observed_mass_kg=float(e["observed_mass_kg"]),
                   fill_mass_kg=float(e["fill_mass_kg"]), uncertainty_kg=float(e["uncertainty_kg"]),
                   uncertainty_frac=uf, lower_kg=float(e["lower_kg"]), upper_kg=float(e["upper_kg"]),
                   conserved_err_kg=e.get("conserved_err_kg"), agreement_conserved=e.get("agreement_conserved"),
                   drum_inferred_kg=e.get("drum_inferred_kg"), agreement_drum=e.get("agreement_drum"),
                   confidence_class=conf, acceptance=accept, transaction_id=transaction_id)


__all__ = [
    "RegolithVolumeEstimate",
    "AcceptanceCriterion",
    "CompiledOrder",
    "Constraint",
    "ConstraintKind",
    "Contingency",
    "ContingencyPolicy",
    "DataLabel",
    "ExecutiveState",
    "IllegalTransition",
    "KeepOutRegion",
    "LabeledValue",
    "MissionExecutive",
    "MissionIntent",
    "Objective",
    "PriorityTier",
    "Provenance",
    "ProvenancedValue",
    "SignedRevision",
    "combine_provenance",
    "compile_order",
]
