"""[REQ:MP-10] Rehearsal: a candidate plan -> conserved-physics prediction -> predicted outcome + risk
score, on SIMULATION branches in REHEARSAL/DEV/TRAINING mode, WITHOUT touching live/accepted truth
(mode-gated per EG-02)."""
import pytest

from stewie.contracts.governance import EnvironmentMode, ModeAuthorityError, permits
from stewie.contracts.planning_model import RehearsalResult
from stewie.contracts.rehearsal import RehearsalCandidate, rehearse

_FEASIBLE = RehearsalCandidate(candidate_id="cand-feasible", payload_kg=10.0)
_INFEASIBLE = RehearsalCandidate(candidate_id="cand-overload", payload_kg=100000.0)


def test_mp10_rehearsal_yields_predicted_outcome_and_risk_score():  # [REQ:MP-10]
    r = rehearse(_FEASIBLE, mode=EnvironmentMode.REHEARSAL)
    assert isinstance(r, RehearsalResult)
    assert r.candidate_id == "cand-feasible"
    assert r.predicted_outcome                       # a real predicted outcome, not empty
    assert 0.0 <= r.risk_score <= 1.0                # a real risk score
    assert r.mode == "rehearsal"


def test_mp10_rehearsal_does_not_touch_accepted_world_mode_gated():  # [REQ:MP-10]
    # the rehearsal runs in a mode that PROVABLY cannot modify accepted truth (EG-02 / §29.1 matrix) ...
    assert permits(EnvironmentMode.REHEARSAL, "simulate") is True
    assert permits(EnvironmentMode.REHEARSAL, "modify_accepted_world") is False
    # ... and a RehearsalResult carries no world-transaction id, so it cannot record an accepted-world write.
    assert "transaction_id" not in RehearsalResult.model_fields
    r = rehearse(_FEASIBLE, mode=EnvironmentMode.REHEARSAL)
    assert not hasattr(r, "transaction_id")


def test_mp10_rehearsal_fails_closed_in_live():  # [REQ:MP-10]
    with pytest.raises(ModeAuthorityError):
        rehearse(_FEASIBLE, mode=EnvironmentMode.LIVE)         # live cannot rehearse (simulate=False)


@pytest.mark.parametrize("mode", [EnvironmentMode.DEV, EnvironmentMode.TRAINING, EnvironmentMode.REHEARSAL])
def test_mp10_rehearsal_allowed_in_simulate_modes(mode):  # [REQ:MP-10]
    r = rehearse(_FEASIBLE, mode=mode)
    assert r.mode == mode.value and r.predicted_outcome


@pytest.mark.parametrize("mode", [EnvironmentMode.LIVE, EnvironmentMode.REPLAY, EnvironmentMode.ARCHIVE, None])
def test_mp10_rehearsal_rejected_outside_simulate_modes(mode):  # [REQ:MP-10]
    with pytest.raises(ModeAuthorityError):
        rehearse(_FEASIBLE, mode=mode)                         # LIVE/REPLAY/ARCHIVE/None all fail closed


def test_mp10_rehearsal_is_deterministic():  # [REQ:MP-10]
    a = rehearse(_FEASIBLE, mode=EnvironmentMode.REHEARSAL)
    b = rehearse(_FEASIBLE, mode=EnvironmentMode.REHEARSAL)
    assert a == b                                    # deterministic conserved-physics prediction


def test_mp10_infeasible_candidate_scores_max_risk():  # [REQ:MP-10]
    r = rehearse(_INFEASIBLE, mode=EnvironmentMode.REHEARSAL)
    assert r.risk_score == 1.0                       # bearing exceeded -> maximal predicted risk
    assert "entrapment" in r.predicted_outcome
