"""[REQ:EG-08] The reconciliation lifecycle (PRD §29.7).

A reconciliation proposal (prediction-vs-observation, feeds from MP-11) moves through a typed state machine:
``observed → compared → proposed → reviewed → accepted/rejected → applied → archived``, carrying its
confidence + model/sensor error flags. The lifecycle DAG is enforced: only an ACCEPTED proposal can be
APPLIED (so a REJECTED proposal never mutates accepted truth -- it can only be archived), and a manual
override of the state is recorded to the EG-07 audit trail.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from enum import Enum

from stewie.contracts.audit import AuditLog


class ReconcileState(str, Enum):
    OBSERVED = "observed"      # a fresh observation of the world
    COMPARED = "compared"      # compared against accepted truth
    PROPOSED = "proposed"      # a world/model update proposed
    REVIEWED = "reviewed"      # a human/authority has reviewed it
    ACCEPTED = "accepted"      # approved to apply
    REJECTED = "rejected"      # refused -- never applied
    APPLIED = "applied"        # the accepted change mutated accepted truth
    ARCHIVED = "archived"      # frozen record (terminal)


#: the legal lifecycle DAG. REJECTED reaches only ARCHIVED (never APPLIED); ARCHIVED is terminal.
LEGAL_TRANSITIONS: dict[ReconcileState, frozenset[ReconcileState]] = {
    ReconcileState.OBSERVED:  frozenset({ReconcileState.COMPARED}),
    ReconcileState.COMPARED:  frozenset({ReconcileState.PROPOSED}),
    ReconcileState.PROPOSED:  frozenset({ReconcileState.REVIEWED}),
    ReconcileState.REVIEWED:  frozenset({ReconcileState.ACCEPTED, ReconcileState.REJECTED}),
    ReconcileState.ACCEPTED:  frozenset({ReconcileState.APPLIED}),
    ReconcileState.APPLIED:   frozenset({ReconcileState.ARCHIVED}),
    ReconcileState.REJECTED:  frozenset({ReconcileState.ARCHIVED}),
    ReconcileState.ARCHIVED:  frozenset(),
}


class ReconcileError(Exception):
    """Raised on an illegal reconcile transition or an attempt to apply a non-accepted proposal."""


@dataclass(frozen=True)
class Proposal:
    """A reconciliation proposal snapshot: its state in the lifecycle + confidence + the model/sensor error
    flags + the proposed change. Frozen -- a transition returns a NEW Proposal."""
    proposal_id: str
    state: ReconcileState
    confidence: float = 0.0
    model_error: bool = False
    sensor_error: bool = False
    provenance: str = ""
    change: str = ""           # the proposed world/model update (summary or hash)


def can_transition(frm: ReconcileState | str, to: ReconcileState | str) -> bool:
    """True iff `frm -> to` is a legal lifecycle transition."""
    return ReconcileState(to) in LEGAL_TRANSITIONS[ReconcileState(frm)]


def advance(proposal: Proposal, to_state: ReconcileState | str) -> Proposal:
    """Advance a proposal to `to_state` if the transition is legal, returning the new Proposal; else raise."""
    to = ReconcileState(to_state)
    if not can_transition(proposal.state, to):
        raise ReconcileError(f"illegal reconcile transition {proposal.state.value} -> {to.value}")
    return dataclasses.replace(proposal, state=to)


def apply_proposal(proposal: Proposal) -> Proposal:
    """Apply an ACCEPTED proposal (mutate accepted truth -> APPLIED). A proposal that is NOT ACCEPTED (e.g.
    REJECTED) is refused, so a rejected proposal never mutates accepted truth."""
    if proposal.state is not ReconcileState.ACCEPTED:
        raise ReconcileError(f"only an ACCEPTED proposal can be applied (state={proposal.state.value})")
    return advance(proposal, ReconcileState.APPLIED)


def manual_override(proposal: Proposal, to_state: ReconcileState | str, *, audit_log: AuditLog, actor: str,
                    reason: str, timestamp: str) -> Proposal:
    """A human override of the reconcile state -- still a LEGAL transition (an override is not a bypass of the
    DAG), and always RECORDED to the EG-07 audit trail (who/what/why/before/after). Returns the new Proposal."""
    new = advance(proposal, to_state)
    audit_log.append(actor=actor, action=f"reconcile_override:{new.state.value}", timestamp=timestamp,
                     location=f"reconcile/{proposal.proposal_id}", mode="live", reason=reason,
                     before_state=proposal.state.value, after_state=new.state.value,
                     evidence=f"confidence={proposal.confidence};model_error={proposal.model_error}")
    return new
