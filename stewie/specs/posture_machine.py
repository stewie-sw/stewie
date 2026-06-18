"""AM-01/AM-02: the explicit posture state machine for the articulated excavator -- the eight canonical
postures, their LEGAL transitions, and a stability guard.

PURE + structural: the legal-transition table and the safety semantics live on-host; the per-posture lift
and stability-margin NUMBERS are supplied by the caller (`dart.posture_select` / `stewie.physics.
posture_kinematics` on-host; the flight-qualified posture geometry is the gated Q tier). So the FSM
enforces transition LEGALITY everywhere, and a transition INTO a raised/working posture is additionally
rejected when the supplied stability margin is inadequate (AM-02/AM-03). `BRAKED_HOLD` is the safe stance
(the SF-01 safe-stop posture) and is reachable from EVERY state; the recovery postures (`SELF_RIGHT`,
`IRON_CROSS`) are reachable ONLY from `BRAKED_HOLD` -- you safe first, then recover (AM-06).
"""
from __future__ import annotations

TRANSIT = "TRANSIT"
DIG = "DIG"
DUMP_Z = "DUMP_Z"
MEERKAT = "MEERKAT"
DRUM_WALK = "DRUM_WALK"
IRON_CROSS = "IRON_CROSS"
SELF_RIGHT = "SELF_RIGHT"
BRAKED_HOLD = "BRAKED_HOLD"
POSTURE_STATES = (TRANSIT, DIG, DUMP_Z, MEERKAT, DRUM_WALK, IRON_CROSS, SELF_RIGHT, BRAKED_HOLD)

#: postures that RAISE the chassis / extend arms into a working or recovery stance -- a transition INTO
#: one of these is gated on an adequate stability margin (AM-02 stability-margin precondition).
_RAISED = frozenset({DIG, DUMP_Z, MEERKAT, DRUM_WALK, IRON_CROSS})

#: legal transitions (grounded in the AM-01..06 semantics + physical sense). TRANSIT is the mobile hub;
#: DIG<->DUMP_Z chain while working; MEERKAT/DRUM_WALK return to TRANSIT; BRAKED_HOLD (added to every
#: state below) is the universal safe stop; SELF_RIGHT/IRON_CROSS are recovery-only from BRAKED_HOLD.
_LEGAL = {
    TRANSIT: {DIG, DUMP_Z, MEERKAT, DRUM_WALK},
    DIG: {TRANSIT, DUMP_Z},
    DUMP_Z: {TRANSIT, DIG},
    MEERKAT: {TRANSIT},
    DRUM_WALK: {TRANSIT},
    BRAKED_HOLD: {TRANSIT, SELF_RIGHT, IRON_CROSS},
    SELF_RIGHT: {BRAKED_HOLD, TRANSIT},
    IRON_CROSS: {BRAKED_HOLD},
}


def legal_transitions(state: str) -> set:
    """The postures reachable from `state`. BRAKED_HOLD (the safe stop) is always reachable."""
    if state not in POSTURE_STATES:
        raise ValueError(f"unknown posture {state!r}; known: {POSTURE_STATES}")
    return set(_LEGAL.get(state, set())) | {BRAKED_HOLD}


def can_transition(frm: str, to: str, *, stability_margin_m: float | None = None,
                   min_margin_m: float = 0.05) -> tuple[bool, str]:
    """Return (allowed, reason). The transition must be in the legal table; a transition INTO a raised /
    working posture additionally requires ``stability_margin_m >= min_margin_m`` WHEN a margin is supplied
    (AM-02/AM-03). A self-transition is a no-op; BRAKED_HOLD is always reachable (the SF-01 safe)."""
    if frm not in POSTURE_STATES or to not in POSTURE_STATES:
        return False, f"unknown posture: {frm!r}->{to!r}"
    if to == frm:
        return True, "no-op"
    if to not in legal_transitions(frm):
        return False, f"illegal transition {frm}->{to}"
    if to in _RAISED and stability_margin_m is not None and stability_margin_m < min_margin_m:
        return False, f"stability margin {stability_margin_m:.3f} m < {min_margin_m} m for {to}"
    return True, "ok"


class PostureMachine:
    """A small posture FSM. `state` starts at BRAKED_HOLD (the safe stance); `transition` enforces
    `can_transition` and records `last_reason`; `safe_stop` drops to BRAKED_HOLD from any state (the
    SF-01 tie -- always legal)."""

    def __init__(self, state: str = BRAKED_HOLD) -> None:
        if state not in POSTURE_STATES:
            raise ValueError(f"unknown posture {state!r}; known: {POSTURE_STATES}")
        self.state = state
        self.last_reason = "init"

    def transition(self, to: str, *, stability_margin_m: float | None = None,
                   min_margin_m: float = 0.05) -> bool:
        ok, reason = can_transition(self.state, to, stability_margin_m=stability_margin_m,
                                    min_margin_m=min_margin_m)
        self.last_reason = reason
        if ok:
            self.state = to
        return ok

    def safe_stop(self) -> None:
        """SF-01 tie: drop to BRAKED_HOLD from any posture (always legal)."""
        self.state = BRAKED_HOLD
        self.last_reason = "safe_stop"
