"""MO-01..MO-04 (§27 mission-ops review): the typed mission-intent / provenance / labeling contracts.

Grounded in docs/architecture_review_2026-06-20_mission_ops.md (P1-1 objective+acceptance hierarchy,
P1-8 provenance vocabulary) and docs/ui_overhaul_plan_2026-06-20.md §5 (MO-01..MO-04). These are the
data spine the operational UI renders; MO-02 (the executive state machine) is deliberately OUT of this
brick (gated -- see §7). Each schema follows the FS-02 spine pattern: strict (extra='forbid'),
frozen, schema_version-stamped.

The load-bearing invariants tested here:
  * a HARD constraint / flight rule may carry NO optimization weight (a flight rule can never become a
    soft preference);
  * the compile/order helper places mandatory objectives + hard constraints BEFORE any weighted score;
  * combining two provenanced values with incompatible frames/revisions RAISES, never silently merges;
  * a labeled value FORCES its SIM/FORECAST/LIVE label.

Run: <venv>/bin/python -m pytest stewie/contracts/test_mission_ops.py -q
"""
import pytest
from pydantic import ValidationError

from stewie import contracts as C


# ---- helpers -----------------------------------------------------------------------------------

def _acc(crit_id="acc1"):
    return C.AcceptanceCriterion(criterion_id=crit_id, statement="flatness within tolerance",
                                 measurable="as-built RMSE <= 0.02 m", sensor="dem_overlay")


def _objective(**over):
    base = dict(
        objective_id="O-001", revision=1, statement="flatten the landing pad",
        rationale="lander needs a level surface", priority=C.PriorityTier.PRIMARY, mandatory=True,
        target_row=100.0, target_col=200.0, frame="MOON_ME",
        acceptance=[_acc()], confidence_required=0.9,
        contingency=C.Contingency(policy=C.ContingencyPolicy.REPLAN, detail="retry from charger"),
        approver="director", evidence="design memo 2026-06-20")
    base.update(over)
    return C.Objective(**base)


# ---- MO-04: SIM/FORECAST/LIVE labeling ---------------------------------------------------------

def test_data_label_enum_values():
    assert C.DataLabel.SIM.value == "sim"
    assert C.DataLabel.FORECAST.value == "forecast"
    assert C.DataLabel.LIVE.value == "live"


def test_labeled_value_forces_its_label():
    lv = C.LabeledValue(value=0.42, label=C.DataLabel.FORECAST)
    assert lv.value == 0.42 and lv.label is C.DataLabel.FORECAST
    assert lv.schema_version == C.SPINE_VERSION
    # the label is REQUIRED -- a value cannot be carried unlabeled
    with pytest.raises(ValidationError):
        C.LabeledValue(value=1.0)


def test_labeled_value_strict_and_round_trips():
    lv = C.LabeledValue(value=12.0, label=C.DataLabel.LIVE)
    assert C.LabeledValue.model_validate(lv.model_dump()) == lv
    with pytest.raises(ValidationError):                       # extra='forbid'
        C.LabeledValue.model_validate({"value": 1.0, "label": "sim", "rogue": 2})
    with pytest.raises(ValidationError):                       # only the three labels are valid
        C.LabeledValue(value=1.0, label="connected")


# ---- MO-03: provenance vocabulary --------------------------------------------------------------

def test_provenance_valid_and_versioned():
    p = C.Provenance(source="estimator", basis=C.DataLabel.FORECAST, timestamp_s=100.0, age_s=2.0,
                     frame="MOON_ME", units="m", confidence=0.8, revision=3)
    assert p.frame == "MOON_ME" and p.revision == 3 and p.schema_version == C.SPINE_VERSION
    with pytest.raises(ValidationError):
        C.Provenance(source="x", basis=C.DataLabel.LIVE, timestamp_s=0.0, age_s=-1.0,   # age >= 0
                     frame="MOON_ME", units="m", confidence=0.5, revision=1)
    with pytest.raises(ValidationError):
        C.Provenance(source="x", basis=C.DataLabel.LIVE, timestamp_s=0.0, age_s=0.0,
                     frame="MOON_ME", units="m", confidence=1.5, revision=1)            # conf in [0,1]


def test_provenanced_value_carries_provenance():
    p = C.Provenance(source="estimator", basis=C.DataLabel.LIVE, timestamp_s=10.0, age_s=0.5,
                     frame="MOON_ME", units="m", confidence=0.9, revision=2)
    pv = C.ProvenancedValue(value=3.14, provenance=p)
    assert pv.value == 3.14 and pv.provenance.frame == "MOON_ME"
    assert C.ProvenancedValue.model_validate(pv.model_dump()) == pv
    with pytest.raises(ValidationError):                       # provenance is required
        C.ProvenancedValue(value=1.0)


