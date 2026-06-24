"""CP-04: the goal-grammar compiler -- lower a canonical MO-01 ``MissionIntent`` into the planner's request.

The INPUT is the canonical operator contract ``stewie.contracts.MissionIntent`` (MO-01): a HIERARCHY of
objectives (primary/secondary/stretch, each mandatory-flagged, with target geometry + measurable
acceptance + resource budgets + prerequisites) and constraints (HARD / FLIGHT_RULE / SOFT). This module
LOWERS that declarative goal into the real planner contract -- a ``lode.mission_planner.Mission`` (the
PlanRequest) -- by REUSING two boundaries that already exist and must not be re-implemented:

  * ``stewie.contracts.compile_order`` -- the MO-01 order discipline: it splits the intent into
    mandatory-objectives-first + hard/flight-rule-constraints-first, weighted (soft) scoring strictly
    after. We consume its output directly rather than re-deriving "mandatory first / hard first".
  * ``lode.mission_planner.mission_from_dict`` -- the planner's own order-compilation + validation
    boundary (order kinds, fleet capabilities, footprints, precedence, the hard-budget dict). Mandatory
    objectives + hard budgets are compiled the SAME way the planner consumes any mission, not via a
    parallel path that could diverge.

The compilation discipline (CP-04's reason for being), now expressed over MO-01:

  * MANDATORY objectives + HARD constraints/flight rules are compiled FIRST and unconditionally
    (``compile_order`` places them in the hard head). Mandatory objectives become required orders; hard
    NUMERIC budgets (from the objectives' structured resource ceilings + time windows) become the
    planner's ``objective_constraints`` budget, which the sequencer applies as a LARGE penalty
    (``_constraint_penalty``) that dominates any weighted score -- so a feasible plan always outranks an
    infeasible one. A hard constraint is therefore NEVER a tradeable term in the weighted objective.
  * SOFT constraints become the weighted ``objective`` string the optimizer minimizes; they tune the plan
    WITHIN the feasible set the hard constraints carve out.
  * The MO-01 ``Constraint`` model already REJECTS a weight on a hard/flight-rule constraint at the
    contract boundary; we re-assert the same invariant (a hard rule can never leak into the soft
    objective) so the compiler fails loudly rather than relying solely on the upstream validator.

MO-01 field gaps this compiler maps around (no invented fields):
  1. An MO-01 ``Objective`` carries target GEOMETRY (target_row/target_col/frame) + ``material_budget_kg``,
     but NO order-kind and NO work-footprint (footprint_m2/depth_m). The faithful lowering is an excavation
     (``cut``) order at the objective's target point, sized so its excavated MASS EQUALS the objective's
     ``material_budget_kg`` (a structured MO-01 field): mass = footprint_m2 x depth_m x body-density, so a
     fixed nominal depth (``_NOMINAL_CUT_DEPTH_M``) solves the footprint to match the budgeted mass exactly.
     For a dig-only ``cut`` (no paired fill) the planner's cost is driven SOLELY by mass (dig_e = mass x
     dig_J/kg, dig_t = mass / dig-rate; haul/lift = 0), so the footprint/depth SPLIT is free and only the
     mass (= the budget) is load-bearing. ``cut`` orders carry NO auto-precedence, so independent objectives
     stay FREELY orderable by the optimizer (unlike ``goto``, which the planner auto-chains into a fixed
     authorship path -- the wrong lowering for a hierarchy whose ordering must come only from prerequisites).
     action <- objective_id, x <- target_col, y <- target_row. An objective WITHOUT a ``material_budget_kg``
     has no geometry the planner can size and is REJECTED (a footprint is not invented).
  2. An MO-01 ``Constraint`` carries kind + a free-text ``statement`` + an optional soft ``weight``, but NO
     structured numeric metric/cap. Hard NUMERIC budgets therefore come from the OBJECTIVES' structured
     resource ceilings (summed ``energy_budget_j`` -> the planner's ``max_energy_J`` cap) and time windows
     (the latest ``time_window_s`` close -> ``max_time_s``), which DO exist in MO-01. A SOFT constraint's
     ``statement`` names its optimization metric via an explicit keyword map onto the planner's OBJECTIVES
     names; a soft constraint that names no known planner metric is REJECTED (not silently dropped). A HARD
     / FLIGHT_RULE constraint's free-text statement is NOT coerced into a numeric cap (no parsing convention
     is invented); it is honored as a flight-rule-head ordering element via ``compile_order``.

The two remaining goal-grammar terms CP-04 names, also lowered onto the real planner path:

  * TOLERANCES -- an objective's measurable acceptance carries a STRUCTURED numeric tolerance
    (``AcceptanceCriterion.tolerance_m``, the as-built RMSE bound; per objective, the tightest is
    ``Objective.acceptance_tolerance_m``). The compiler lowers the TIGHTEST tolerance across the mandatory
    objectives onto ``Mission.accept_flatness_tol_m``, which the conserved-authority acceptance gate
    (``validate_plan``) measures the worked footprints against (``as_built_pass`` = as-built RMSE <= tol).
    Like the budgets, the tolerance is a STRUCTURED field, never parsed out of the free-text ``measurable``.
    No objective declares a tolerance -> the gate keeps its documented default (byte-identical).
  * KEEP-OUTS -- a mission ``KeepOutRegion`` (circle / axis-aligned rectangle / polygon in the local order
    frame) lowers via ``KeepOutRegion.to_planner_keepout`` into the planner's OWN keep-out input
    (``Mission.keepouts``): hauls route AROUND it (the costmap raster marks it impassable) and a build sited
    inside it is flagged as a build-on-obstacle conflict (``totals['keepout_conflicts']``). We REUSE the
    planner's existing keep-out mechanism (``mission_planner`` routing + ``point_in_keepout``), not a
    parallel barrier model.
"""
from __future__ import annotations

