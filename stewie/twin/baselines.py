"""[GATE6B] The comparators a referee will demand before believing the veto-only claim.

``promotion.baseline_fixed_precedence`` is the DEPLOYED control, and it has one property that makes
it useless as the comparator for the model-bias claim: it never reads the physics channel at all.
A system with no model cannot be harmed by a misspecified model, so beating it under model
misspecification demonstrates nothing. This module supplies the comparators that do read the model.

Four, spanning the design space:

``inverse_variance_fusion``
    Physics as a pseudo-measurement, combined with the observation by inverse-variance weighting.
    This is the textbook thing to do and it is the honest opponent: it USES the model, so a model
    bias ``b`` enters the fused estimate with weight ``sigma_o^2 / (sigma_o^2 + sigma_p^2)``. The
    error therefore grows LINEARLY and without bound in ``b``, which is precisely what the veto-only
    argument claims to avoid. It has no way to decline.

``covariance_intersection``
    The conservative rule valid under unknown correlation (Julier & Uhlmann 1997). Reported here with
    an honest caveat that matters: with a scalar variance per cell, the trace-minimising ``omega`` is
    degenerate -- it puts all weight on the lower-variance source. So trace-optimal CI on this problem
    reduces to "use the observation, ignore the model". It is immune to model bias for the same reason
    fixed precedence is: by declining to use the model at all. Pass an explicit ``omega`` to get a
    genuine blend.

``last_write_wins`` / ``confidence_weighted``
    The two rules actually found in deployed systems. Neither can abstain.

None of the four can abstain. That is not an oversight in their implementation; it is the property
under test.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Fused:
    """A combined estimate and its resulting 1-sigma, per cell [m]."""

    values: np.ndarray
    sigma_m: np.ndarray

    @property
    def rms_sigma_m(self) -> float:
        return float(np.sqrt(np.mean(np.asarray(self.sigma_m, dtype=float) ** 2)))


def inverse_variance_fusion(observation: np.ndarray, sigma_o: float,
                            prediction: np.ndarray, sigma_p: float) -> Fused:
    """Treat the physical prediction as a pseudo-measurement and fuse by inverse variance.

    The weight on the prediction is ``sigma_o^2 / (sigma_o^2 + sigma_p^2)``, so an unmodelled bias in
    ``prediction`` passes into the estimate scaled by exactly that factor. This is the comparator
    against which "a misspecified model cannot cause a harmful acceptance" is a non-trivial claim.
    """
    if not (sigma_o > 0.0 and sigma_p > 0.0):
        raise ValueError(f"sigmas must be > 0 (got {sigma_o}, {sigma_p})")
    o = np.asarray(observation, dtype=float)
    p = np.asarray(prediction, dtype=float)
    if o.shape != p.shape:
        raise ValueError(f"shape mismatch: observation {o.shape} vs prediction {p.shape}")
    wo, wp = 1.0 / sigma_o ** 2, 1.0 / sigma_p ** 2
    z = (wo * o + wp * p) / (wo + wp)
    s = np.full(o.shape, 1.0 / np.sqrt(wo + wp))
    return Fused(z, s)


def prediction_weight(sigma_o: float, sigma_p: float) -> float:
    """The share of a prediction bias that ``inverse_variance_fusion`` passes into its estimate.

    Stated separately because it is the analytic prediction the sweep is checked against: accepted
    error under a pure prediction bias ``b`` is ``prediction_weight * b``, exactly.
    """
    if not (sigma_o > 0.0 and sigma_p > 0.0):
        raise ValueError(f"sigmas must be > 0 (got {sigma_o}, {sigma_p})")
    return (1.0 / sigma_p ** 2) / (1.0 / sigma_o ** 2 + 1.0 / sigma_p ** 2)


def covariance_intersection(observation: np.ndarray, sigma_o: float,
                            prediction: np.ndarray, sigma_p: float,
                            omega: float | None = None) -> Fused:
    """Covariance intersection: conservative combination valid under unknown correlation.

    ``omega=None`` selects the trace-minimising weight. For a scalar variance the objective is linear
    in ``omega``, so the optimum sits at an endpoint and all weight goes to the lower-variance source.
    That degeneracy is reported rather than smoothed over: it is why CI, on this problem, buys
    immunity to model bias by refusing to use the model.
    """
    if not (sigma_o > 0.0 and sigma_p > 0.0):
        raise ValueError(f"sigmas must be > 0 (got {sigma_o}, {sigma_p})")
    o = np.asarray(observation, dtype=float)
    p = np.asarray(prediction, dtype=float)
    if o.shape != p.shape:
        raise ValueError(f"shape mismatch: observation {o.shape} vs prediction {p.shape}")
    if omega is None:
        omega = 1.0 if sigma_o <= sigma_p else 0.0     # trace-optimal, degenerate for scalars
    if not (0.0 <= omega <= 1.0):
        raise ValueError(f"omega must be in [0, 1] (got {omega})")
    inv = omega / sigma_o ** 2 + (1.0 - omega) / sigma_p ** 2
    z = (omega / sigma_o ** 2 * o + (1.0 - omega) / sigma_p ** 2 * p) / inv
    return Fused(z, np.full(o.shape, 1.0 / np.sqrt(inv)))


def last_write_wins(prior: np.ndarray, updates: list[tuple[float, np.ndarray]]) -> np.ndarray:
    """Timestamp precedence: the latest update wins outright, whatever its uncertainty."""
    z = np.array(prior, dtype=float, copy=True)
    if not updates:
        return z
    for _, u in sorted(updates, key=lambda t: t[0]):
        z = np.asarray(u, dtype=float).copy()
    return z


def confidence_weighted(observations: list[tuple[np.ndarray, float]]) -> np.ndarray:
    """Reliability-weighted mean of observations. No physical check and no way to decline."""
    if not observations:
        raise ValueError("no observations")
    tot = sum(w for _, w in observations)
    if not (tot > 0.0):
        raise ValueError("weights must sum to > 0")
    acc = np.zeros(np.asarray(observations[0][0], dtype=float).shape, dtype=float)
    for v, w in observations:
        acc += w * np.asarray(v, dtype=float)
    return acc / tot
