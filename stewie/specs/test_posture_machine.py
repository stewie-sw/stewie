"""AM-01/AM-02: the posture state machine -- eight canonical postures, legal transitions, the universal
BRAKED_HOLD safe stop, recovery-only SELF_RIGHT/IRON_CROSS, and the AM-02 stability-margin guard on
raised postures (the margin is caller-supplied -- the flight-qualified geometry is the gated tier)."""
import pytest

from stewie.specs import posture_machine as PM


def test_eight_canonical_postures():  # [REQ:AM-01]
    assert set(PM.POSTURE_STATES) == {"TRANSIT", "DIG", "DUMP_Z", "MEERKAT", "DRUM_WALK",
                                      "IRON_CROSS", "SELF_RIGHT", "BRAKED_HOLD"}


def test_braked_hold_reachable_from_every_state():
    for s in PM.POSTURE_STATES:
        assert PM.BRAKED_HOLD in PM.legal_transitions(s)        # the SF-01 safe stop is always reachable


def test_recovery_postures_only_from_braked_hold():
    # SELF_RIGHT / IRON_CROSS are recovery-only: you safe first, then recover (AM-06)
    assert PM.can_transition("BRAKED_HOLD", "SELF_RIGHT")[0]
    assert PM.can_transition("BRAKED_HOLD", "IRON_CROSS")[0]
    assert not PM.can_transition("TRANSIT", "IRON_CROSS")[0]     # cannot iron-cross straight from transit
    assert not PM.can_transition("DIG", "SELF_RIGHT")[0]


def test_stability_margin_guards_raised_postures():  # [REQ:AM-02]
    # a transition INTO a raised/working posture is rejected below the margin, allowed above (or unsupplied)
    ok_lo, why = PM.can_transition("TRANSIT", "DIG", stability_margin_m=0.01, min_margin_m=0.05)
    assert not ok_lo and "stability margin" in why
    assert PM.can_transition("TRANSIT", "DIG", stability_margin_m=0.20, min_margin_m=0.05)[0]
    assert PM.can_transition("TRANSIT", "DIG")[0]                # no margin supplied -> structural legality only
    # the safe stop is never margin-gated
    assert PM.can_transition("DIG", "BRAKED_HOLD", stability_margin_m=0.0)[0]


def test_machine_enforces_and_safe_stops():
    m = PM.PostureMachine()
    assert m.state == "BRAKED_HOLD"                             # starts safe
    assert m.transition("TRANSIT") and m.state == "TRANSIT"
    assert m.transition("DIG", stability_margin_m=0.3) and m.state == "DIG"
    assert not m.transition("MEERKAT") and m.state == "DIG"     # illegal DIG->MEERKAT: state unchanged
    assert "illegal" in m.last_reason
    m.safe_stop()
    assert m.state == "BRAKED_HOLD"                             # SF-01 drop from any state


def test_unknown_posture_rejected():
    with pytest.raises(ValueError):
        PM.PostureMachine("FLYING")
    with pytest.raises(ValueError):
        PM.legal_transitions("FLYING")
    assert PM.can_transition("TRANSIT", "FLYING")[0] is False
