"""CP-04: goal-grammar compiler tests, on the CANONICAL MO-01 contracts.

The compiler INPUT is ``stewie.contracts.MissionIntent`` (MO-01): a HIERARCHY of objectives (each with
target geometry + measurable acceptance + resource budgets + prerequisites, tagged primary/secondary/
stretch and mandatory/optional) and constraints (HARD / FLIGHT_RULE / SOFT). The compiler LOWERS it into
the REAL planner contract -- a ``lode.mission_planner.Mission`` carrying compiled excavation orders,
precedence, and the hard-constraint budget dict ``objective_constraints`` -- plus a weighted soft
objective string, returned together as a ``CompiledPlanRequest`` (the planner takes them SEPARATELY:
``plan(mission, objective=...)``; hard rules ride on the Mission, soft trade-offs are the objective).

The load-bearing invariants under test (CP-04, expressed over MO-01):
  1. Mandatory objectives compile into orders BEFORE any soft/weighted optimization (mandatory-first,
     sourced from the MO-01 ``compile_order`` helper the compiler reuses), and a hard structured budget
     lands in ``objective_constraints`` (the planner's HARD penalty path) -- never as a soft weight.
  2. A hard / flight-rule constraint that also carries a soft weight is REJECTED (a flight rule must not
     be tradeable). (MO-01's Constraint model also rejects this at the contract boundary; the compiler
     re-asserts it.)
  3. The compiled request drives the REAL planner path (``mission_planner.plan``) on real moon physics,
     the mandatory objectives are honoured (present + sequenced respecting prerequisites), and the
     optimizer is free to ORDER independent objectives (the lowering does not impose a spurious total
     order).

No synthetic data and no stubs: inputs are real canonical MO-01 contract instances and the end-to-end
test runs the real single-vehicle planner on the real moon regolith model (bodies.json).
"""
import math

import pytest

import lode.mission_planner as MP
from lode import mission_intent_compiler as MIC
from stewie.contracts import (
    AcceptanceCriterion,
    Constraint,
    ConstraintKind,
    Contingency,
    ContingencyPolicy,
    KeepOutRegion,
    MissionIntent,
    Objective,
    PriorityTier,
)


# ---------------------------------------------------------------------------------------------------
# canonical MO-01 builders: every MO-01 required field is supplied with a real, valid value (the
# compiler consumes the canonical contract, so the tests construct it -- not a local duplicate).
# ---------------------------------------------------------------------------------------------------
def _objective(objective_id, *, target_row, target_col, mandatory=True,
               priority=PriorityTier.PRIMARY, prerequisites=(), material_budget_kg=300.0,
               energy_budget_j=None, time_window_s=None, tolerance_m=None, order_kind="cut"):
    """A fully-specified MO-01 Objective (acceptance non-empty, contingency present, approver set).

    ``tolerance_m`` -> the acceptance criterion's structured numeric acceptance tolerance (the as-built
    flatness/profile tolerance the planner's acceptance gate consumes); None -> the contract default."""
    return Objective(
        objective_id=objective_id, revision=0,
        statement=f"excavate {objective_id}", rationale="construction prep",
        priority=priority, mandatory=mandatory,
        target_row=target_row, target_col=target_col, frame="MOON_ME", order_kind=order_kind,
        acceptance=[AcceptanceCriterion(criterion_id=f"{objective_id}-ac", statement="excavated",
                                        measurable="as-built RMSE <= 0.02 m", sensor="stereo",
                                        tolerance_m=tolerance_m)],
        confidence_required=0.6,
        energy_budget_j=energy_budget_j, material_budget_kg=material_budget_kg,
        time_window_s=time_window_s,
        prerequisites=list(prerequisites),
        contingency=Contingency(policy=ContingencyPolicy.SAFE, detail="loss of localization"),
        approver="flight-director")


def _intent(mission_id, objectives, constraints=(), keep_outs=()):
    return MissionIntent(mission_id=mission_id, revision=0, statement="test mission",
                         objectives=list(objectives), constraints=list(constraints),
                         keep_outs=list(keep_outs))