import dataclasses

from stewie.contracts import (
    Constraint,
    ConstraintKind,
    MissionIntent,
    Objective,
    compile_order,
)

from lode import mission_planner as MP

#: MO-01 objective structured budget -> the planner's hard-budget key (the ``objective_constraints`` caps
#: the sequencer enforces via ``_constraint_penalty``, i.e. lode.mission_planner._CONSTRAINT_CAPS). These
#: are the only HARD numeric budgets MO-01 supplies in a structured form AND the planner models.
_PLANNER_ENERGY_CAP_KEY = "max_energy_J"   # <- summed Objective.energy_budget_j
_PLANNER_TIME_CAP_KEY = "max_time_s"       # <- latest Objective.time_window_s close

#: the nominal excavation depth [m] used to SPLIT an objective's ``material_budget_kg`` into a planner
#: footprint (footprint_m2 = mass / (depth x density)). For a dig-only ``cut`` the planner cost is mass-
#: driven only (the depth/footprint split is free; mass = the budget is the load-bearing quantity), so this
#: is a fixed, documented split -- not a physics claim about how deep the cut is. A shallow nominal keeps
#: the derived footprint a realistic area for typical kg-scale budgets.
_NOMINAL_CUT_DEPTH_M = 0.1

#: SOFT-constraint statement keyword -> the planner objective metric (lode.mission_planner.OBJECTIVES). A
#: soft constraint expresses WHICH metric to optimize via its free-text statement; we map an explicit set
#: of metric keywords (longest match wins) onto the planner's known objective names. Keywords are checked
#: against the statement with both '_' and ' ' normalized to a space, so "average power" and
#: "average_power" both match. Unrecognized -> reject (a soft constraint must say WHAT to optimize).
_SOFT_METRIC_KEYWORDS = {
    "average power": "average_power",
    "duration": "time",
    "distance": "distance",
    "energy": "energy",
    "charges": "charges",
    "power": "average_power",
    "time": "time",
    "mass": "mass",
}


@dataclasses.dataclass(frozen=True)
class CompiledPlanRequest:
    """The compiled planner request: the ``Mission`` (orders + precedence + hard ``objective_constraints``
    budget) plus the weighted ``objective`` string, plus the MO-01 ``CompiledOrder`` that proves the
    mandatory-first / hard-first discipline this request was built under. The real planner takes the
    Mission and the objective as SEPARATE arguments (``mission_planner.plan(mission, objective=...)``): the
    hard budget rides on the Mission, the soft weighting is the objective -- mirroring exactly how the
    planner keeps hard rules and soft trade-offs apart. ``plan(**request.plan_kwargs)`` drives the real
    planner."""
    mission: "MP.Mission"
    objective: str
    #: the MO-01 ordering proof: mandatory objective ids, hard (no-weight) constraint ids, and the
    #: hard-first-then-weighted constraint order that ``compile_order`` produced. Carried so a consumer can
    #: AUDIT that the compile respected the discipline, not just trust it.
    order: "object"   # stewie.contracts.CompiledOrder

    @property
    def plan_kwargs(self) -> dict:
        return {"mission": self.mission, "objective": self.objective}


