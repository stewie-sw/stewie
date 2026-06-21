"""MO-02 (§27.2.C / P1-2 mission-ops review): the mission-executive STATE MACHINE.

Grounded in ``docs/architecture_review_2026-06-20_mission_ops.md`` P1-2 ("The mission executive needs
explicit state and authority transitions") and ``PRD.md`` §27.2.C MO-02. The lifecycle is::

    DRAFT -> ANALYZED -> REHEARSED -> REVIEWED -> RELEASED -> ARMED -> EXECUTING ->
    (HOLDING | SAFED | COMPLETED | ABORTED) -> DEBRIEFED

This is the PURE state machine + guards. It is deliberately NOT wired to live ROS/hardware (the
execution tier is gated, per the review §7 and PRD MO-04: "all execution UI stays labeled
SIMULATION/FORECAST until MO-02 exists and passes fault injection"). What it enforces, in code:

* **Authorized, evidenced transitions** -- every transition REQUIRES a non-empty ``evidence`` string
  and an ``role`` that is in the transition's authorizing-role set; a transition lacking either is
  REJECTED (``ValueError`` for the empty case, ``PermissionError`` for the wrong role).
* **Legal edges only** -- a transition not in the transition table raises ``IllegalTransition``.
* **Signed immutable revision on RELEASED** -- entering ``RELEASED`` produces a ``SignedRevision``: a
  FROZEN record carrying a deterministic content hash of the mission intent, signed by the releasing
  role. It cannot be mutated in place.
* **Replanning makes a NEW revision** -- ``replan`` returns a FRESH executive in ``DRAFT`` carrying a
  new (higher-revision) intent; the already-released record is never mutated.
* **SAFE/HOLD reachability** -- ``SAFED`` is reachable from every live state (``ARMED``, ``EXECUTING``,
  ``HOLDING``); ``HOLDING`` is reachable from ``EXECUTING`` and can resume it.

The executive itself is a frozen pydantic model (a snapshot): a transition returns a NEW executive
rather than mutating, matching the immutable-snapshot pattern of the rest of ``stewie.contracts``.
"""
from __future__ import annotations

import hashlib
import json
from enum import Enum

from pydantic import Field

from . import Contract
from .mission_ops import MissionIntent


class IllegalTransition(ValueError):
    """Raised when a transition is not a legal edge of the executive state machine. Subclasses
    ``ValueError`` so callers may catch either; the distinct type lets the executive separate an
    illegal-edge rejection from an evidence/role rejection."""


class ExecutiveState(str, Enum):
    """MO-02 / P1-2: the mission-executive lifecycle states. The head DRAFT..RELEASED is the planning
    and authorization chain (RELEASED = a signed immutable revision); ARMED..EXECUTING is the live
    chain (gated -- not wired to hardware here); HOLDING/SAFED/COMPLETED/ABORTED are the execution
    outcomes; DEBRIEFED is the terminal closeout."""
    DRAFT = "draft"
    ANALYZED = "analyzed"
    REHEARSED = "rehearsed"
    REVIEWED = "reviewed"
    RELEASED = "released"
    ARMED = "armed"
    EXECUTING = "executing"
    HOLDING = "holding"
    SAFED = "safed"
    COMPLETED = "completed"
    ABORTED = "aborted"
    DEBRIEFED = "debriefed"


# The legal transition table: state -> {target -> frozenset(authorizing roles)}. A transition is legal
# only if (a) the target is a key under the source state and (b) the actor's role is in its role set.
# SAFED is reachable from every live state (ARMED/EXECUTING/HOLDING) -- the independent safe stop.
_TRANSITIONS: dict[ExecutiveState, dict[ExecutiveState, frozenset[str]]] = {
    ExecutiveState.DRAFT: {
        ExecutiveState.ANALYZED: frozenset({"planner"}),
    },
    ExecutiveState.ANALYZED: {
        ExecutiveState.REHEARSED: frozenset({"operator", "planner"}),
    },
    ExecutiveState.REHEARSED: {
        ExecutiveState.REVIEWED: frozenset({"reviewer"}),
    },
    ExecutiveState.REVIEWED: {
        # RELEASED is the signing transition -- director authority only.
        ExecutiveState.RELEASED: frozenset({"director"}),
    },
    ExecutiveState.RELEASED: {
        ExecutiveState.ARMED: frozenset({"operator"}),
    },
    ExecutiveState.ARMED: {
        ExecutiveState.EXECUTING: frozenset({"operator"}),
        ExecutiveState.SAFED: frozenset({"safety", "operator", "director"}),
    },
    ExecutiveState.EXECUTING: {
        ExecutiveState.HOLDING: frozenset({"operator", "safety"}),
        ExecutiveState.SAFED: frozenset({"safety", "operator", "director"}),
        ExecutiveState.COMPLETED: frozenset({"operator"}),
        ExecutiveState.ABORTED: frozenset({"director", "operator"}),
    },
    ExecutiveState.HOLDING: {
        ExecutiveState.EXECUTING: frozenset({"operator"}),
        ExecutiveState.SAFED: frozenset({"safety", "operator", "director"}),
        ExecutiveState.ABORTED: frozenset({"director", "operator"}),
    },
    ExecutiveState.SAFED: {
        ExecutiveState.ABORTED: frozenset({"director", "operator"}),
        ExecutiveState.DEBRIEFED: frozenset({"reviewer"}),
    },
    ExecutiveState.COMPLETED: {
        ExecutiveState.DEBRIEFED: frozenset({"reviewer"}),
    },
    ExecutiveState.ABORTED: {
        ExecutiveState.DEBRIEFED: frozenset({"reviewer"}),
    },
    ExecutiveState.DEBRIEFED: {},     # terminal -- no successor
}


