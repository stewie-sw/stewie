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
import hmac
import os
import secrets
from dataclasses import dataclass

#: [dispatch-audit R3] a live-execution token is SHORT-LIVED -- the training-to-live gate authorizes a bounded
#: command window, not an indefinite one. [ASSUMPTION] 120 s (a small operations window over the move-and-wait
#: RTT); override with $STEWIE_LIVE_TOKEN_TTL_S. The SF-01 watchdog (5 s) still bounds each command inside it.
DEFAULT_LIVE_TOKEN_TTL_S: float = float(os.environ.get("STEWIE_LIVE_TOKEN_TTL_S", "120"))

#: [dispatch-audit R3] the KEYED secret the token signature (HMAC) is computed under, so a token cannot be
#: forged or its expiry extended without it. From $STEWIE_LIVE_TOKEN_SECRET when set (a stable key across
#: workers/restarts); otherwise a per-process random key -- unforgeable, zero-config, and since tokens are
#: short-lived (DEFAULT_LIVE_TOKEN_TTL_S) a key rotation on restart only invalidates already-expiring tokens.
_SECRET: bytes = (os.environ.get("STEWIE_LIVE_TOKEN_SECRET") or secrets.token_hex(32)).encode("utf-8")


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
    Bound to (mission_id, revision_id) by a KEYED HMAC signature so it cannot be forged or retargeted; and
    [dispatch-audit R3] EXPIRING -- ``issued_at`` + ``ttl_s`` bound a command window the HMAC also covers, so
    the expiry cannot be self-extended. ``revision_id`` is the released revision's immutable content_hash
    (R2/R3), so a token authorizes exactly the signed plan, not a mutable revision number."""
    mission_id: str
    revision_id: str
    issued_at: float
    ttl_s: float
    signature: str

    def is_expired(self, now: float) -> bool:
        """True once ``now`` is strictly past the issue time + ttl (the deadline itself is still valid)."""
        return now > self.issued_at + self.ttl_s


def _sign(mission_id: str, revision_id: str, issued_at: float, ttl_s: float) -> str:
    """A KEYED HMAC-SHA256 over the token's identity + validity window, so a token is unforgeable and its
    expiry unextendable without ``_SECRET`` (the old unkeyed sha256 was a public formula anyone could recompute)."""
    payload = f"live-exec:{mission_id}:{revision_id}:{issued_at!r}:{ttl_s!r}".encode("utf-8")
    return hmac.new(_SECRET, payload, hashlib.sha256).hexdigest()


def issue_live_token(mission_id: str, revision_id: str, preconditions: LivePreconditions, *,
                     now: float, ttl_s: float = DEFAULT_LIVE_TOKEN_TTL_S) -> LiveExecutionToken:
    """§29.5 step 7: mint a LiveExecutionToken ONLY when ALL of steps 1-6 hold. Raises LiveExecutionRefused
    (naming the unmet steps) otherwise. Separate from EG-02: this certifies the SEQUENCE, not the mode/role.
    [dispatch-audit R3] the token expires ``ttl_s`` after ``now`` (the caller supplies the clock -- no
    wall-clock inside the pure contract, mirroring SafingWatchdog); ``revision_id`` should be the released
    content_hash so the token authorizes the immutable signed plan."""
    if not preconditions.all_met():
        raise LiveExecutionRefused(
            f"training-to-live gate not passed for {mission_id!r}: unmet steps {preconditions.unmet()}")
    return LiveExecutionToken(mission_id, revision_id, float(now), float(ttl_s),
                              _sign(mission_id, revision_id, float(now), float(ttl_s)))


def require_live_token(token: LiveExecutionToken | None, mission_id: str, revision_id: str, *,
                       now: float) -> None:
    """§29.5 step 8: the command-bridge unlock check. Reject the live execute unless a VALID, UNEXPIRED token
    for exactly this (mission_id, revision_id) is presented. Fail-closed on a missing / mismatched / forged /
    expired token. ``now`` is the caller's clock (the pure contract holds no wall-clock)."""
    if token is None:
        raise LiveExecutionRefused(f"no live-execution token for {mission_id!r} (training-to-live gate)")
    if token.mission_id != mission_id or token.revision_id != revision_id:
        raise LiveExecutionRefused("live-execution token does not match the mission/revision being executed")
    expected = _sign(token.mission_id, token.revision_id, token.issued_at, token.ttl_s)
    if not hmac.compare_digest(token.signature, expected):   # constant-time; catches forgery + tampered ttl/issued_at
        raise LiveExecutionRefused("live-execution token signature invalid (forged, retargeted, or tampered)")
    if token.is_expired(now):
        raise LiveExecutionRefused("live-execution token expired (re-run the training-to-live gate)")
