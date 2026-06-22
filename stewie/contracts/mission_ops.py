"""MO-01 / MO-03 / MO-04 (§27 mission-ops): the typed mission-intent, provenance, and labeling
contracts -- the data spine the operational UI renders.

Grounded in ``docs/architecture_review_2026-06-20_mission_ops.md`` ("How mission objectives should be
planned", P1-1 objective+acceptance hierarchy, P1-8 provenance vocabulary) and
``docs/ui_overhaul_plan_2026-06-20.md`` §5 (MO-01..MO-04). MO-02, the mission-executive STATE MACHINE,
is deliberately NOT here -- it is gated (the Execute screen waits on it, §7), out of this brick.

Same spine pattern as ``stewie.contracts`` (FS-02): every schema is STRICT (``extra='forbid'`` ->
unknown fields rejected at the boundary), FROZEN (an immutable snapshot), and carries ``schema_version``.

Three load-bearing invariants, enforced by validation (not convention):

* **MO-01** -- a HARD constraint / flight rule carries NO optimization weight (reject a weight on a hard
  constraint), and ``compile_order`` places mandatory objectives + hard constraints BEFORE any weighted
  scoring, so a flight rule can never silently become a soft preference.
* **MO-03** -- ``combine_provenance`` REJECTS combining two provenanced values with incompatible
  frames/revisions/units (raises ``ValueError``), never silently merging them.
* **MO-04** -- a ``LabeledValue`` FORCES its value to carry a SIM/FORECAST/LIVE label.
"""
from __future__ import annotations

from enum import Enum

from pydantic import Field, model_validator

from . import Contract


# ================================================================================================
# MO-04: the SIM / FORECAST / LIVE labeling contract
# ================================================================================================

class DataLabel(str, Enum):
    """MO-04 / ui_overhaul §5: the strict SIM/FORECAST/LIVE provenance label every operational value
    carries. The cockpit's color contract binds to these (forecast = cyan, observed estimate = white,
    truth = magenta-directors-only); until the mission executive (MO-02) exists, execution UI stays
    visibly SIM or FORECAST -- never LIVE without it."""
    SIM = "sim"
    FORECAST = "forecast"
    LIVE = "live"


class LabeledValue(Contract):
    """MO-04: a value that CANNOT be carried unlabeled -- it forces a SIM/FORECAST/LIVE label so the UI
    can never render a simulated/forecast value as if it were live. ``value`` is the typed payload (a
    number the cockpit displays); ``label`` is required (no default)."""
    value: float
    label: DataLabel


# ================================================================================================
# MO-03: the provenance vocabulary (P1-8)
# ================================================================================================

class Provenance(Contract):
    """MO-03 / P1-8: the provenance every operational view-model field carries so a simulated pose, a
    forecast battery, an observed DEM, and a truth surface can never share a color or label. ``basis``
    reuses the MO-04 SIM/FORECAST/LIVE label; ``frame``+``units``+``revision`` are what
    ``combine_provenance`` checks before it allows two values to be combined."""
    source: str                                  # who produced it (estimator | map | loc | sim | ...)
    basis: DataLabel                             # sim | forecast | live -- the MO-04 label
    timestamp_s: float                           # mission time the value was produced
    age_s: float = Field(ge=0.0)                 # seconds since produced (data freshness the UI shows)
    frame: str                                   # coordinate authority (MOON_ME | SITE_LOCAL | ...)
    units: str                                   # the physical units (m | deg | J | ...)
    confidence: float = Field(ge=0.0, le=1.0)    # belief quality in [0,1]
    revision: int = Field(ge=0)                  # the map/plan revision this value belongs to


class ProvenancedValue(Contract):
    """MO-03: an operational value bound to its ``Provenance`` -- the typed field shape the operational
    view model uses so every rendered number carries source/basis/age/frame/units/confidence/revision."""
    value: float
    provenance: Provenance


