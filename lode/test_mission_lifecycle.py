"""MO-WIRE: wire MO-01 (MissionIntent) + CP-04 (compile_intent) + MO-02 (MissionExecutive) into a
LIVE plan->executive flow. ``lode.mission_lifecycle`` drives a fresh MissionExecutive through the
planning + authorization chain DRAFT -> ANALYZED -> REHEARSED -> REVIEWED -> RELEASED, attaching REAL
evidence at each transition (the compiler's deterministic plan_id at ANALYZED; the real
forward_compare ranking at REHEARSED) and honouring MO-02's role + evidence guards. Nothing synthetic:
the intent really compiles, the planner really runs, the executive really advances under its guards.

Run: <venv>/bin/python -m pytest lode/test_mission_lifecycle.py -q
"""
import pytest

import stewie.contracts as C
from stewie.contracts import executive as X
from lode import mission_lifecycle as LC


# ---- a real, compilable mission intent (mandatory objective with a material budget) ------------

def _intent(revision=0):
    acc = C.AcceptanceCriterion(criterion_id="acc1", statement="pad flat within tolerance",
                                measurable="as-built RMSE <= 0.02 m", sensor="dem_overlay")
    obj = C.Objective(
        objective_id="O-001", revision=revision, statement="flatten the landing pad",
        rationale="lander needs a level surface", priority=C.PriorityTier.PRIMARY, mandatory=True,
        target_row=100.0, target_col=120.0, frame="MOON_ME",
        acceptance=[acc], confidence_required=0.9, material_budget_kg=50.0,
        contingency=C.Contingency(policy=C.ContingencyPolicy.REPLAN, detail="retry from charger"),
        approver="director", evidence="design memo 2026-06-20")
    return C.MissionIntent(mission_id="M-001", revision=revision, statement="prepare the pad",
                           objectives=[obj], constraints=[], task_graph_ref="planir-001")


# ---- the happy path: a real intent compiles + plans and the executive reaches REVIEWED/RELEASED --

def test_analyze_compiles_and_attaches_real_plan_id():
    ex = X.MissionExecutive.start(_intent())
    res = LC.analyze(ex)
    assert res.executive.state is X.ExecutiveState.ANALYZED
    # the analyze step ran the REAL compiler -> a deterministic plan_id is attached as evidence
    pid = res.evidence["plan_id"]
    assert isinstance(pid, str) and len(pid) >= 8
    # the same intent compiles to the same deterministic plan_id (no wall clock)
    res2 = LC.analyze(X.MissionExecutive.start(_intent()))
    assert res2.evidence["plan_id"] == pid


def test_rehearse_runs_forward_compare_and_attaches_real_results():
    ex = LC.analyze(X.MissionExecutive.start(_intent())).executive
    res = LC.rehearse(ex)
    assert res.executive.state is X.ExecutiveState.REHEARSED
    fc = res.evidence["forward_compare"]
    # real forward_compare output: a ranked set of futures with measured numbers + a recommendation
    assert fc["recommended"] in {f["algorithm"] for f in fc["futures"]}
    assert len(fc["futures"]) >= 2
    for fut in fc["futures"]:
        assert fut["time_s"] > 0.0            # a real simulated makespan, not a placeholder


def test_full_lifecycle_reaches_released_with_signed_revision_and_evidence():
    ex = X.MissionExecutive.start(_intent())
    res = LC.run_lifecycle(ex)
    assert res.executive.state is X.ExecutiveState.RELEASED
    rel = res.executive.released_revision
    assert rel is not None                                   # the signed immutable revision
    assert rel.signed_by == "director"
    assert rel.content_hash == X.SignedRevision.hash_intent(rel.intent)
    # every transition carried REAL evidence: plan_id (ANALYZED) + forward_compare (REHEARSED)
    assert res.evidence["plan_id"]
    assert res.evidence["forward_compare"]["futures"]
    # the transition log records each legal edge with its authorizing role
    states = [t["to"] for t in res.transitions]
    assert states == ["analyzed", "rehearsed", "reviewed", "released"]
    roles = [t["role"] for t in res.transitions]
    assert roles == ["planner", "operator", "reviewer", "director"]


# ---- guard enforcement: unevidenced / illegal transitions are rejected -------------------------

def test_uncompilable_intent_is_rejected_not_advanced():
    # a mandatory objective WITHOUT material_budget_kg cannot be sized -> compile_intent raises, so the
    # lifecycle refuses to advance (no plan_id evidence can be fabricated).
    acc = C.AcceptanceCriterion(criterion_id="a", statement="s", measurable="m")
    obj = C.Objective(
        objective_id="O-x", revision=0, statement="no budget", rationale="r",
        priority=C.PriorityTier.PRIMARY, mandatory=True, target_row=1.0, target_col=2.0,
        acceptance=[acc], confidence_required=0.5,
        contingency=C.Contingency(policy=C.ContingencyPolicy.SAFE), approver="director")
    intent = C.MissionIntent(mission_id="M-x", revision=0, statement="s", objectives=[obj])
    ex = X.MissionExecutive.start(intent)
    with pytest.raises(ValueError):
        LC.analyze(ex)
    # the executive is unchanged (still DRAFT, no evidence)
    assert ex.state is X.ExecutiveState.DRAFT


def test_illegal_release_before_review_is_rejected():
    # advancing past the legal head (releasing a DRAFT) is an illegal MO-02 edge -> rejected.
    ex = X.MissionExecutive.start(_intent())
    with pytest.raises(X.IllegalTransition):
        LC.release(ex)            # DRAFT -> RELEASED is not a legal edge


def test_wrong_role_release_is_rejected():
    # the lifecycle release step signs under the director role; an explicit non-director role is refused
    # by MO-02's role guard (a planner may not sign a release).
    ex = LC.review(LC.rehearse(LC.analyze(X.MissionExecutive.start(_intent())).executive).executive).executive
    assert ex.state is X.ExecutiveState.REVIEWED
    with pytest.raises(PermissionError):
        LC.release(ex, role="planner")


def test_unevidenced_transition_is_rejected():
    # the lifecycle never emits an empty-evidence transition; calling the low-level advance with empty
    # evidence is rejected by MO-02 (a transition lacking named evidence is illegal).
    ex = X.MissionExecutive.start(_intent())
    with pytest.raises(ValueError):
        LC.advance(ex, X.ExecutiveState.ANALYZED, role="planner", evidence="")