def test_mandatory_objective_compiles_to_order_and_soft_constraint_to_weight():  # [REQ:CP-04]
    intent = _intent(
        "dig-then-prefer-fast",
        [_objective("pit", target_row=10.0, target_col=10.0, material_budget_kg=300.0)],
        # a SOFT constraint: minimize energy, weighted -- it tunes the optimizer, it is not a hard budget.
        [Constraint(constraint_id="prefer-energy", kind=ConstraintKind.SOFT,
                    statement="minimize energy", weight=1.0)],
    )
    req = MIC.compile_intent(intent)

    # the mandatory objective compiled into a real excavation order (mandatory-first: it is in the order set).
    assert isinstance(req.mission, MP.Mission)
    actions = {o.action for o in req.mission.orders}
    assert "pit" in actions
    pit = next(o for o in req.mission.orders if o.action == "pit")
    assert pit.kind == "cut" and pit.x == 10.0 and pit.y == 10.0
    # the order's MASS equals the objective's material_budget_kg (the load-bearing sizing quantity).
    recovered = pit.footprint_m2 * pit.depth_m * MP.body_density("moon")
    assert math.isclose(recovered, 300.0, rel_tol=1e-9)

    # the soft constraint became a WEIGHTED objective the planner optimizes (a convex weight dict).
    weights = MP.parse_objective(req.objective)
    assert "energy" in weights

    # no soft constraint leaked into the HARD-constraint budget.
    assert not req.mission.objective_constraints

    # the MO-01 ordering proof confirms mandatory-first / hard-first discipline.
    assert req.order.mandatory_objective_ids == ["pit"]
    assert req.order.weighted_constraint_ids == ["prefer-energy"]


def test_objective_order_kind_lowers_to_that_kind_round_trip():  # [REQ:CP-04]
    # MO-01 extension (2026-06-23): an objective's order_kind lowers to an order of THAT kind, not silently a
    # cut -- so the full plan vocabulary round-trips through compile_intent (a 'fill' objective compiles to a
    # fill order, mass preserved), instead of every objective collapsing to cut.
    for kind in ("cut", "fill"):
        intent = _intent("m", [_objective("o1", target_row=5.0, target_col=10.0,
                                           material_budget_kg=300.0, order_kind=kind)])
        req = MIC.compile_intent(intent)
        o1 = next(o for o in req.mission.orders if o.action == "o1")
        assert o1.kind == kind, f"order_kind={kind} lowered to {o1.kind!r}, expected {kind}"
        recovered = o1.footprint_m2 * o1.depth_m * MP.body_density("moon")
        assert math.isclose(recovered, 300.0, rel_tol=1e-9)   # mass preserved across the kind


def test_default_order_kind_is_cut_byte_identical():  # [REQ:CP-04]
    # additive extension: an objective with no order_kind defaults to cut (the prior behaviour, unchanged).
    intent = _intent("m", [_objective("o1", target_row=5.0, target_col=10.0)])
    req = MIC.compile_intent(intent)
    assert next(o for o in req.mission.orders if o.action == "o1").kind == "cut"


def test_invalid_order_kind_is_rejected():  # [REQ:CP-04]
    import pytest
    with pytest.raises(ValueError, match="order_kind"):
        _objective("o1", target_row=0.0, target_col=0.0, order_kind="bogus")


def test_intent_from_orders_round_trips_the_full_vocabulary():  # [REQ:CP-04]
    # Release builder (intent_from_orders): cockpit BUILD orders -> MissionIntent -> compile_intent returns
    # orders of the SAME kind / x / y / mass (nothing dropped or faked); non-build orders (goto path
    # waypoints) are honestly surfaced in `skipped`, never silently dropped or mapped to a cut.
    orders = [
        {"action": "Pad cut", "kind": "cut", "x": 10.0, "y": 5.0, "footprint_m2": 9.0, "depth_m": 0.2},
        {"action": "Berm fill", "kind": "fill", "x": -10.0, "y": 5.0, "footprint_m2": 12.0, "depth_m": 0.3},
        {"action": "wp1", "kind": "goto", "x": 0.0, "y": 0.0},
    ]
    intent, skipped = MIC.intent_from_orders(orders, mission_id="m1", approver="dir", body="moon")
    assert skipped == [{"action": "wp1", "kind": "goto"}]
    assert len(intent.objectives) == 2
    density = MP.body_density("moon")
    req = MIC.compile_intent(intent)                          # round-trip through the REAL compiler
    by_action = {o.action: o for o in req.mission.orders}
    for src in orders[:2]:
        ro = by_action[src["action"]]
        assert ro.kind == src["kind"] and ro.x == src["x"] and ro.y == src["y"]
        rt_mass = ro.footprint_m2 * ro.depth_m * density
        orig_mass = src["footprint_m2"] * src["depth_m"] * density
        assert math.isclose(rt_mass, orig_mass, rel_tol=1e-9)