def combine_provenance(a: Provenance, b: Provenance) -> Provenance:
    """MO-03 / P1-8: combine two provenances ONLY when they are frame-, revision-, and unit-compatible;
    otherwise RAISE rather than silently combine. The merge is conservative -- it reports the OLDEST age
    (max), the LOWEST confidence (min), and the merged source -- so a combined value never claims to be
    fresher or more certain than its worst input. ``basis`` must also agree (you may not silently merge a
    forecast with a live value)."""
    if a.frame != b.frame:
        raise ValueError(
            f"MO-03: refusing to combine provenances with incompatible frames {a.frame!r} != {b.frame!r}")
    if a.revision != b.revision:
        raise ValueError(
            f"MO-03: refusing to combine provenances with incompatible revisions {a.revision} != {b.revision}")
    if a.units != b.units:
        raise ValueError(
            f"MO-03: refusing to combine provenances with incompatible units {a.units!r} != {b.units!r}")
    if a.basis != b.basis:
        raise ValueError(
            f"MO-03: refusing to combine provenances with incompatible basis {a.basis.value!r} "
            f"!= {b.basis.value!r}")
    return Provenance(
        source=f"{a.source}+{b.source}",
        basis=a.basis,
        timestamp_s=max(a.timestamp_s, b.timestamp_s),   # most recent production time
        age_s=max(a.age_s, b.age_s),                     # conservative: the staler of the two
        frame=a.frame,
        units=a.units,
        confidence=min(a.confidence, b.confidence),      # conservative: the less certain of the two
        revision=a.revision,
    )


# ================================================================================================
# MO-01: the mission-intent hierarchy
# ================================================================================================

class PriorityTier(str, Enum):
    """MO-01 / review "How mission objectives should be planned": the objective priority tier. Primary =
    must complete; secondary = complete if margins permit; stretch = opportunistic. Drives what may be
    sacrificed under resource pressure."""
    PRIMARY = "primary"
    SECONDARY = "secondary"
    STRETCH = "stretch"


class ConstraintKind(str, Enum):
    """MO-01: a constraint is HARD (a physical/safety limit), a FLIGHT_RULE (an operational rule that is
    also non-negotiable), or SOFT (an optimization preference). Hard + flight-rule are compiled FIRST and
    carry no weight; only SOFT participates in weighted scoring (the flight-rule-can-never-soften
    invariant)."""
    HARD = "hard"
    FLIGHT_RULE = "flight_rule"
    SOFT = "soft"


class ContingencyPolicy(str, Enum):
    """MO-01: what autonomy does when an objective cannot proceed -- retry, observe, replan, skip, return,
    or SAFE (review: "contingency policy: retry, observe, replan, skip, return, SAFE")."""
    RETRY = "retry"
    OBSERVE = "observe"
    REPLAN = "replan"
    SKIP = "skip"
    RETURN = "return"
    SAFE = "safe"


class Contingency(Contract):
    """MO-01: the abort/contingency branch for an objective -- the policy autonomy follows plus a
    human-readable detail. The hold/abort THRESHOLDS that trip it live on the objective."""
    policy: ContingencyPolicy
    detail: str = ""


class AcceptanceCriterion(Contract):
    """MO-01 / P1-1: the measurable evidence required to declare an objective complete -- "an optimization
    objective such as time is not the mission objective". ``measurable`` is the observable completion test;
    ``sensor`` is what supplies the evidence; ``tolerance_m`` is the STRUCTURED numeric acceptance
    tolerance the planner's acceptance gate consumes (the as-built flatness/profile RMSE bound in metres,
    e.g. the +/-0.02 m named in ``measurable``). It is a structured field -- NOT parsed out of the
    free-text ``measurable`` -- so the goal-grammar compiler (CP-04) lowers a real number onto the plan,
    never an invented parse of prose. None -> no per-objective override (the gate keeps its documented
    default)."""
    criterion_id: str
    statement: str
    measurable: str               # the observable completion test (e.g. "as-built RMSE <= 0.02 m")
    sensor: str = ""              # the acceptance sensor that supplies the evidence
    tolerance_m: float | None = Field(default=None, gt=0.0)   # as-built RMSE acceptance bound [m]


class Constraint(Contract):
    """MO-01: a mission constraint. The load-bearing invariant: a HARD constraint or FLIGHT_RULE may NOT
    carry an optimization ``weight`` -- only a SOFT constraint may. This is what stops weighted scoring
    from converting a flight rule into a soft preference. ``weight`` is None for hard/flight-rule and a
    value in [0,1] for soft."""
    constraint_id: str
    kind: ConstraintKind
    statement: str
    weight: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _hard_carries_no_weight(self) -> Constraint:
        if self.kind in (ConstraintKind.HARD, ConstraintKind.FLIGHT_RULE) and self.weight is not None:
            raise ValueError(
                f"MO-01: a {self.kind.value} constraint may not carry an optimization weight "
                "(a flight rule can never become a soft preference)")
        return self

    @property
    def is_optimizable(self) -> bool:
        """True only for a SOFT constraint with a weight -- the structural test the compile/order helper
        uses to keep hard/flight constraints out of weighted scoring."""
        return self.kind == ConstraintKind.SOFT and self.weight is not None