def compile_intent(intent: MissionIntent) -> CompiledPlanRequest:
    """Lower a canonical MO-01 ``MissionIntent`` into the planner's request (a ``Mission`` + weighted
    objective string).

    Compilation order is the CP-04 invariant, sourced from MO-01's own ``compile_order``: mandatory
    objectives + hard constraints/flight rules are compiled FIRST (mandatory objectives -> required orders;
    hard structured budgets -> the ``objective_constraints`` budget); soft constraints are compiled into the
    weighted ``objective`` string LAST. The order set + budget are validated by the planner's own
    ``mission_from_dict`` boundary (kinds, capabilities, footprints, precedence, budgets).

    Raises ValueError on: no mandatory objective to plan; a mandatory objective with no
    ``material_budget_kg`` (no work geometry the planner can size); a hard/flight-rule constraint that also
    carries a weight (re-asserting the MO-01 invariant); a soft constraint whose statement names no known
    planner metric; a prerequisite that references an unknown/non-mandatory objective; a non-lunar frame.
    """
    if not isinstance(intent, MissionIntent):
        raise ValueError(
            f"compile_intent expects a canonical stewie.contracts.MissionIntent, got {type(intent)!r}")

    # --- MO-01 order discipline: REUSE compile_order to split mandatory-first / hard-first. We do NOT
    #     re-derive "mandatory first / hard first" -- the contract helper is the single source of it. ---
    order = compile_order(intent)

    # --- mandatory objectives first: they are the required work; without one there is nothing to plan ---
    mandatory_ids = set(order.mandatory_objective_ids)
    if not mandatory_ids:
        raise ValueError(
            "MissionIntent has no mandatory objective to plan (nothing to compile into orders)")
    by_id = {o.objective_id: o for o in intent.objectives}
    # compile the mandatory objectives in compile_order's order (mandatory-first is structural, not casual).
    mandatory = [by_id[oid] for oid in order.mandatory_objective_ids]

    # the planner body the intent's coordinate frame lowers to (drives the regolith density for sizing).
    body = _intent_body(intent)

    # --- objectives -> the planner's order queue. MO-01 objectives carry target geometry +
    #     material_budget_kg + an ``order_kind`` (default ``cut``; MO-01 2026-06-23 extension), so each lowers
    #     to an order of that kind (cut | fill | sinter) at its target point (x <- target_col, y <- target_row),
    #     sized so its mass EQUALS material_budget_kg (footprint = mass / (nominal-depth x density)). The order
    #     carries no auto-precedence, so independent objectives stay freely orderable; ordering comes only from
    #     prerequisites below. ---
    density = MP.body_density(body)
    order_payload = []
    for o in mandatory:
        if o.material_budget_kg is None:
            raise ValueError(
                f"objective {o.objective_id!r} has no material_budget_kg: MO-01 supplies no other work "
                f"geometry the planner can size an order from, so a footprint cannot be derived "
                f"(set material_budget_kg, or move the objective out of the mandatory set).")
        mass = float(o.material_budget_kg)
        footprint_m2 = mass / (_NOMINAL_CUT_DEPTH_M * density)
        order_payload.append({
            "action": o.objective_id,
            "kind": o.order_kind,                    # MO-01 extension: honor the objective's order_kind (cut|fill|sinter)
            "x": float(o.target_col),
            "y": float(o.target_row),
            "footprint_m2": footprint_m2,
            "depth_m": _NOMINAL_CUT_DEPTH_M,
            "note": o.statement,
        })

    # --- prerequisites -> precedence (before_action=prereq, after_action=objective) the sequencer honours.
    #     Only mandatory objectives are in the order set, so a prerequisite must reference a mandatory one. ---
    precedence: list[list[str]] = []
    for o in mandatory:
        for prereq in o.prerequisites:
            if prereq not in by_id:
                raise ValueError(
                    f"objective {o.objective_id!r} prerequisite {prereq!r} references an unknown objective")
            if prereq not in mandatory_ids:
                raise ValueError(
                    f"objective {o.objective_id!r} prerequisite {prereq!r} is not a mandatory objective; "
                    f"only mandatory objectives are compiled into orders, so its prerequisite must be too.")
            precedence.append([prereq, o.objective_id])

    # --- hard constraints + budgets -> the planner's hard-budget objective_constraints (the penalty path,
    #     which dominates any weighted score). A weighted hard/flight-rule constraint is a contradiction ->
    #     reject (re-asserting the MO-01 invariant the contract already enforces). ---
    for c in intent.constraints:
        if c.kind in (ConstraintKind.HARD, ConstraintKind.FLIGHT_RULE) and c.weight is not None:
            raise ValueError(
                f"hard constraint {c.constraint_id!r} ({c.kind.value}) carries a weight ({c.weight!r}): a "
                f"hard constraint / flight rule can never become a soft, tradeable weight.")

    budgets = _compile_hard_budgets(mandatory)

    # --- TOLERANCES -> the as-built acceptance gate. Each mandatory objective's measurable acceptance may
    #     carry a STRUCTURED numeric tolerance (MO-01 AcceptanceCriterion.tolerance_m, the as-built RMSE
    #     bound -- not parsed out of prose). A single plan must meet the strictest, so the mission's
    #     acceptance tolerance is the TIGHTEST across the mandatory objectives. None when none declares one
    #     (validate_plan keeps its default). ---
    accept_tol = _compile_acceptance_tolerance(mandatory)

    # --- KEEP-OUTS -> the planner's OWN keep-out input. Each MO-01 keep-out region lowers to the planner's
    #     keepout dict shape (circle/rectangle/polygon) the router already routes around and the build-on-
    #     obstacle conflict check already consumes -- we reuse Mission.keepouts, not a parallel barrier. ---
    keepouts = [r.to_planner_keepout() for r in intent.keep_outs]

    payload: dict = {
        "name": intent.mission_id,
        "body": body,
        "orders": order_payload,
    }
    if precedence:
        payload["precedence"] = precedence
    if budgets:
        payload["objective_constraints"] = budgets
    if accept_tol is not None:
        payload["accept_flatness_tol_m"] = accept_tol
    if keepouts:
        payload["keepouts"] = keepouts

    # REUSE the planner's own order-compilation + validation boundary (kinds/capabilities/footprints/
    # precedence/budgets/keep-outs) so mandatory objectives + hard constraints are compiled the SAME way
    # the planner consumes any mission -- not via a parallel path that could diverge.
    mission = MP.mission_from_dict(payload)

    # --- soft constraints LAST -> the weighted objective string (tunes the plan within the feasible set).
    #     parse_objective validates names + weight domain and renormalizes to a convex combination. ---
    objective = _compile_soft_objective(intent.constraints)
    return CompiledPlanRequest(mission=mission, objective=objective, order=order)