class SignedRevision(Contract):
    """MO-02: the SIGNED IMMUTABLE plan revision produced when the executive enters ``RELEASED``. It
    freezes the mission intent at its revision number, records who signed it (the releasing role), and
    binds the content with a deterministic SHA-256 hash. Being a frozen Contract, it cannot be mutated
    in place -- replanning produces a NEW ``SignedRevision`` (a new revision), never an edit of this
    one (review P1-2: "Replanning creates a new revision and never mutates the released plan in
    place")."""
    revision: int = Field(ge=0)
    intent: MissionIntent
    signed_by: str
    content_hash: str

    @staticmethod
    def hash_intent(intent: MissionIntent) -> str:
        """The deterministic content hash that binds a signed revision to its intent. Hashes the
        canonical (sorted-key) JSON dump of the intent, so the same intent always yields the same hash
        and any content change yields a different one."""
        payload = json.dumps(intent.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @classmethod
    def sign(cls, intent: MissionIntent, signed_by: str) -> SignedRevision:
        """Create a signed revision for ``intent`` at ``intent.revision``, signed by ``signed_by``,
        with the content hash computed over the intent."""
        return cls(
            revision=intent.revision,
            intent=intent,
            signed_by=signed_by,
            content_hash=cls.hash_intent(intent),
        )


class MissionExecutive(Contract):
    """MO-02 / P1-2: the mission-executive state machine. A FROZEN snapshot -- ``transition`` and
    ``replan`` return a NEW executive rather than mutating, so the released history is never
    overwritten. Carries the current ``state``, the ``intent`` it governs, and (once released) the
    ``released_revision`` (the signed immutable record)."""
    state: ExecutiveState = ExecutiveState.DRAFT
    intent: MissionIntent
    released_revision: SignedRevision | None = None

    @classmethod
    def start(cls, intent: MissionIntent) -> MissionExecutive:
        """Begin a new mission executive in DRAFT governing ``intent``."""
        return cls(state=ExecutiveState.DRAFT, intent=intent, released_revision=None)

    def _legal_targets(self) -> dict[ExecutiveState, frozenset[str]]:
        return _TRANSITIONS[self.state]

    def transition(self, target: ExecutiveState, *, role: str, evidence: str) -> MissionExecutive:
        """Advance to ``target`` under ``role`` with ``evidence``. Enforces, in order: (1) evidence and
        role must be non-empty (``ValueError``); (2) the edge ``state -> target`` must be in the
        transition table (``IllegalTransition``); (3) ``role`` must be in the edge's authorizing-role
        set (``PermissionError``). On entering ``RELEASED`` it signs an immutable revision. Returns a
        NEW executive."""
        if not evidence:
            raise ValueError(
                f"MO-02: transition {self.state.value} -> {target.value} requires named evidence")
        if not role:
            raise ValueError(
                f"MO-02: transition {self.state.value} -> {target.value} requires an authorizing role")
        legal = self._legal_targets()
        if target not in legal:
            raise IllegalTransition(
                f"MO-02: illegal transition {self.state.value} -> {target.value} "
                f"(legal: {sorted(t.value for t in legal)})")
        authorized = legal[target]
        if role not in authorized:
            raise PermissionError(
                f"MO-02: role {role!r} may not perform {self.state.value} -> {target.value} "
                f"(authorized: {sorted(authorized)})")

        released = self.released_revision
        if target is ExecutiveState.RELEASED:
            # entering RELEASED signs an immutable revision of the current intent
            released = SignedRevision.sign(self.intent, signed_by=role)
        return self.model_copy(update={"state": target, "released_revision": released})

    def replan(self, new_intent: MissionIntent, *, role: str, evidence: str) -> MissionExecutive:
        """Replan with ``new_intent`` -- returns a FRESH executive in DRAFT carrying the new intent,
        leaving any already-released revision untouched (review P1-2: replanning creates a NEW revision,
        never mutates the released plan in place). ``new_intent.revision`` MUST strictly advance the
        current intent's revision (``ValueError`` otherwise). Evidence + role are required for the same
        reason transitions are (a replan is an authorized act)."""
        if not evidence:
            raise ValueError("MO-02: replan requires named evidence")
        if not role:
            raise ValueError("MO-02: replan requires an authorizing role")
        if new_intent.revision <= self.intent.revision:
            raise ValueError(
                f"MO-02: replan must advance the revision number "
                f"({new_intent.revision} must be > {self.intent.revision})")
        # a fresh machine in DRAFT -- the old executive (and its released_revision) is left intact
        return MissionExecutive.start(new_intent)