def test_hard_budget_lands_in_objective_constraints_not_in_soft_weights():  # [REQ:CP-04]
    intent = _intent(
        "hard-time-cap",
        [_objective("pit", target_row=8.0, target_col=8.0, material_budget_kg=200.0,
                    # a HARD numeric budget from MO-01's structured objective fields (a flight rule).
                    time_window_s=(0.0, 5000.0), energy_budget_j=1.5e8)],
        [Constraint(constraint_id="prefer-distance", kind=ConstraintKind.SOFT,
                    statement="minimize distance", weight=1.0)],
    )
    req = MIC.compile_intent(intent)

    # the hard caps are on the planner's HARD penalty path (objective_constraints), keyed as the planner's
    # budget keys -- the time window close -> max_time_s, the energy budget -> max_energy_J.
    assert req.mission.objective_constraints["max_time_s"] == 5000.0
    assert req.mission.objective_constraints["max_energy_J"] == 1.5e8
    # they are NOT tradeable weights in the soft objective.
    assert "time" not in MP.parse_objective(req.objective)
    assert "energy" not in MP.parse_objective(req.objective)


def test_hard_constraint_with_weight_is_rejected():  # [REQ:CP-04]
    # a flight rule must never be expressible as a soft, tradeable weight. MO-01's Constraint model rejects
    # a weight on a HARD/FLIGHT_RULE constraint at construction, so the contradiction cannot even be built
    # (the boundary that the compiler also re-asserts). Either way it never reaches the soft objective.
    with pytest.raises(ValueError, match="weight"):
        Constraint(constraint_id="bad", kind=ConstraintKind.FLIGHT_RULE,
                   statement="energy ceiling", weight=0.5)


def test_objective_time_window_compiles_to_hard_time_budget():  # [REQ:CP-04]
    intent = _intent(
        "deadline",
        [_objective("pit", target_row=8.0, target_col=8.0, time_window_s=(0.0, 3600.0))],
    )
    req = MIC.compile_intent(intent)
    # an objective's time-window close is a HARD makespan budget, not a soft weight.
    assert req.mission.objective_constraints["max_time_s"] == 3600.0


def test_energy_budget_is_aggregated_across_objectives():  # [REQ:CP-04]
    intent = _intent(
        "two-budgets",
        [_objective("a", target_row=4.0, target_col=4.0, energy_budget_j=1.0e8),
         _objective("b", target_row=20.0, target_col=20.0, energy_budget_j=2.0e8)],
    )
    req = MIC.compile_intent(intent)
    # the planner models a single mission energy budget; the per-objective ceilings aggregate.
    assert req.mission.objective_constraints["max_energy_J"] == 3.0e8


def test_prerequisites_compile_to_precedence():  # [REQ:CP-04]
    intent = _intent(
        "grade-then-haul",
        [_objective("grade", target_row=5.0, target_col=5.0),
         _objective("berm", target_row=20.0, target_col=20.0, prerequisites=("grade",))],
    )
    req = MIC.compile_intent(intent)
    # prerequisite (grade before berm) -> the planner's precedence (sequencer honours it). Exactly one
    # edge -- the lowering does NOT also auto-chain the orders into a spurious path.
    assert req.mission.precedence == [("grade", "berm")]


def test_independent_objectives_are_freely_orderable():  # [REQ:CP-04]
    # objectives with NO prerequisites must be freely orderable: the COMPILER must impose no hidden total
    # order, so authoring order does not constrain the plan. Asserted DETERMINISTICALLY on the compiler
    # contract (precedence-free + order-independent compile), NOT on the planner's specific route order --
    # under a mass-weighted "distance" objective + the min-cost-transport LP the optimal sequence genuinely
    # differs across numpy/scipy builds (CI vs local picked different optimal orders for these 3 objectives),
    # which is a planner-optimality property, not the CP-04 lowering contract this test covers.
    def _mk(order):
        return MIC.compile_intent(_intent(
            "free-order", [_objective(a, target_row=r, target_col=c) for (a, r, c) in order]))

    req = _mk([("A", 0.0, 0.0), ("B", 50.0, 50.0), ("C", 5.0, 5.0)])
    assert req.mission.precedence == []                                  # no prerequisites -> no precedence edges
    assert {o.action for o in req.mission.orders} == {"A", "B", "C"}     # all three lowered, independent
    # reordering the AUTHORED objectives yields the SAME precedence-free mission (authorship order does not leak)
    req2 = _mk([("C", 5.0, 5.0), ("A", 0.0, 0.0), ("B", 50.0, 50.0)])
    assert req2.mission.precedence == []
    assert {o.action for o in req2.mission.orders} == {"A", "B", "C"}
    # and the planner produces a valid plan visiting all three (freely sequenced; the SPECIFIC order is the
    # optimizer's env-dependent choice, deliberately not asserted here).
    result = MP.plan(mission=req.mission, algorithm="brute", objective="distance")
    visited = {a for t in result.trips for a in t.get("actions", ())}
    assert {"A", "B", "C"} <= visited


