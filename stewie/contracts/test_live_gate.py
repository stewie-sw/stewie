"""[REQ:EG-05] The training-to-live gate: a live-execution token is refused until all 8-step preconditions
hold, the command bridge rejects a missing/mismatched/forged/EXPIRED token, and LIVE mode authority (EG-02)
alone is not sufficient.

[dispatch-audit R3] A live-execution token is now EXPIRING (issued_at + ttl_s; the command bridge refuses it
past its deadline) and its signature is a KEYED HMAC over (mission_id, revision_id, issued_at, ttl_s), so a
token cannot be forged and its expiry cannot be extended without the server secret. The caller supplies the
clock (no wall-clock inside the pure contract), mirroring the SF-01 SafingWatchdog.
"""
import dataclasses

import pytest

from stewie.contracts.live_gate import (
    LiveExecutionRefused,
    LivePreconditions,
    issue_live_token,
    require_live_token,
)

_ALL_MET = LivePreconditions(True, True, True, True, True, True)
_STEPS = [f.name for f in dataclasses.fields(LivePreconditions)]


def test_eg05_token_refused_when_any_step_missing():  # [REQ:EG-05]
    assert len(_STEPS) == 6
    for missing in _STEPS:
        pc = LivePreconditions(**{s: (s != missing) for s in _STEPS})     # all but one
        with pytest.raises(LiveExecutionRefused):
            issue_live_token("m1", "r1", pc, now=1000.0)


def test_eg05_token_issued_and_valid_when_all_met():  # [REQ:EG-05]
    t = issue_live_token("m1", "r1", _ALL_MET, now=1000.0)
    assert (t.mission_id, t.revision_id) == ("m1", "r1") and t.signature
    assert t.issued_at == 1000.0 and t.ttl_s > 0.0
    require_live_token(t, "m1", "r1", now=1000.5)                          # valid, within ttl -> no raise


def test_eg05_bridge_rejects_missing_or_mismatched_or_forged_token():  # [REQ:EG-05]
    t = issue_live_token("m1", "r1", _ALL_MET, now=1000.0)
    with pytest.raises(LiveExecutionRefused):
        require_live_token(None, "m1", "r1", now=1000.0)                   # step 8: no token
    with pytest.raises(LiveExecutionRefused):
        require_live_token(t, "m2", "r1", now=1000.0)                      # retargeted mission
    with pytest.raises(LiveExecutionRefused):
        require_live_token(t, "m1", "r2", now=1000.0)                      # retargeted revision (content_hash)
    forged = dataclasses.replace(t, signature="deadbeef")
    with pytest.raises(LiveExecutionRefused):
        require_live_token(forged, "m1", "r1", now=1000.0)                 # forged signature


def test_eg05_token_expires_after_its_ttl():  # [REQ:EG-05] [dispatch-audit R3]
    t = issue_live_token("m1", "r1", _ALL_MET, now=1000.0, ttl_s=30.0)
    require_live_token(t, "m1", "r1", now=1000.0 + 29.9)                   # just inside -> ok
    require_live_token(t, "m1", "r1", now=1000.0 + 30.0)                   # exactly at deadline -> still ok
    with pytest.raises(LiveExecutionRefused):
        require_live_token(t, "m1", "r1", now=1000.0 + 30.01)              # past ttl -> refused


def test_eg05_expiry_cannot_be_extended_without_the_secret():  # [REQ:EG-05] [dispatch-audit R3]
    """The signature is keyed over issued_at + ttl_s, so rewriting the token to a longer ttl (or a later
    issued_at) invalidates it -- a client cannot self-extend a live-command window it was granted."""
    t = issue_live_token("m1", "r1", _ALL_MET, now=1000.0, ttl_s=30.0)
    tampered_ttl = dataclasses.replace(t, ttl_s=1_000_000.0)              # forge a far-future expiry
    with pytest.raises(LiveExecutionRefused):
        require_live_token(tampered_ttl, "m1", "r1", now=1000.0 + 100.0)
    tampered_issued = dataclasses.replace(t, issued_at=2000.0)            # forge a later issue time
    with pytest.raises(LiveExecutionRefused):
        require_live_token(tampered_issued, "m1", "r1", now=2000.0 + 10.0)


def test_eg05_gate_is_separate_from_eg02_mode_authority():  # [REQ:EG-05]
    from stewie.contracts.governance import EnvironmentMode, permits
    assert permits(EnvironmentMode.LIVE, "command_real_robot") is True    # EG-02: LIVE may command...
    with pytest.raises(LiveExecutionRefused):                             # ...but with no sequence -> no token
        issue_live_token("m1", "r1", LivePreconditions(), now=1000.0)