def test_combine_provenance_rejects_incompatible_frame():
    a = C.Provenance(source="loc", basis=C.DataLabel.LIVE, timestamp_s=10.0, age_s=0.0,
                     frame="MOON_ME", units="m", confidence=0.9, revision=1)
    b = C.Provenance(source="map", basis=C.DataLabel.LIVE, timestamp_s=10.0, age_s=0.0,
                     frame="SITE_LOCAL", units="m", confidence=0.9, revision=1)
    with pytest.raises(ValueError):                           # P1-8: reject, never silently combine
        C.combine_provenance(a, b)


def test_combine_provenance_rejects_incompatible_revision():
    a = C.Provenance(source="loc", basis=C.DataLabel.LIVE, timestamp_s=10.0, age_s=0.0,
                     frame="MOON_ME", units="m", confidence=0.9, revision=1)
    b = C.Provenance(source="map", basis=C.DataLabel.LIVE, timestamp_s=10.0, age_s=0.0,
                     frame="MOON_ME", units="m", confidence=0.9, revision=2)
    with pytest.raises(ValueError):
        C.combine_provenance(a, b)


def test_combine_provenance_merges_compatible():
    a = C.Provenance(source="loc", basis=C.DataLabel.LIVE, timestamp_s=10.0, age_s=1.0,
                     frame="MOON_ME", units="m", confidence=0.9, revision=2)
    b = C.Provenance(source="map", basis=C.DataLabel.LIVE, timestamp_s=12.0, age_s=3.0,
                     frame="MOON_ME", units="m", confidence=0.6, revision=2)
    merged = C.combine_provenance(a, b)
    # same frame+revision+units -> a valid merge: oldest (max age) / lowest confidence wins (conservative)
    assert merged.frame == "MOON_ME" and merged.revision == 2 and merged.units == "m"
    assert merged.age_s == 3.0 and merged.confidence == 0.6
    assert merged.source == "loc+map"


def test_combine_provenance_rejects_incompatible_units():
    a = C.Provenance(source="loc", basis=C.DataLabel.LIVE, timestamp_s=10.0, age_s=0.0,
                     frame="MOON_ME", units="m", confidence=0.9, revision=1)
    b = C.Provenance(source="map", basis=C.DataLabel.LIVE, timestamp_s=10.0, age_s=0.0,
                     frame="MOON_ME", units="deg", confidence=0.9, revision=1)
    with pytest.raises(ValueError):
        C.combine_provenance(a, b)


# ---- MO-01: mission intent hierarchy -----------------------------------------------------------

def test_priority_and_constraint_enums():
    assert {t.value for t in C.PriorityTier} == {"primary", "secondary", "stretch"}
    assert {k.value for k in C.ConstraintKind} == {"hard", "flight_rule", "soft"}


def test_acceptance_criterion_valid_and_strict():
    a = _acc()
    assert a.criterion_id == "acc1" and a.schema_version == C.SPINE_VERSION
    assert C.AcceptanceCriterion.model_validate(a.model_dump()) == a
    with pytest.raises(ValidationError):                       # extra='forbid'
        C.AcceptanceCriterion.model_validate(
            {"criterion_id": "a", "statement": "s", "measurable": "m", "rogue": 1})


def test_constraint_soft_carries_weight():
    c = C.Constraint(constraint_id="c-soft", kind=C.ConstraintKind.SOFT, statement="prefer short routes",
                     weight=0.5)
    assert c.weight == 0.5 and c.is_optimizable is True


def test_hard_constraint_must_not_carry_weight():  # the MO-01 load-bearing invariant
    # a HARD constraint with an optimization weight is rejected -- a flight rule can never be softened
    with pytest.raises(ValidationError):
        C.Constraint(constraint_id="c-hard", kind=C.ConstraintKind.HARD,
                     statement="never exceed 20 deg slope", weight=0.9)
    with pytest.raises(ValidationError):
        C.Constraint(constraint_id="c-fr", kind=C.ConstraintKind.FLIGHT_RULE,
                     statement="keep 10% energy reserve", weight=0.1)
    # the same hard constraint with NO weight is accepted, and is not optimizable
    hard = C.Constraint(constraint_id="c-hard", kind=C.ConstraintKind.HARD,
                        statement="never exceed 20 deg slope")
    assert hard.weight is None and hard.is_optimizable is False


