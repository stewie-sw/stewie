"""MO-02 (§27.2.C / P1-2 mission-ops review): the mission-executive STATE MACHINE.

Grounded in docs/architecture_review_2026-06-20_mission_ops.md P1-2 ("The mission executive needs
explicit state and authority transitions") and PRD.md §27.2.C MO-02:

    DRAFT -> ANALYZED -> REHEARSED -> REVIEWED -> RELEASED -> ARMED -> EXECUTING ->
    (HOLDING | SAFED | COMPLETED | ABORTED) -> DEBRIEFED

Load-bearing invariants tested here (every one enforced by code, not convention):
  * each transition REQUIRES named evidence + an authorizing role -- a transition lacking either is
    REJECTED;
  * an ILLEGAL transition (not in the transition table) raises;
  * RELEASED produces a SIGNED IMMUTABLE revision -- a frozen record carrying a content hash that
    cannot be mutated in place;
  * replanning creates a NEW revision (a new released record), never mutating the released one;
  * SAFED and HOLDING are reachable from EXECUTING; SAFED is reachable from anywhere live.

This is the PURE state machine + guards -- it is deliberately NOT wired to live ROS/hardware (that
tier is gated).

Run: <venv>/bin/python -m pytest stewie/contracts/test_executive.py -q
"""
import pytest
from pydantic import ValidationError

from stewie import contracts as C
from stewie.contracts import executive as X


# ---- helpers -----------------------------------------------------------------------------------

def _intent(revision=0):
    acc = C.AcceptanceCriterion(criterion_id="acc1", statement="flatness within tolerance",
                                measurable="as-built RMSE <= 0.02 m", sensor="dem_overlay")
    obj = C.Objective(
        objective_id="O-001", revision=revision, statement="flatten the landing pad",
        rationale="lander needs a level surface", priority=C.PriorityTier.PRIMARY, mandatory=True,
        target_row=100.0, target_col=200.0, frame="MOON_ME",
        acceptance=[acc], confidence_required=0.9,
        contingency=C.Contingency(policy=C.ContingencyPolicy.REPLAN, detail="retry from charger"),
        approver="director", evidence="design memo 2026-06-20")
    return C.MissionIntent(mission_id="M-001", revision=revision, statement="prepare the pad",
                           objectives=[obj], constraints=[], task_graph_ref="planir-001")


def _ev(role="planner", evidence="analysis report 2026-06-20"):
    return dict(role=role, evidence=evidence)


def _to_released(ex):
    """Drive a fresh executive through the legal head DRAFT->...->RELEASED, returning it."""
    ex = ex.transition(X.ExecutiveState.ANALYZED, role="planner", evidence="feasibility analysis")
    ex = ex.transition(X.ExecutiveState.REHEARSED, role="operator", evidence="sim rehearsal log")
    ex = ex.transition(X.ExecutiveState.REVIEWED, role="reviewer", evidence="review board minutes")
    ex = ex.transition(X.ExecutiveState.RELEASED, role="director", evidence="release authorization")
    return ex


# ---- states / table ----------------------------------------------------------------------------

def test_executive_state_enum_full_lifecycle():
    names = {s.value for s in X.ExecutiveState}
    assert names == {
        "draft", "analyzed", "rehearsed", "reviewed", "released", "armed", "executing",
        "holding", "safed", "completed", "aborted", "debriefed",
    }


def test_legal_linear_path_advances_state():
    ex = X.MissionExecutive.start(_intent())
    assert ex.state is X.ExecutiveState.DRAFT
    ex = _to_released(ex)
    assert ex.state is X.ExecutiveState.RELEASED
    ex = ex.transition(X.ExecutiveState.ARMED, role="operator", evidence="arming checklist passed")
    ex = ex.transition(X.ExecutiveState.EXECUTING, role="operator", evidence="execute command issued")
    assert ex.state is X.ExecutiveState.EXECUTING
    ex = ex.transition(X.ExecutiveState.COMPLETED, role="operator", evidence="all acceptance met")
    ex = ex.transition(X.ExecutiveState.DEBRIEFED, role="reviewer", evidence="debrief report filed")
    assert ex.state is X.ExecutiveState.DEBRIEFED