def _intent_body(intent: MissionIntent) -> str:
    """The planner body an MO-01 intent targets. MO-01 objectives carry a coordinate ``frame`` (MOON_ME by
    default); the planner is keyed by a body name (bodies.json). The lunar mission frames lower to 'moon';
    a non-lunar frame is rejected rather than silently planned on the moon."""
    frames = {o.frame for o in intent.objectives}
    if not frames or frames <= {"MOON_ME", "SITE_LOCAL", "moon", "MOON"}:
        return "moon"
    raise ValueError(
        f"MissionIntent objective frame(s) {sorted(frames)} are not a known lunar planner frame; the "
        f"planner is keyed by body and these do not lower to 'moon'.")


def _compile_hard_budgets(objectives: list[Objective]) -> dict:
    """Compile the MO-01 objectives' STRUCTURED hard resource ceilings into the planner's hard-budget keys
    (``objective_constraints``). MO-01 supplies these numerically on the OBJECTIVE (a ``Constraint`` is
    free-text and carries no cap):

      * ``energy_budget_j`` -> ``max_energy_J`` -- the AGGREGATE hard energy ceiling (summed across the
        objectives that declare one; an objective without one contributes nothing).
      * ``time_window_s`` close -> ``max_time_s`` -- the latest objective window close is the makespan
        ceiling (the plan may not finish after the last objective's window shuts).

    MO-01's ``material_budget_kg`` / ``data_budget_bytes`` have NO planner budget key -- the planner models
    time/energy/charges/distance budgets only -- so they are not lowered (and not silently coerced into a
    different cap). Returns {} when no objective declares a structured budget (byte-identical to an
    un-budgeted plan)."""
    budgets: dict = {}
    energy = sum(o.energy_budget_j for o in objectives if o.energy_budget_j is not None)
    if any(o.energy_budget_j is not None for o in objectives):
        budgets[_PLANNER_ENERGY_CAP_KEY] = float(energy)
    closes = [o.time_window_s[1] for o in objectives if o.time_window_s is not None]
    if closes:
        budgets[_PLANNER_TIME_CAP_KEY] = float(max(closes))
    return budgets


