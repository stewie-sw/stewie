"""[REQ:EG-05] The training-to-live gate: a live-execution token is refused until all 8-step preconditions
hold, the command bridge rejects a missing/mismatched/forged token, and LIVE mode authority (EG-02) alone is
not sufficient."""
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
            issue_live_token("m1", "r1", pc)


def test_eg05_token_issued_and_valid_when_all_met():  # [REQ:EG-05]
    t = issue_live_token("m1", "r1", _ALL_MET)
    assert (t.mission_id, t.revision_id) == ("m1", "r1") and t.signature
    require_live_token(t, "m1", "r1")                                     # valid -> no raise


def test_eg05_bridge_rejects_missing_or_mismatched_or_forged_token():  # [REQ:EG-05]
    t = issue_live_token("m1", "r1", _ALL_MET)
    with pytest.raises(LiveExecutionRefused):
        require_live_token(None, "m1", "r1")                              # step 8: no token
    with pytest.raises(LiveExecutionRefused):
        require_live_token(t, "m2", "r1")                                 # retargeted mission
    with pytest.raises(LiveExecutionRefused):
        require_live_token(t, "m1", "r2")                                 # retargeted revision
    forged = dataclasses.replace(t, signature="deadbeef")
    with pytest.raises(LiveExecutionRefused):
        require_live_token(forged, "m1", "r1")                            # forged signature


def test_eg05_gate_is_separate_from_eg02_mode_authority():  # [REQ:EG-05]
    from stewie.contracts.governance import EnvironmentMode, permits
    assert permits(EnvironmentMode.LIVE, "command_real_robot") is True    # EG-02: LIVE may command...
    with pytest.raises(LiveExecutionRefused):                             # ...but with no sequence -> no token
        issue_live_token("m1", "r1", LivePreconditions())