# ---- evidence + role enforcement ---------------------------------------------------------------

def test_transition_rejects_missing_evidence():
    ex = X.MissionExecutive.start(_intent())
    with pytest.raises(ValueError):
        ex.transition(X.ExecutiveState.ANALYZED, role="planner", evidence="")


def test_transition_rejects_missing_role():
    ex = X.MissionExecutive.start(_intent())
    with pytest.raises(ValueError):
        ex.transition(X.ExecutiveState.ANALYZED, role="", evidence="feasibility analysis")


def test_transition_rejects_unauthorized_role():
    """RELEASED is a director-authority transition; a planner may not release."""
    ex = X.MissionExecutive.start(_intent())
    ex = ex.transition(X.ExecutiveState.ANALYZED, role="planner", evidence="feasibility analysis")
    ex = ex.transition(X.ExecutiveState.REHEARSED, role="operator", evidence="sim rehearsal log")
    ex = ex.transition(X.ExecutiveState.REVIEWED, role="reviewer", evidence="review board minutes")
    with pytest.raises(PermissionError):
        ex.transition(X.ExecutiveState.RELEASED, role="planner", evidence="release authorization")


# ---- illegal transitions -----------------------------------------------------------------------

def test_illegal_skip_transition_raises():
    ex = X.MissionExecutive.start(_intent())
    # DRAFT -> EXECUTING is not a legal edge
    with pytest.raises(X.IllegalTransition):
        ex.transition(X.ExecutiveState.EXECUTING, role="operator", evidence="skip the gates")


def test_illegal_backward_transition_raises():
    ex = _to_released(X.MissionExecutive.start(_intent()))
    # RELEASED -> ANALYZED is not legal (replanning makes a NEW revision, not a backward edge)
    with pytest.raises(X.IllegalTransition):
        ex.transition(X.ExecutiveState.ANALYZED, role="planner", evidence="go back")


def test_terminal_debriefed_has_no_successor():
    ex = _to_released(X.MissionExecutive.start(_intent()))
    ex = ex.transition(X.ExecutiveState.ARMED, role="operator", evidence="arming checklist")
    ex = ex.transition(X.ExecutiveState.EXECUTING, role="operator", evidence="execute issued")
    ex = ex.transition(X.ExecutiveState.ABORTED, role="director", evidence="abort ordered")
    ex = ex.transition(X.ExecutiveState.DEBRIEFED, role="reviewer", evidence="debrief filed")
    with pytest.raises(X.IllegalTransition):
        ex.transition(X.ExecutiveState.ARMED, role="operator", evidence="restart")


# ---- SAFED / HOLDING reachability --------------------------------------------------------------

def test_holding_reachable_from_executing_and_back():
    ex = _to_released(X.MissionExecutive.start(_intent()))
    ex = ex.transition(X.ExecutiveState.ARMED, role="operator", evidence="arming checklist")
    ex = ex.transition(X.ExecutiveState.EXECUTING, role="operator", evidence="execute issued")
    ex = ex.transition(X.ExecutiveState.HOLDING, role="operator", evidence="hold: dust event")
    assert ex.state is X.ExecutiveState.HOLDING
    # a hold can resume execution
    ex = ex.transition(X.ExecutiveState.EXECUTING, role="operator", evidence="resume: dust cleared")
    assert ex.state is X.ExecutiveState.EXECUTING


def test_safed_reachable_from_executing():
    ex = _to_released(X.MissionExecutive.start(_intent()))
    ex = ex.transition(X.ExecutiveState.ARMED, role="operator", evidence="arming checklist")
    ex = ex.transition(X.ExecutiveState.EXECUTING, role="operator", evidence="execute issued")
    ex = ex.transition(X.ExecutiveState.SAFED, role="safety", evidence="SAFE: covariance loss")
    assert ex.state is X.ExecutiveState.SAFED