def test_soft_constraint_priorities_preserved_in_objective_string():  # [REQ:CP-04]
    # multiple soft constraints combine into a single convex objective; higher weight = higher priority.
    intent = _intent(
        "prio",
        [_objective("pit", target_row=8.0, target_col=8.0)],
        [Constraint(constraint_id="want-fast", kind=ConstraintKind.SOFT,
                    statement="minimize time", weight=0.75),
         Constraint(constraint_id="want-lean", kind=ConstraintKind.SOFT,
                    statement="minimize energy", weight=0.25)],
    )
    req = MIC.compile_intent(intent)
    weights = MP.parse_objective(req.objective)
    assert weights["time"] > weights["energy"]   # priority preserved through normalization


def test_soft_constraint_naming_unknown_metric_is_rejected():  # [REQ:CP-04]
    # a soft constraint must say WHAT to optimize; a statement naming no planner metric is rejected, not
    # silently dropped (which would turn a stated preference into a no-op).
    intent = _intent(
        "vague",
        [_objective("pit", target_row=8.0, target_col=8.0)],
        [Constraint(constraint_id="vibes", kind=ConstraintKind.SOFT,
                    statement="make it nice", weight=1.0)],
    )
    with pytest.raises(ValueError, match="no known planner optimization metric"):
        MIC.compile_intent(intent)


def test_compiled_mission_runs_real_planner_path():  # [REQ:CP-04]
    # end-to-end: the compiled request drives the REAL planner (no stub) on real moon physics, honouring
    # the prerequisite, and the mandatory objectives are present in the resulting plan's trips.
    intent = _intent(
        "e2e",
        [_objective("grade", target_row=6.0, target_col=6.0),
         _objective("berm", target_row=18.0, target_col=18.0, prerequisites=("grade",),
                    # a generous time window -> the plan is feasible under the hard makespan budget.
                    time_window_s=(0.0, 1.0e9))],
    )
    req = MIC.compile_intent(intent)
    result = MP.plan(algorithm="nearest", **req.plan_kwargs)
    assert isinstance(result, MP.PlanResult)
    # the real plan visited the mandatory work sites.
    visited = {a for t in result.trips for a in t.get("actions", ())}
    assert {"grade", "berm"} <= visited
    # and it honoured the prerequisite: grade's trip precedes berm's.
    labels = [t["label"] for t in result.trips]
    grade_i = next(i for i, label in enumerate(labels) if "grade" in label)
    berm_i = next(i for i, label in enumerate(labels) if "berm" in label)
    assert grade_i < berm_i
    # the plan produced real, finite totals (it ran the physics, not a stub).
    assert result.totals["time_s"] > 0.0
    assert result.totals["energy_J"] > 0.0


def test_no_mandatory_objective_is_rejected():  # [REQ:CP-04]
    # a MissionIntent with no mandatory objective has nothing to plan -> hard error, not a silent empty plan.
    intent = _intent(
        "all-optional",
        [_objective("maybe", target_row=8.0, target_col=8.0, mandatory=False,
                    priority=PriorityTier.STRETCH)],
    )
    with pytest.raises(ValueError, match="mandatory"):
        MIC.compile_intent(intent)


def test_empty_mission_is_rejected():  # [REQ:CP-04]
    intent = _intent("empty", [])
    with pytest.raises(ValueError, match="mandatory"):
        MIC.compile_intent(intent)


def test_mandatory_objective_without_material_budget_is_rejected():  # [REQ:CP-04]
    # MO-01 supplies no work geometry other than material_budget_kg; without it the planner cannot size an
    # order, so the compiler refuses rather than inventing a footprint.
    intent = _intent(
        "no-geometry",
        [_objective("pit", target_row=8.0, target_col=8.0, material_budget_kg=None)],
    )
    with pytest.raises(ValueError, match="material_budget_kg"):
        MIC.compile_intent(intent)


