"""[REQ:MP-11] The reconciliation step: an executed plan's PREDICTED-vs-OBSERVED diff yields a world-update
proposal, and -- when the residual exceeds the sensor's measurement-error envelope -- a MODEL-UPDATE proposal
with ``model_error`` flagged; a within-envelope residual is flagged ``sensor_error`` (world-update only); a
perfect prediction yields nothing; and the emitted proposals feed the EG-08 lifecycle (advance/apply).

Predicted vs observed are REAL conserved-backend outputs (no fabricated numbers): the rover's static sinkage
that the physics MP-09 scorer computes for a nominal design payload (predicted) versus for a drum returned
heavier than planned (observed). Both come from ``stewie.contracts.physics_scoring.score_candidate`` on the
conserved tier2_numpy backend + real Moon body constants.
"""
import pytest

from stewie.contracts.physics_scoring import score_candidate
from stewie.contracts.reconciliation import ReconcileState, apply_proposal, ReconcileError, advance
from stewie.contracts.reconciliation_step import ReconcileStepError, reconcile_prediction

S = ReconcileState


def _real_predicted_observed() -> tuple[float, float]:
    """A REAL predicted-vs-observed sinkage pair from the conserved backend: the planner predicted the static
    sinkage for a light (near-empty) drum; execution observed a heavier real drum fill -> larger sinkage."""
    predicted = score_candidate(body="moon", payload_kg=10.0).sinkage_m     # planner's design-payload sinkage
    observed = score_candidate(body="moon", payload_kg=60.0).sinkage_m      # heavier real fill -> larger sinkage
    assert observed > predicted > 0                                          # a real, signed deviation
    return predicted, observed


def test_mp11_deviation_yields_world_update_plus_flagged_model_error():  # [REQ:MP-11]
    predicted, observed = _real_predicted_observed()
    tight_tol = 0.01 * predicted                                             # a tight real sensor envelope
    step = reconcile_prediction(predicted, observed, quantity="rover_sinkage_m",
                                sensor_tolerance=tight_tol, provenance="MP-11 executed-plan reconcile")

    # a world-update proposal AND a model-update proposal, both emitted at PROPOSED
    assert step.world_proposal is not None and step.model_proposal is not None
    assert step.world_proposal.state is S.PROPOSED and step.model_proposal.state is S.PROPOSED
    assert step.proposals == (step.world_proposal, step.model_proposal)

    # the model error is FLAGGED (residual exceeds the sensor envelope -> not measurement noise)
    assert step.residual.implicates_model is True
    assert step.world_proposal.model_error is True and step.model_proposal.model_error is True
    assert step.model_proposal.sensor_error is False
    assert 0.5 < step.world_proposal.confidence < 1.0                        # residual dwarfs the envelope

    # the proposed change carries the real observed value
    assert repr(observed) in step.world_proposal.change


def test_mp11_within_envelope_residual_is_sensor_error_no_model_update():  # [REQ:MP-11]
    predicted, observed = _real_predicted_observed()
    loose_tol = 10.0 * (observed - predicted)                                # a loose sensor: residual is noise
    step = reconcile_prediction(predicted, observed, quantity="rover_sinkage_m", sensor_tolerance=loose_tol)

    assert step.residual.implicates_model is False
    assert step.world_proposal is not None                                   # the world belief still updates
    assert step.world_proposal.sensor_error is True and step.world_proposal.model_error is False
    assert step.model_proposal is None                                       # the model is NOT implicated


def test_mp11_perfect_prediction_yields_nothing_to_reconcile():  # [REQ:MP-11]
    predicted, _ = _real_predicted_observed()
    step = reconcile_prediction(predicted, predicted, quantity="rover_sinkage_m", sensor_tolerance=0.0)
    assert step.residual.abs_residual == 0.0 and step.residual.confidence == 0.0
    assert step.world_proposal is None and step.model_proposal is None
    assert step.proposals == ()


def test_mp11_proposals_feed_the_eg08_lifecycle():  # [REQ:MP-11]
    predicted, observed = _real_predicted_observed()
    step = reconcile_prediction(predicted, observed, quantity="rover_sinkage_m",
                                sensor_tolerance=0.01 * predicted)
    assert step.world_proposal is not None

    # a PROPOSED reconcile proposal flows on through EG-08: reviewed -> accepted -> applied
    reviewed = advance(step.world_proposal, S.REVIEWED)
    accepted = advance(reviewed, S.ACCEPTED)
    assert apply_proposal(accepted).state is S.APPLIED

    # a rejected model proposal can never mutate accepted truth (EG-08 invariant)
    assert step.model_proposal is not None
    rejected = advance(advance(step.model_proposal, S.REVIEWED), S.REJECTED)
    with pytest.raises(ReconcileError):
        apply_proposal(rejected)


def test_mp11_negative_tolerance_is_rejected():  # [REQ:MP-11]
    with pytest.raises(ReconcileStepError):
        reconcile_prediction(1.0, 2.0, sensor_tolerance=-0.1)