def test_safed_reachable_from_armed_and_holding():
    # from ARMED
    ex = _to_released(X.MissionExecutive.start(_intent()))
    ex = ex.transition(X.ExecutiveState.ARMED, role="operator", evidence="arming checklist")
    ex2 = ex.transition(X.ExecutiveState.SAFED, role="safety", evidence="SAFE before exec")
    assert ex2.state is X.ExecutiveState.SAFED
    # from HOLDING
    ex = ex.transition(X.ExecutiveState.EXECUTING, role="operator", evidence="execute issued")
    ex = ex.transition(X.ExecutiveState.HOLDING, role="operator", evidence="hold")
    ex = ex.transition(X.ExecutiveState.SAFED, role="safety", evidence="SAFE from hold")
    assert ex.state is X.ExecutiveState.SAFED


# ---- signed immutable revision -----------------------------------------------------------------

def test_released_produces_signed_immutable_revision():
    ex = _to_released(X.MissionExecutive.start(_intent()))
    rel = ex.released_revision
    assert rel is not None
    assert rel.revision == 0
    assert rel.signed_by == "director"
    assert rel.content_hash and len(rel.content_hash) == 64    # sha256 hex
    # the hash binds the intent content (deterministic)
    assert rel.content_hash == X.SignedRevision.hash_intent(rel.intent)
    # immutable: cannot mutate the frozen record in place
    with pytest.raises(ValidationError):
        rel.content_hash = "0" * 64
    with pytest.raises(ValidationError):
        rel.revision = 99


def test_no_released_revision_before_release():
    ex = X.MissionExecutive.start(_intent())
    assert ex.released_revision is None
    ex = ex.transition(X.ExecutiveState.ANALYZED, role="planner", evidence="feasibility analysis")
    assert ex.released_revision is None


def test_signed_revision_hash_changes_with_content():
    a = _intent(revision=0)
    b = _intent(revision=1)
    assert X.SignedRevision.hash_intent(a) != X.SignedRevision.hash_intent(b)


# ---- replan makes a NEW revision ---------------------------------------------------------------

def test_replan_creates_new_revision_never_mutates_released():
    ex = _to_released(X.MissionExecutive.start(_intent(revision=0)))
    first = ex.released_revision
    assert first.revision == 0

    # replan with an updated intent at the NEXT revision number
    new_intent = _intent(revision=1)
    replanned = ex.replan(new_intent, role="planner", evidence="replan: new approach")

    # the replanned executive is a FRESH machine in DRAFT carrying the new intent
    assert replanned.state is X.ExecutiveState.DRAFT
    assert replanned.intent.revision == 1
    assert replanned.released_revision is None

    # the ORIGINAL released record is untouched (immutable + still revision 0)
    assert ex.released_revision is first
    assert ex.released_revision.revision == 0
    assert ex.released_revision.content_hash == X.SignedRevision.hash_intent(_intent(revision=0))

    # driving the replanned machine to RELEASED yields a DISTINCT signed revision
    replanned = _to_released(replanned)
    second = replanned.released_revision
    assert second.revision == 1
    assert second.content_hash != first.content_hash


def test_replan_rejects_non_advancing_revision():
    ex = _to_released(X.MissionExecutive.start(_intent(revision=0)))
    with pytest.raises(ValueError):                  # a replan must advance the revision number
        ex.replan(_intent(revision=0), role="planner", evidence="same revision")


# ---- contract spine conformance ----------------------------------------------------------------

def test_signed_revision_is_strict_and_versioned():
    ex = _to_released(X.MissionExecutive.start(_intent()))
    rel = ex.released_revision
    assert rel.schema_version == C.SPINE_VERSION
    with pytest.raises(ValidationError):            # extra='forbid'
        X.SignedRevision.model_validate({**rel.model_dump(), "rogue": 1})


def test_executive_re_exported_from_contracts_package():
    # MO-02 follows the MO-01 re-export pattern so consumers use C.MissionExecutive
    assert C.MissionExecutive is X.MissionExecutive
    assert C.ExecutiveState is X.ExecutiveState
    assert C.SignedRevision is X.SignedRevision
