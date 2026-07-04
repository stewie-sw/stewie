"""[REQ:EG-08] The reconciliation lifecycle: a proposal advances observed→compared→proposed→reviewed→
accepted/rejected→applied→archived; a rejected proposal never mutates accepted truth; a manual override is
logged (to the EG-07 audit trail); illegal transitions are refused."""
import pytest

from stewie.contracts.audit import AuditLog
from stewie.contracts.reconciliation import (
    Proposal,
    ReconcileError,
    ReconcileState,
    advance,
    apply_proposal,
    can_transition,
    manual_override,
)

S = ReconcileState


def test_eg08_proposal_advances_through_the_lifecycle():  # [REQ:EG-08]
    p = Proposal(proposal_id="r1", state=S.OBSERVED, confidence=0.9)
    for nxt in (S.COMPARED, S.PROPOSED, S.REVIEWED, S.ACCEPTED):
        p = advance(p, nxt)
    p = apply_proposal(p)
    assert p.state is S.APPLIED
    assert advance(p, S.ARCHIVED).state is S.ARCHIVED


def test_eg08_rejected_proposal_never_mutates_accepted_truth():  # [REQ:EG-08]
    rej = advance(Proposal(proposal_id="r2", state=S.REVIEWED), S.REJECTED)
    with pytest.raises(ReconcileError):
        apply_proposal(rej)                                   # a rejected proposal cannot be applied
    assert can_transition(S.REJECTED, S.APPLIED) is False
    assert can_transition(S.REJECTED, S.ARCHIVED) is True     # it may only be archived


def test_eg08_illegal_transition_raises():  # [REQ:EG-08]
    with pytest.raises(ReconcileError):
        advance(Proposal(proposal_id="r3", state=S.OBSERVED), S.APPLIED)


def test_eg08_manual_override_is_logged_to_the_audit_trail():  # [REQ:EG-08]
    log = AuditLog()
    p = Proposal(proposal_id="r4", state=S.REVIEWED, confidence=0.4, model_error=True)
    new = manual_override(p, S.ACCEPTED, audit_log=log, actor="safety_officer:sam",
                          reason="human judged the low-confidence proposal valid",
                          timestamp="2026-07-03T22:20:00Z")
    assert new.state is S.ACCEPTED
    assert len(log.records()) == 1
    rec = log.records()[0]
    assert rec.actor == "safety_officer:sam" and "override" in rec.action
    assert log.verify() is True