def test_optional_objectives_are_not_compiled_into_orders():  # [REQ:CP-04]
    # mandatory-first: a secondary/optional objective is NOT planned as a required order (it goes to the
    # optional list in compile_order, never the order set), so the plan carries only the mandatory work.
    intent = _intent(
        "mixed",
        [_objective("pit", target_row=8.0, target_col=8.0, material_budget_kg=300.0),
         _objective("nice-to-have", target_row=12.0, target_col=12.0, mandatory=False,
                    priority=PriorityTier.SECONDARY, material_budget_kg=100.0)],
    )
    req = MIC.compile_intent(intent)
    actions = {o.action for o in req.mission.orders}
    assert actions == {"pit"}                       # only the mandatory objective is an order
    assert "nice-to-have" in req.order.optional_objective_ids


# ---------------------------------------------------------------------------------------------------
# TOLERANCES: an objective's measurable acceptance tolerance (as-built flatness/profile) compiles onto
# the Mission and the planner's acceptance gate HONORS it (a tight tol fails a sloped pad; a loose tol
# passes it). MO-01 carries the tolerance as a STRUCTURED numeric field on the AcceptanceCriterion, not
# parsed out of free text -- the same no-invented-parsing-convention discipline the budget lowering uses.
# ---------------------------------------------------------------------------------------------------
def _sloped_dem():
    """A real geometric construction fixture: flat for col<50, a ~26.6deg ramp for col>=50 (rise 0.5
    m/cell). A uniform-depth cut over the ramp leaves a sloped as-built surface, so the as-built flatness
    RMSE is non-trivial and the acceptance tolerance is load-bearing (not the trivially-flat mantle)."""
    import numpy as np
    cell = 1.0
    Z = np.zeros((100, 100), dtype=np.float64)
    Z[:, 50:] = (np.arange(50) * 0.5)[None, :]
    return (Z, cell)


def test_acceptance_tolerance_compiles_onto_mission():  # [REQ:CP-04]
    # an objective's acceptance tolerance is a STRUCTURED MO-01 field; the compiler lowers it onto the
    # Mission so the planner's acceptance gate (validate_plan) consumes it -- not a hardcoded default.
    intent = _intent(
        "tight-pad",
        [_objective("pad", target_row=8.0, target_col=8.0, material_budget_kg=300.0, tolerance_m=0.05)],
    )
    req = MIC.compile_intent(intent)
    assert req.mission.accept_flatness_tol_m == 0.05


def test_acceptance_tolerance_is_the_tightest_over_objectives():  # [REQ:CP-04]
    # multiple mandatory objectives with different tolerances -> the mission as-built gate is the TIGHTEST
    # (a single mission-wide as-built RMSE tolerance must satisfy the strictest objective's acceptance).
    intent = _intent(
        "mixed-tol",
        [_objective("loose", target_row=4.0, target_col=4.0, tolerance_m=0.10),
         _objective("tight", target_row=20.0, target_col=20.0, tolerance_m=0.02)],
    )
    req = MIC.compile_intent(intent)
    assert req.mission.accept_flatness_tol_m == 0.02


def test_compiled_tolerance_is_honored_by_the_real_acceptance_gate():  # [REQ:CP-04]
    # end-to-end: the compiled tolerance flows into the REAL acceptance gate. The SAME sloped pad leaves an
    # as-built RMSE of ~0.24 m (a uniform cut on the ramp stays sloped); that FAILS a tight 0.02 m compiled
    # tolerance and PASSES a loose 0.30 m one -- proving the objective's tolerance, not a fixed default,
    # decides acceptance.
    dem = _sloped_dem()
    origin = (45.0, 45.0)                     # anchor the local frame so the pad straddles the ramp
    tight = MIC.compile_intent(_intent(
        "tol-tight",
        [_objective("pad", target_row=10.0, target_col=10.0, material_budget_kg=300.0, tolerance_m=0.02)]))
    loose = MIC.compile_intent(_intent(
        "tol-loose",
        [_objective("pad", target_row=10.0, target_col=10.0, material_budget_kg=300.0, tolerance_m=0.30)]))
    r_tight = MP.plan(mission=tight.mission, algorithm="nearest", dem=dem, dem_origin=origin,
                      with_acceptance=True)
    r_loose = MP.plan(mission=loose.mission, algorithm="nearest", dem=dem, dem_origin=origin,
                      with_acceptance=True)
    # the as-built surface is genuinely sloped (the tolerance is load-bearing, not a flat-mantle no-op).
    rmse = r_tight.validation["as_built_flatness_rmse_m"]
    assert 0.02 < rmse < 0.30
    # the gate reports the COMPILED tolerance and decides pass/fail against it.
    assert r_tight.validation["as_built_tol_m"] == 0.02
    assert r_tight.validation["as_built_pass"] is False
    assert r_loose.validation["as_built_tol_m"] == 0.30
    assert r_loose.validation["as_built_pass"] is True