class Objective(Contract):
    """MO-01 / review objective field table: one mission objective with the full operator field set --
    id+revision, statement/rationale, priority+mandatory flag, target geometry+frame, measurable
    acceptance, confidence requirement, time/illumination/comms windows, resource budgets, prerequisites,
    hold/abort thresholds, contingency policy, approver+evidence. ``acceptance`` must be non-empty (an
    objective with no measurable completion test is not an objective)."""
    objective_id: str
    revision: int = Field(ge=0)
    statement: str
    rationale: str
    priority: PriorityTier
    mandatory: bool
    # target geometry + coordinate authority
    target_row: float
    target_col: float
    frame: str = "MOON_ME"
    # measurable acceptance (at least one criterion)
    acceptance: list[AcceptanceCriterion] = Field(min_length=1)
    # minimum belief quality (not only nominal value)
    confidence_required: float = Field(ge=0.0, le=1.0)
    # when it may occur -- time / illumination / comms windows ([t0,t1] in mission seconds; None = any)
    time_window_s: tuple[float, float] | None = None
    illumination_window_s: tuple[float, float] | None = None
    comms_window_s: tuple[float, float] | None = None
    # hard resource ceilings
    energy_budget_j: float | None = Field(default=None, ge=0.0)
    material_budget_kg: float | None = Field(default=None, ge=0.0)
    data_budget_bytes: int | None = Field(default=None, ge=0)
    # task-graph ordering
    prerequisites: list[str] = Field(default_factory=list)
    # when autonomy must stop, and what it does then
    hold_threshold: str = ""
    abort_threshold: str = ""
    contingency: Contingency
    # who may release it and on what basis
    approver: str
    evidence: str = ""

    @property
    def acceptance_tolerance_m(self) -> float | None:
        """CP-04: the TIGHTEST structured acceptance tolerance across this objective's criteria (the
        as-built RMSE bound the planner must meet), or None if none declares one. A single plan must
        satisfy the strictest criterion, so the minimum is the binding tolerance."""
        tols = [c.tolerance_m for c in self.acceptance if c.tolerance_m is not None]
        return min(tols) if tols else None


class KeepOutRegion(Contract):
    """MO-01: a mission keep-out region the planner must avoid -- a no-go zone (boulder field, crater,
    ejecta blanket, PSR boundary) in the mission's LOCAL order frame [metres]. Exactly ONE shape is
    supplied: a CIRCLE (``x``, ``y``, ``radius_m``), an axis-aligned RECTANGLE (``x0``, ``y0``, ``x1``,
    ``y1``), or a POLYGON (``points``, >= 3 vertices). The goal-grammar compiler (CP-04) lowers it into
    the planner's OWN keep-out input (``Mission.keepouts``): hauls route AROUND it and a build sited
    inside it is flagged as a build-on-obstacle conflict -- the same mechanism the router already uses,
    not a parallel barrier model."""
    region_id: str
    reason: str = ""
    # circle
    x: float | None = None
    y: float | None = None
    radius_m: float | None = Field(default=None, gt=0.0)
    # axis-aligned rectangle
    x0: float | None = None
    y0: float | None = None
    x1: float | None = None
    y1: float | None = None
    # polygon (>= 3 vertices)
    points: list[tuple[float, float]] | None = None

    @model_validator(mode="after")
    def _exactly_one_shape(self) -> KeepOutRegion:
        is_circle = self.x is not None and self.y is not None and self.radius_m is not None
        is_rect = all(v is not None for v in (self.x0, self.y0, self.x1, self.y1))
        is_poly = self.points is not None
        n = sum((is_circle, is_rect, is_poly))
        if n != 1:
            raise ValueError(
                "MO-01: a KeepOutRegion must supply exactly one shape -- a circle (x,y,radius_m), a "
                "rectangle (x0,y0,x1,y1), or a polygon (points, >= 3 vertices)")
        if self.points is not None and len(self.points) < 3:
            raise ValueError("MO-01: a KeepOutRegion polygon needs >= 3 vertices")
        if is_rect and (self.x0 == self.x1 or self.y0 == self.y1):
            raise ValueError("MO-01: a KeepOutRegion rectangle must have non-zero width and height")
        return self

    def to_planner_keepout(self) -> dict:
        """CP-04: lower this region into the planner's keep-out dict shape (the SAME schema
        ``mission_from_dict`` validates and ``point_in_keepout`` / the router raster consume). The
        validator guarantees exactly one shape's fields are all non-None."""
        if self.points is not None:
            return {"points": [[float(px), float(py)] for px, py in self.points]}
        if None not in (self.x0, self.y0, self.x1, self.y1):
            return {"x0": float(self.x0), "y0": float(self.y0),     # type: ignore[arg-type]
                    "x1": float(self.x1), "y1": float(self.y1)}     # type: ignore[arg-type]
        return {"x": float(self.x), "y": float(self.y),             # type: ignore[arg-type]
                "r": float(self.radius_m)}                          # type: ignore[arg-type]


