"""[REQ:RS-01] The typed RUNTIME-SPINE contracts -- the ONLY payloads that cross the perception ->
mapping -> localization -> planning -> control -> UI stage boundaries. No module passes a raw ad-hoc
dict across a stage boundary; every crossing is one of these strict, frozen, version-stamped Contract
schemas (``extra='forbid'`` rejects unknown/wrong-shape fields AT the boundary -- that IS the contract).

These extend the existing FS-02 contract spine (``stewie.contracts``) rather than inventing a parallel
one: the localization-state boundary IS the existing ``BeliefState`` (re-exported here as
``LocalizationState``), and the world-transaction boundary IS the existing
``stewie.twin.envelope.WorldTransaction`` (a dataclass, referenced in the registry). The six schemas the
spine was missing -- ``DepthObservation``, ``VisualHazardObservation``, ``ObservedMapUpdate``,
``HazardMapDescriptor``, ``CostmapSnapshot``, ``TrajectoryCommand``, ``CommandEligibility`` -- are
defined here as boundary DESCRIPTORS (the metadata/verdict that crosses the seam; the raw rasters/clouds
live in their stores, exactly as ``WorldState`` describes the twin without carrying its rasters).
"""
from __future__ import annotations

from pydantic import Field, field_validator

from stewie.contracts import BeliefState, Contract

#: the localization-state boundary payload IS the estimator belief (FS-04/FS-07). Re-exported under the
#: runtime-spine name so the registry reads uniformly; there is ONE localization contract, not two.
LocalizationState = BeliefState


class DepthObservation(Contract):
    """The normalized depth / point-cloud observation a perception node emits from a stereo/LiDAR/replay
    frame (the boundary descriptor; the dense cloud lives on the ROS topic named by ``point_topic``)."""
    t_s: float = Field(ge=0.0)
    source: str = "stereo"                 # stereo | lidar | rgbd | replay
    frame_id: str = "ipex_front_stereo_optical"
    point_topic: str = "/stewie/perception/points"
    width: int = Field(default=0, ge=0)
    height: int = Field(default=0, ge=0)
    point_count: int = Field(default=0, ge=0)
    range_min_m: float = Field(default=0.0, ge=0.0)
    range_max_m: float = Field(default=0.0, ge=0.0)
    valid_fraction: float = Field(default=0.0, ge=0.0, le=1.0)
    no_truth: bool = True

    @field_validator("source")
    @classmethod
    def _known_source(cls, v: str) -> str:
        if v not in {"stereo", "lidar", "rgbd", "replay"}:
            raise ValueError(f"unknown depth source: {v}")
        return v


class HazardDetection(Contract):
    """One boulder/obstacle candidate the visual hazard classifier proposed, with its ACCEPT/REJECT
    verdict and the reason (size-gate / appearance / stereo). ``confidence`` is bounded [0, 1]."""
    kind: str = "rock"                     # rock | obstacle | negative | shadow
    confidence: float = Field(ge=0.0, le=1.0)
    accepted: bool
    reason: str = ""
    centroid_row: float = 0.0
    centroid_col: float = 0.0
    size_m: float = Field(default=0.0, ge=0.0)


class VisualHazardObservation(Contract):
    """The visual hazard classifier's per-frame output: the detections (each with its accept/reject
    verdict + reason), from image appearance only -- no truth input (``no_truth``)."""
    t_s: float = Field(ge=0.0)
    source: str = "stereo"
    detections: list[HazardDetection] = Field(default_factory=list)
    no_truth: bool = True


class ObservedMapUpdate(Contract):
    """An update to the observed world one mapping step folds in -- WHICH layer, its geometry, its
    provenance (the prior-vs-observed-vs-forecast-vs-edited distinction RS-02/DT-04 require), the map
    uncertainty, and how much of the site the observation now covers."""
    t_s: float = Field(ge=0.0)
    layer: str                             # dem | occupancy | rock | changed
    rows: int = Field(gt=0)
    cols: int = Field(gt=0)
    cell_m: float = Field(gt=0.0)
    provenance: str = "observed"           # prior | observed | forecast | edited
    uncertainty_m: float = Field(default=0.0, ge=0.0)
    coverage_fraction: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("layer")
    @classmethod
    def _known_layer(cls, v: str) -> str:
        if v not in {"dem", "occupancy", "rock", "changed"}:
            raise ValueError(f"unknown observed-map layer: {v}")
        return v

    @field_validator("provenance")
    @classmethod
    def _known_provenance(cls, v: str) -> str:
        if v not in {"prior", "observed", "forecast", "edited"}:
            raise ValueError(f"unknown map provenance: {v}")
        return v