def test_no_acceptance_tolerance_keeps_the_default_gate():  # [REQ:CP-04]
    # an objective that declares no structured tolerance -> the mission carries no override, so the
    # acceptance gate falls back to its documented default (byte-identical to a pre-CP-04-tolerance plan).
    intent = _intent("no-tol", [_objective("pad", target_row=8.0, target_col=8.0, material_budget_kg=300.0)])
    req = MIC.compile_intent(intent)
    assert req.mission.accept_flatness_tol_m is None


# ---------------------------------------------------------------------------------------------------
# KEEP-OUTS: a mission keep-out region compiles into the planner's existing keep-out mechanism, so the
# real planner ROUTES AROUND it (a haul bends around the no-go circle) and a build placed INSIDE one is
# flagged as a build-on-obstacle conflict. The compiler reuses Mission.keepouts (the planner's own
# routing input), not a parallel barrier model.
# ---------------------------------------------------------------------------------------------------
def test_keep_out_region_compiles_to_mission_keepouts():  # [REQ:CP-04]
    intent = _intent(
        "with-nogo",
        [_objective("pad", target_row=8.0, target_col=8.0, material_budget_kg=300.0)],
        keep_outs=[KeepOutRegion(region_id="boulder", x=4.0, y=4.0, radius_m=2.0,
                                 reason="boulder field")],
    )
    req = MIC.compile_intent(intent)
    # the keep-out lowered into the planner's OWN keepout input (a {x,y,r} circle in the local frame).
    assert req.mission.keepouts == ({"x": 4.0, "y": 4.0, "r": 2.0},)


def test_keep_out_makes_the_planner_route_around_it():  # [REQ:CP-04]
    # the compiled keep-out is honored by the REAL planner routing (route_leg): on a FLAT DEM (so slope is
    # never the blocker -- only the keep-out can force a detour), a no-go disk straddling the direct
    # (0,0)->(20,20) line makes the router bend AROUND it, lengthening the routed path vs the same leg with
    # no keep-out. This drives the planner's own costmap router, not a parallel barrier model.
    import numpy as np
    flat = (np.zeros((60, 60), dtype=np.float64), 1.0)
    a, b = (2.0, 2.0), (40.0, 40.0)
    blocked = _intent(
        "route-around",
        [_objective("site", target_row=40.0, target_col=40.0, material_budget_kg=300.0)],
        keep_outs=[KeepOutRegion(region_id="rubble", x=21.0, y=21.0, radius_m=6.0, reason="rubble")],
    )
    mission = MIC.compile_intent(blocked).mission
    # the compiled keep-out reached the planner's routing input.
    assert mission.keepouts == ({"x": 21.0, "y": 21.0, "r": 6.0},)
    clear_m, _, clear_reached, _ = MP.route_leg(flat, (0.0, 0.0), a, b, keepouts=())
    routed_m, _, reached, waypoints = MP.route_leg(flat, (0.0, 0.0), a, b, keepouts=mission.keepouts)
    # the leg is still reachable (the router found a corridor) but it is LONGER -- it detoured around the
    # no-go disk -- and no waypoint lies inside the keep-out.
    assert clear_reached and reached
    assert routed_m > clear_m
    assert all(not MP.point_in_keepout(wx, wy, mission.keepouts[0]) for wx, wy in waypoints)


def test_build_inside_a_keep_out_is_flagged_as_a_conflict():  # [REQ:CP-04]
    # an objective whose target sits INSIDE a compiled keep-out is a build-on-obstacle: the planner's own
    # conflict check (keepout_conflicts) flags it, so an operator cannot silently site work on a no-go.
    intent = _intent(
        "build-on-nogo",
        [_objective("pad", target_row=10.0, target_col=10.0, material_budget_kg=300.0)],
        keep_outs=[KeepOutRegion(region_id="crater", x=10.0, y=10.0, radius_m=3.0, reason="crater")],
    )
    req = MIC.compile_intent(intent)
    result = MP.plan(mission=req.mission, algorithm="nearest")
    assert result.totals["keepout_conflicts"] == 1