def test_contingency_policy_enum():
    assert {p.value for p in C.ContingencyPolicy} == {
        "retry", "observe", "replan", "skip", "return", "safe"}


def test_objective_full_field_set():
    o = _objective()
    assert o.objective_id == "O-001" and o.revision == 1 and o.mandatory is True
    assert o.priority is C.PriorityTier.PRIMARY and o.frame == "MOON_ME"
    assert o.acceptance[0].criterion_id == "acc1"
    assert o.confidence_required == 0.9 and o.contingency.policy is C.ContingencyPolicy.REPLAN
    assert o.approver == "director"
    assert C.Objective.model_validate(o.model_dump()) == o      # round-trip
    with pytest.raises(ValidationError):                       # confidence_required in [0,1]
        _objective(confidence_required=1.4)
    with pytest.raises(ValidationError):                       # at least one acceptance criterion
        _objective(acceptance=[])


def test_mission_intent_hierarchy():
    primary = _objective(objective_id="P1", priority=C.PriorityTier.PRIMARY, mandatory=True)
    secondary = _objective(objective_id="S1", priority=C.PriorityTier.SECONDARY, mandatory=False)
    stretch = _objective(objective_id="X1", priority=C.PriorityTier.STRETCH, mandatory=False)
    hard = C.Constraint(constraint_id="c1", kind=C.ConstraintKind.HARD, statement="slope <= 20 deg")
    soft = C.Constraint(constraint_id="c2", kind=C.ConstraintKind.SOFT, statement="short routes",
                        weight=0.3)
    mi = C.MissionIntent(
        mission_id="M-42", revision=1, statement="prepare the landing site",
        objectives=[primary, secondary, stretch], constraints=[hard, soft],
        task_graph_ref="plan-ir:abc123")
    assert mi.mission_id == "M-42" and len(mi.objectives) == 3
    assert mi.task_graph_ref == "plan-ir:abc123"
    assert C.MissionIntent.model_validate(mi.model_dump()) == mi


def test_mission_intent_priority_accessors():
    primary = _objective(objective_id="P1", priority=C.PriorityTier.PRIMARY, mandatory=True)
    secondary = _objective(objective_id="S1", priority=C.PriorityTier.SECONDARY, mandatory=False)
    stretch = _objective(objective_id="X1", priority=C.PriorityTier.STRETCH, mandatory=False)
    mi = C.MissionIntent(mission_id="M", revision=1, statement="s",
                         objectives=[stretch, primary, secondary])
    assert [o.objective_id for o in mi.primary_objectives] == ["P1"]
    assert [o.objective_id for o in mi.secondary_objectives] == ["S1"]
    assert [o.objective_id for o in mi.stretch_objectives] == ["X1"]
    assert [o.objective_id for o in mi.mandatory_objectives] == ["P1"]


def test_compile_order_puts_mandatory_and_hard_before_weighted():
    # the MO-01 ordering invariant: mandatory objectives + hard/flight-rule constraints are compiled
    # FIRST; the weighted (soft) terms come strictly AFTER. A flight rule can never become a preference.
    primary = _objective(objective_id="P1", priority=C.PriorityTier.PRIMARY, mandatory=True)
    secondary = _objective(objective_id="S1", priority=C.PriorityTier.SECONDARY, mandatory=False)
    hard = C.Constraint(constraint_id="c-hard", kind=C.ConstraintKind.HARD, statement="slope")
    flight = C.Constraint(constraint_id="c-fr", kind=C.ConstraintKind.FLIGHT_RULE, statement="reserve")
    soft = C.Constraint(constraint_id="c-soft", kind=C.ConstraintKind.SOFT, statement="short",
                        weight=0.4)
    mi = C.MissionIntent(mission_id="M", revision=1, statement="s",
                         objectives=[secondary, primary], constraints=[soft, hard, flight])
    co = C.compile_order(mi)
    # mandatory objectives precede non-mandatory
    assert co.mandatory_objective_ids == ["P1"]
    assert co.optional_objective_ids == ["S1"]
    # ALL hard/flight constraints precede ALL weighted constraints, and no weighted term is hard
    assert co.hard_constraint_ids == ["c-hard", "c-fr"]
    assert co.weighted_constraint_ids == ["c-soft"]
    # the compiled sequence is hard-first then weighted -- the structural guarantee
    assert co.compiled_constraint_order == ["c-hard", "c-fr", "c-soft"]
    # and the invariant the helper guarantees: every weighted entry is_optimizable, none is hard
    assert all(not c.is_optimizable for c in (hard, flight))
    assert soft.is_optimizable