class HazardMapDescriptor(Contract):
    """The boundary descriptor of a ``dart.hazard_map.HazardMap`` -- grid geometry + the no-go fraction +
    the cost/confidence summary a downstream planner reasons over (the raw slope/roughness/rock grids
    stay in DART). Complements the dataclass; it is what crosses the mapping->planning seam."""
    rows: int = Field(gt=0)
    cols: int = Field(gt=0)
    cell_m: float = Field(gt=0.0)
    n_classes: int = Field(default=0, ge=0)
    no_go_fraction: float = Field(default=0.0, ge=0.0, le=1.0)
    max_cost: float = Field(default=0.0, ge=0.0)
    mean_confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class CostmapSnapshot(Contract):
    """The composed terrain+hazard costmap descriptor at the planning boundary -- geometry, the ordered
    layer names composed (``lode.costmap_layers``), the blocking-reason tags, and the max cost. The dense
    cost grid lives in LODE; this is the typed summary the route planner + cockpit consume."""
    t_s: float = Field(ge=0.0)
    rows: int = Field(gt=0)
    cols: int = Field(gt=0)
    cell_m: float = Field(gt=0.0)
    layers: list[str] = Field(default_factory=list)
    blocking_reasons: list[str] = Field(default_factory=list)
    max_cost: float = Field(default=0.0, ge=0.0)


class TrajectoryCommand(Contract):
    """The single BOUNDED next command the control stage lowers (RS-03): a goto goal + a hard velocity
    cap. ``bounded`` records that the command passed the bounding step (a lowered command is never
    unbounded); the eligibility verdict that GATES emission is a separate ``CommandEligibility``."""
    leg_id: int = Field(ge=0)
    kind: str = "goto"
    goal_row: float
    goal_col: float
    v_max_mps: float = Field(gt=0.0, le=1.0)
    bounded: bool = True

    @field_validator("kind")
    @classmethod
    def _known_kind(cls, v: str) -> str:
        if v not in {"goto", "safe", "rearm"}:
            raise ValueError(f"unknown command kind: {v}")
        return v


class CommandEligibility(Contract):
    """The pre-emission eligibility VERDICT (the RS spine's command-authority gate; mirrors the AG-08/
    SF-01/SF-02/NV-12 interlock). ``eligible`` is the AND of the individual checks; a False verdict
    carries the legible ``reason`` a refusal surfaces. INFORMS/gates only -- it is not itself a command."""
    eligible: bool
    reason: str = ""
    profile: str = "live"
    mode_ok: bool = True
    released: bool = True
    sensor_fresh: bool = True
    map_fresh: bool = True
    covariance_ok: bool = True
    watchdog_alive: bool = True
    link_ack: bool = True
    safe_inactive: bool = True


#: the runtime spine, in stage order. Each entry maps a stage-boundary name to its ONLY payload type.
#: Six are the strict Contract descriptors above; ``LocalizationState`` is the existing ``BeliefState``;
#: ``WorldTransaction`` is the existing ``stewie.twin.envelope.WorldTransaction`` (its own frozen dataclass).
def _world_transaction_type() -> type:
    from stewie.twin.envelope import WorldTransaction
    return WorldTransaction


RUNTIME_SPINE: dict[str, type] = {
    "DepthObservation": DepthObservation,
    "VisualHazardObservation": VisualHazardObservation,
    "ObservedMapUpdate": ObservedMapUpdate,
    "HazardMap": HazardMapDescriptor,
    "LocalizationState": LocalizationState,
    "CostmapSnapshot": CostmapSnapshot,
    "TrajectoryCommand": TrajectoryCommand,
    "CommandEligibility": CommandEligibility,
    "WorldTransaction": _world_transaction_type(),
}

#: the six schemas the spine was missing (all strict Contract subclasses defined here).
_NEW_CONTRACTS = (DepthObservation, VisualHazardObservation, ObservedMapUpdate, HazardMapDescriptor,
                  CostmapSnapshot, TrajectoryCommand, CommandEligibility)


def validate_boundary(stage: str, payload: dict) -> Contract:
    """Coerce a stage-boundary ``payload`` dict through its runtime-spine Contract, REJECTING a raw /
    wrong-shape dict (unknown or missing fields raise). This is how a stage validates what it received
    instead of trusting an ad-hoc dict. Only defined for the pydantic-Contract stages (not the
    WorldTransaction dataclass, which validates on its own construction)."""
    t = RUNTIME_SPINE.get(stage)
    if t is None or not (isinstance(t, type) and issubclass(t, Contract)):
        raise KeyError(f"no runtime-spine Contract for stage {stage!r}")
    return t(**payload)