def test_keep_out_rectangle_and_polygon_compile():  # [REQ:CP-04]
    # a keep-out region may be a circle, an axis-aligned rectangle, or a polygon -- each lowers to the
    # matching planner keepout shape the router already understands (reusing point_in_keepout / the raster).
    intent = _intent(
        "shapes",
        [_objective("pad", target_row=2.0, target_col=2.0, material_budget_kg=300.0)],
        keep_outs=[
            KeepOutRegion(region_id="rect", x0=30.0, y0=30.0, x1=40.0, y1=40.0, reason="trench"),
            KeepOutRegion(region_id="poly", points=[(50.0, 50.0), (60.0, 50.0), (55.0, 60.0)],
                          reason="ejecta"),
        ],
    )
    req = MIC.compile_intent(intent)
    assert {"x0": 30.0, "y0": 30.0, "x1": 40.0, "y1": 40.0} in req.mission.keepouts
    assert {"points": [[50.0, 50.0], [60.0, 50.0], [55.0, 60.0]]} in req.mission.keepouts


def test_compiled_tolerance_is_exercised_on_the_live_rehearse_path():  # [REQ:CP-04]
    # CP-04 X (integration): the compiled as-built tolerance is not only honored by the planner API
    # (plan(with_acceptance=True)) but EXERCISED on the live REHEARSE product path -- lode.resync.
    # forward_compare (the executive REHEARSED edge, /executive/advance). A mission compiled WITH an
    # acceptance tolerance surfaces the as-built verdict against THAT compiled tolerance in every future;
    # a mission compiled WITHOUT one is byte-identical (no as-built field, no acceptance computed).
    from lode.resync import forward_compare

    req = MIC.compile_intent(_intent(
        "rehearse-accept",
        [_objective("pad", target_row=8.0, target_col=8.0, material_budget_kg=300.0, tolerance_m=0.035)]))
    assert req.mission.accept_flatness_tol_m == 0.035
    fc = forward_compare(req.mission, candidates=("nearest",))
    assert fc["futures"], "forward_compare produced no futures"
    for f in fc["futures"]:
        # the COMPILED tolerance (0.035), not a hardcoded default, is what the live path's gate used
        assert f["as_built_tol_m"] == 0.035, f"live rehearse path did not honor the compiled tolerance: {f}"
        assert isinstance(f["as_built_pass"], bool)

    # no compiled tolerance -> the live path stays byte-identical (no acceptance computed, no field)
    req_none = MIC.compile_intent(_intent(
        "rehearse-no-accept",
        [_objective("pad", target_row=8.0, target_col=8.0, material_budget_kg=300.0)]))
    assert req_none.mission.accept_flatness_tol_m is None
    fc_none = forward_compare(req_none.mission, candidates=("nearest",))
    for f in fc_none["futures"]:
        assert "as_built_pass" not in f and "as_built_tol_m" not in f