class MissionIntent(Contract):
    """MO-01 / P1-1: the operator-facing mission object the planner compiles against -- a HIERARCHY, not a
    flat order queue. Carries primary/secondary/stretch objectives, constraints + flight rules, and a
    reference to the compiled task graph (the Plan IR). Plan actions + telemetry events trace back to
    objective IDs. ``revision`` is the immutable revision number (replanning makes a NEW revision)."""
    mission_id: str
    revision: int = Field(ge=0)
    statement: str
    objectives: list[Objective] = Field(default_factory=list)
    constraints: list[Constraint] = Field(default_factory=list)
    # MO-01 / CP-04: mission-wide keep-out regions (no-go zones) the planner must route around; lowered
    # into Mission.keepouts by the goal-grammar compiler.
    keep_outs: list[KeepOutRegion] = Field(default_factory=list)
    # the compiled task graph reference (e.g. a Plan IR id); the task graph itself lives in the planner
    task_graph_ref: str = ""

    @property
    def primary_objectives(self) -> list[Objective]:
        return [o for o in self.objectives if o.priority == PriorityTier.PRIMARY]

    @property
    def secondary_objectives(self) -> list[Objective]:
        return [o for o in self.objectives if o.priority == PriorityTier.SECONDARY]

    @property
    def stretch_objectives(self) -> list[Objective]:
        return [o for o in self.objectives if o.priority == PriorityTier.STRETCH]

    @property
    def mandatory_objectives(self) -> list[Objective]:
        return [o for o in self.objectives if o.mandatory]


class CompiledOrder(Contract):
    """MO-01: the result of ``compile_order`` -- the structural guarantee that mandatory objectives + hard
    constraints are placed BEFORE any weighted scoring. ``compiled_constraint_order`` is hard/flight-rule
    constraints first, then weighted (soft) constraints, so a flight rule can never be evaluated as a soft
    preference."""
    mandatory_objective_ids: list[str] = Field(default_factory=list)
    optional_objective_ids: list[str] = Field(default_factory=list)
    hard_constraint_ids: list[str] = Field(default_factory=list)      # hard + flight-rule, no weight
    weighted_constraint_ids: list[str] = Field(default_factory=list)  # soft, optimizable
    compiled_constraint_order: list[str] = Field(default_factory=list)  # hard-first then weighted


def compile_order(intent: MissionIntent) -> CompiledOrder:
    """MO-01: compile a MissionIntent into the order the planner must respect -- mandatory objectives and
    hard/flight-rule constraints FIRST, weighted (soft) scoring strictly AFTER. The planner may optimize
    time/energy/risk/coverage only over the weighted tail; the hard head is non-negotiable, so weighted
    scoring can never convert a flight rule into a soft preference (review: "Weighted scoring must not
    convert a flight rule into a soft preference")."""
    mandatory = [o.objective_id for o in intent.objectives if o.mandatory]
    optional = [o.objective_id for o in intent.objectives if not o.mandatory]
    hard = [c.constraint_id for c in intent.constraints if not c.is_optimizable]
    weighted = [c.constraint_id for c in intent.constraints if c.is_optimizable]
    return CompiledOrder(
        mandatory_objective_ids=mandatory,
        optional_objective_ids=optional,
        hard_constraint_ids=hard,
        weighted_constraint_ids=weighted,
        compiled_constraint_order=hard + weighted,
    )
