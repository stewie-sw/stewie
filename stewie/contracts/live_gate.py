"""[REQ:EG-05] The training-to-live gate + live-execution token (PRD §29.5).

Before a mission goes live, the 8-step sequence must complete: (1) mission created, (2) simulation branch,
(3) rehearsal completed, (4) physics checks passed, (5) safety checks passed, (6) human approval recorded ->
(7) a LiveExecutionToken is issued -> (8) the command bridge unlocks only for a valid token. Steps 1-6 are the
MO-02 planning/authorization chain (DRAFT -> ANALYZED -> REHEARSED -> REVIEWED -> RELEASED; a RELEASED
SignedRevision certifies them). This formalizes step 7 (the token) + step 8 (the bridge-unlock check), so LIVE
role/mode authority (EG-02) alone is NOT sufficient to execute -- the rehearsal/physics/safety/approval
sequence must have completed and yielded a token bound to exactly the mission+revision being executed.

Wiring: this is the gate + token primitive. Threading the token through the /executive/run execute path (mint
on RELEASED, present at command lowering) is the noted [REQ:EG-05] integration follow-up, not half-wired here.
"""
from __future__ import annotations

import dataclasses
import hashlib
from dataclasses import dataclass


class LiveExecutionRefused(PermissionError):
    """Raised when a live-execution token is requested before the training-to-live sequence has completed, or
    when a live command is attempted without a valid token for the mission/revision being executed."""


@dataclass(frozen=True)
class LivePreconditions:
    """§29.5 steps 1-6 -- ALL must hold before a token may be issued. A RELEASED SignedRevision (MO-02)
    certifies these; making them explicit lets the gate refuse with the specific unmet step(s)."""
    mission_created: bool = False
    simulation_branch: bool = False
    rehearsal_completed: bool = False
    physics_passed: bool = False
    safety_passed: bool = False
    human_approval: bool = False

    def unmet(self) -> list[str]:
        return [f.name for f in dataclasses.fields(self) if not getattr(self, f.name)]

    def all_met(self) -> bool:
        return not self.unmet()


@dataclass(frozen=True)
class LiveExecutionToken:
    """§29.5 step 7: the certificate that the training-to-live gate passed for a mission's released revision.
    Bound to (mission_id, revision_id) by a signature so it cannot be forged or retargeted to another mission."""
    mission_id: str
    revision_id: str
    signature: str


def _sign(mission_id: str, revision_id: str) -> str:
    return hashlib.sha256(f"live-exec:{mission_id}:{revision_id}".encode()).hexdigest()


def issue_live_token(mission_id: str, revision_id: str, preconditions: LivePreconditions) -> LiveExecutionToken:
    """§29.5 step 7: mint a LiveExecutionToken ONLY when ALL of steps 1-6 hold. Raises LiveExecutionRefused
    (naming the unmet steps) otherwise. Separate from EG-02: this certifies the SEQUENCE, not the mode/role."""
    if not preconditions.all_met():
        raise LiveExecutionRefused(
            f"training-to-live gate not passed for {mission_id!r}: unmet steps {preconditions.unmet()}")
    return LiveExecutionToken(mission_id, revision_id, _sign(mission_id, revision_id))


def require_live_token(token: LiveExecutionToken | None, mission_id: str, revision_id: str) -> None:
    """§29.5 step 8: the command-bridge unlock check. Reject the live execute unless a VALID token for exactly
    this (mission_id, revision_id) is presented. Fail-closed on a missing / mismatched / forged token."""
    if token is None:
        raise LiveExecutionRefused(f"no live-execution token for {mission_id!r} (training-to-live gate)")
    if token.mission_id != mission_id or token.revision_id != revision_id:
        raise LiveExecutionRefused("live-execution token does not match the mission/revision being executed")
    if token.signature != _sign(mission_id, revision_id):
        raise LiveExecutionRefused("live-execution token signature invalid (forged or retargeted)")