# ---------------------------------------------------------------------------------------------------
# ML-07: the mission-planner-LLM guardrail. A planner front-end (an LLM, an operator, a script) MAY
# author a candidate task graph, but a candidate is only ever a typed MO-01 MissionIntent: it must
# compile through the CP-04 typed boundary to a validated Mission, pass the compiler's deterministic
# validation, and be MO-02 executive-APPROVED (director-signed RELEASED) before any simulation or
# command lowering runs. No LLM is built here (the row's "may" clause); the guardrail is what binds.
# ---------------------------------------------------------------------------------------------------
def test_ml07_candidate_plan_is_gated_on_typed_compile_and_executive_release():  # [REQ:ML-07]
    # the full guardrail chain on ONE candidate plan: typed compile -> deterministic validation ->
    # executive approval -> only THEN sim execution. At every pre-release state the sim refuses to run.
    from lode import mission_lifecycle as LC
    from lode.sim_execution import run_sim_execution
    from stewie.contracts.executive import ExecutiveState, MissionExecutive, SignedRevision

    intent = _intent(
        "ml07-guardrail",
        [_objective("pad", target_row=8.0, target_col=8.0, material_budget_kg=300.0)])

    # (1) the candidate compiles through the typed MO-01 -> CP-04 path to a validated planner Mission.
    req = MIC.compile_intent(intent)
    assert isinstance(req.mission, MP.Mission)
    assert {o.action for o in req.mission.orders} == {"pad"}

    # (2) sim / command lowering is BLOCKED before executive approval -- even a fully analyzed,
    # rehearsed AND reviewed plan cannot run until the director signs the release (MO-02).
    legs = [{"faults": []}]
    ex = MissionExecutive.start(intent)
    for step in (None, LC.analyze, LC.rehearse, LC.review):     # DRAFT, ANALYZED, REHEARSED, REVIEWED
        if step is not None:
            ex = step(ex).executive
        assert ex.state is not ExecutiveState.RELEASED
        with pytest.raises(ValueError, match="RELEASED"):
            run_sim_execution(ex, legs)

    # (3) director release signs the immutable revision; only the RELEASED plan may be simulated.
    released = LC.release(ex).executive
    assert released.state is ExecutiveState.RELEASED
    rel = released.released_revision
    assert rel is not None and rel.signed_by == "director"
    assert rel.content_hash == SignedRevision.hash_intent(intent)
    run = run_sim_execution(released, legs)
    assert run["final_state"] == "completed" and run["label"] == "sim"


def test_ml07_free_form_candidate_plan_is_rejected_at_the_typed_boundary():  # [REQ:ML-07]
    # what an unguarded LLM would emit -- free-form prose or a raw task-graph dict -- is REJECTED at the
    # typed boundary: compile_intent accepts ONLY a canonical MO-01 MissionIntent, so no free-form plan
    # can reach the planner (or, downstream, the executive) uncompiled.
    for free_form in (
        "excavate a pad at (8, 8) then build a berm",                    # prose
        {"tasks": [{"do": "dig", "where": [8, 8]}]},                     # untyped task-graph dict
    ):
        with pytest.raises(ValueError, match="canonical"):
            MIC.compile_intent(free_form)


def test_ml07_invalid_typed_candidate_fails_validation_and_never_reaches_release():  # [REQ:ML-07]
    # a candidate that IS typed but fails deterministic validation (a soft constraint naming no planner
    # metric -- free-form intent smuggled into a typed field) is rejected by the compiler, so the
    # lifecycle refuses to advance: the executive stays DRAFT and nothing can be released or simulated.
    from lode import mission_lifecycle as LC
    from stewie.contracts.executive import ExecutiveState, MissionExecutive

    intent = _intent(
        "ml07-vague",
        [_objective("pad", target_row=8.0, target_col=8.0, material_budget_kg=300.0)],
        [Constraint(constraint_id="vibes", kind=ConstraintKind.SOFT,
                    statement="make it nice", weight=1.0)])
    ex = MissionExecutive.start(intent)
    with pytest.raises(ValueError, match="no known planner optimization metric"):
        LC.analyze(ex)
    assert ex.state is ExecutiveState.DRAFT and ex.released_revision is None


def test_r4_non_lunar_body_carries_its_frame_and_is_rejected_not_silently_moon():
    """[dispatch-audit R4] Mars->Moon frame bug: a non-lunar body's objectives must carry the body's OWN
    coordinate frame (not the MOON_ME default), so _intent_body REJECTS them before release rather than
    silently compiling a mars mission to a moon plan (which would use Moon gravity + a lunar terrain anchor).
    Direct-verification regression for the audit finding input_body='mars' -> objective_frame='MOON_ME'."""
    orders = [{"kind": "cut", "action": "cut 1", "x": 10, "y": 20, "footprint_m2": 36, "depth_m": 0.1}]
    # moon (unchanged): MOON_ME frame, compiles to the moon planner.
    im, _ = MIC.intent_from_orders(orders, mission_id="m", approver="op", body="moon")
    assert {o.frame for o in im.objectives} == {"MOON_ME"}
    assert MIC._intent_body(im) == "moon"
    # mars: the objectives now carry MARS_ME (the R4 fix, not the MOON_ME default), and _intent_body REJECTS
    # the non-lunar frame instead of silently returning "moon" -- body/frame integrity preserved.
    imm, _ = MIC.intent_from_orders(orders, mission_id="m", approver="op", body="mars")
    assert {o.frame for o in imm.objectives} == {"MARS_ME"}
    with pytest.raises(ValueError, match="MARS_ME|not a known lunar"):
        MIC._intent_body(imm)
