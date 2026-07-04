"""[REQ:MP-11] The reconciliation step: prediction vs observation -> plan deviation -> world-update +
model-update proposals that feed the EG-08 reconciliation lifecycle (PRD §29.7 / §30).

After an executed plan, the planner's PREDICTED outcome is reconciled against the EXECUTION's OBSERVED outcome
for a real quantity (mass moved, energy, rover sinkage, pose, ...). The residual ``observed - predicted`` is
diagnosed against the sensor's known measurement-error envelope (``sensor_tolerance``, in the quantity's
units):

  * ANY nonzero residual yields a WORLD-UPDATE proposal -- the observation is fresh ground truth, so the world
    model's belief is proposed to move to the observed value.
  * A residual BEYOND the sensor tolerance implicates the predictive MODEL (the surprise is larger than
    measurement noise can explain), so a second MODEL-UPDATE proposal is emitted flagged ``model_error``.
  * A residual WITHIN the sensor tolerance is flagged ``sensor_error`` (plausibly measurement noise) and does
    NOT implicate the model -- only the world belief is proposed to update.

Each emitted proposal is a :class:`stewie.contracts.reconciliation.Proposal` already walked
``OBSERVED -> COMPARED -> PROPOSED`` via :func:`~stewie.contracts.reconciliation.advance`; downstream the EG-08
lifecycle reviews / accepts / rejects / applies it (a rejected proposal never mutates accepted truth). This is
the MP-11 producer that feeds the EG-08 state machine.
"""
from __future__ import annotations

from dataclasses import dataclass

from stewie.contracts.reconciliation import Proposal, ReconcileState, advance


class ReconcileStepError(ValueError):
    """Raised on an invalid reconciliation input (e.g. a negative sensor tolerance)."""


@dataclass(frozen=True)
class PredictionResidual:
    """The predicted-vs-observed diff for one quantity + its diagnosis against the sensor envelope."""
    quantity: str
    predicted: float
    observed: float
    residual: float               # observed - predicted (signed)
    abs_residual: float
    sensor_tolerance: float
    implicates_model: bool        # |residual| > sensor_tolerance -> beyond measurement noise
    confidence: float             # in [0, 1); ~1 when the residual dwarfs the sensor envelope, 0 when residual=0


@dataclass(frozen=True)
class ReconcileStep:
    """The output of one reconciliation step: the residual + the emitted proposal(s). ``world_proposal`` is
    present whenever there is anything to reconcile (a nonzero residual); ``model_proposal`` is present only
    when the residual implicates the model."""
    residual: PredictionResidual
    world_proposal: Proposal | None
    model_proposal: Proposal | None

    @property
    def proposals(self) -> tuple[Proposal, ...]:
        """The emitted proposals in emission order (world first, then model when present)."""
        return tuple(p for p in (self.world_proposal, self.model_proposal) if p is not None)


def _proposed(proposal_id: str, *, confidence: float, model_error: bool, sensor_error: bool,
              change: str, provenance: str) -> Proposal:
    """Mint a proposal at OBSERVED and walk it OBSERVED -> COMPARED -> PROPOSED (composing ``advance``)."""
    p = Proposal(proposal_id=proposal_id, state=ReconcileState.OBSERVED, confidence=confidence,
                 model_error=model_error, sensor_error=sensor_error, provenance=provenance, change=change)
    return advance(advance(p, ReconcileState.COMPARED), ReconcileState.PROPOSED)


def reconcile_prediction(predicted: float, observed: float, *, quantity: str = "outcome",
                         sensor_tolerance: float = 0.0, provenance: str = "",
                         proposal_stem: str = "reconcile") -> ReconcileStep:
    """Reconcile a plan's PREDICTED outcome against the EXECUTION's OBSERVED outcome for one quantity.

    The residual ``observed - predicted`` is diagnosed against ``sensor_tolerance`` (the sensor's known
    measurement-error envelope, in the quantity's units): a residual beyond it implicates the predictive
    MODEL, one within it is treated as (possible) sensor noise. Returns a :class:`ReconcileStep` carrying a
    WORLD-UPDATE proposal (whenever the residual is nonzero) and -- when the model is implicated -- a
    MODEL-UPDATE proposal flagged ``model_error``. Each proposal is already advanced to ``PROPOSED`` and flows
    on through the EG-08 lifecycle. Raises :class:`ReconcileStepError` on a negative tolerance.
    """
    if sensor_tolerance < 0:
        raise ReconcileStepError(f"sensor_tolerance must be non-negative (got {sensor_tolerance})")
    residual = observed - predicted
    abs_residual = abs(residual)
    implicates_model = abs_residual > sensor_tolerance
    confidence = 0.0 if abs_residual == 0.0 else abs_residual / (abs_residual + sensor_tolerance)
    diag = PredictionResidual(quantity=quantity, predicted=predicted, observed=observed, residual=residual,
                              abs_residual=abs_residual, sensor_tolerance=sensor_tolerance,
                              implicates_model=implicates_model, confidence=confidence)

    if abs_residual == 0.0:                       # a perfect prediction -- nothing to reconcile
        return ReconcileStep(residual=diag, world_proposal=None, model_proposal=None)

    world = _proposed(
        f"{proposal_stem}:world:{quantity}", confidence=confidence,
        model_error=implicates_model, sensor_error=not implicates_model,
        change=f"set world belief {quantity} = {observed!r} (predicted {predicted!r}, residual {residual!r})",
        provenance=provenance)

    model: Proposal | None = None
    if implicates_model:
        model = _proposed(
            f"{proposal_stem}:model:{quantity}", confidence=confidence, model_error=True, sensor_error=False,
            change=(f"recalibrate model for {quantity}: predicted {predicted!r} vs observed {observed!r} "
                    f"(residual {residual!r} exceeds sensor tolerance {sensor_tolerance!r})"),
            provenance=provenance)
    return ReconcileStep(residual=diag, world_proposal=world, model_proposal=model)