def _compile_acceptance_tolerance(objectives: list[Objective]) -> float | None:
    """CP-04: compile the mission's as-built acceptance tolerance [m] from the OBJECTIVES' structured
    acceptance tolerances (MO-01 ``AcceptanceCriterion.tolerance_m``, exposed per objective as
    ``Objective.acceptance_tolerance_m`` = the tightest of its criteria). The plan's single as-built
    flatness gate (``validate_plan``) must satisfy the strictest objective, so the mission tolerance is the
    TIGHTEST (minimum) across the mandatory objectives that declare one. None when none declares a
    tolerance (the gate keeps its documented default -- byte-identical to a pre-tolerance plan). A tolerance
    is NOT parsed from the free-text ``measurable``; only the structured numeric field is lowered."""
    tols = [o.acceptance_tolerance_m for o in objectives if o.acceptance_tolerance_m is not None]
    return min(tols) if tols else None


def _compile_soft_objective(constraints: list[Constraint]) -> str:
    """Compile the SOFT (optimizable) MO-01 constraints into a weighted-objective string the planner's
    ``parse_objective`` accepts. Each soft constraint names its optimization metric via its free-text
    ``statement`` (mapped onto the planner's OBJECTIVES names) and carries the optimization ``weight``.

    No soft constraint -> the planner default ("time"). One -> a bare name (or name:weight). Many ->
    "name:w,name:w" (validated + renormalized to a convex combination downstream). A soft constraint whose
    statement names NO known planner metric is REJECTED (not silently dropped); a zero/negative/duplicate
    weight is caught by ``parse_objective``."""
    soft = [c for c in constraints if c.is_optimizable]
    if not soft:
        return "time"
    terms: list[tuple[str, float]] = []
    for c in soft:
        metric = _statement_metric(c)
        # c.is_optimizable guarantees a non-None weight; MO-01 bounds it to [0,1].
        terms.append((metric, float(c.weight)))   # type: ignore[arg-type]
    # collapse duplicate metrics by summing their weights (parse_objective rejects a duplicate component).
    merged: dict[str, float] = {}
    for metric, w in terms:
        merged[metric] = merged.get(metric, 0.0) + w
    if len(merged) == 1:
        (metric, w), = merged.items()
        spec = metric if w == 1.0 else f"{metric}:{w}"
    else:
        spec = ",".join(f"{m}:{w}" for m, w in merged.items())
    MP.parse_objective(spec)   # fail fast at compile time on a bad weight/name (don't defer to plan time)
    return spec


def _statement_metric(c: Constraint) -> str:
    """Map a SOFT MO-01 constraint's free-text ``statement`` onto a planner objective metric name. Matches
    the longest metric keyword found in the (lower-cased) statement (so 'average power' beats 'power'). A
    statement that names no known planner metric is rejected -- a soft constraint must say WHAT to optimize."""
    text = c.statement.lower().replace("_", " ")
    matches = [(kw, metric) for kw, metric in _SOFT_METRIC_KEYWORDS.items() if kw in text]
    if not matches:
        raise ValueError(
            f"soft constraint {c.constraint_id!r} statement {c.statement!r} names no known planner "
            f"optimization metric; expected one of {sorted(set(_SOFT_METRIC_KEYWORDS.values()))}.")
    # longest keyword wins (e.g. 'average power' over 'power'), so a more specific metric is preferred.
    best_kw = max((kw for kw, _ in matches), key=len)
    return dict(matches)[best_kw]
