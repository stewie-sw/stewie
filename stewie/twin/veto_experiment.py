"""[GATE6B] The two-condition experiment that makes the veto-only claim testable.

The earlier comparison (``test_gate6_promotion_vs_baseline``) had a defect worth stating plainly,
because it is the kind that survives a green suite: its twenty "trials" injected the SAME constant
sensor offset every time and varied only the physics noise, which the fixed-precedence baseline never
reads. The baseline was therefore evaluated twenty times on identical input, and its 20/20 harmful
acceptance was a restatement of its definition rather than a measurement.

This module replaces that with two sweeps in which every trial differs, and in which each system
faces the failure mode it is actually vulnerable to:

**Condition A -- model bias.** Two independent good observations, one physical prediction carrying a
bias ``b``. Sweeping ``b`` separates systems that use the model from systems that do not. Inverse-
variance fusion absorbs ``prediction_weight * b`` and its error grows without bound. Fixed precedence
is flat, but only because it never reads the model. The gate is flat AND reads the model.

**Condition B -- sensor fault.** One faulty observation offset by ``d``, one good prediction.
Sweeping ``d`` separates systems that can decline from systems that cannot. Fixed precedence takes
the fault at full weight; inverse-variance takes ``1 - prediction_weight`` of it; the gate abstains.

The point of running both is that **neither baseline is safe in both conditions**. A system can be
immune to model bias by ignoring the model, or it can exploit the model and inherit its bias. The
claim under test is that vetoing with the model without ever constructing from it gets both.

Terrain is the real Haworth LOLA DEM. The faults are injected under control, which is what a fault
study requires; nothing about the surface is synthesised.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from stewie.twin.baselines import (
    covariance_intersection,
    inverse_variance_fusion,
    prediction_weight,
)
from stewie.twin.promotion import Decision, Evidence, baseline_fixed_precedence, evaluate


@dataclass
class SystemResult:
    """Per-system outcome at one sweep level."""

    system: str
    level_m: float
    n_trials: int
    n_harmful: int = 0
    n_abstained: int = 0
    mean_error_m: float = 0.0
    errors_m: list[float] = field(default_factory=list)

    @property
    def harmful_rate(self) -> float:
        return self.n_harmful / self.n_trials if self.n_trials else 0.0

    @property
    def abstain_rate(self) -> float:
        return self.n_abstained / self.n_trials if self.n_trials else 0.0


def _rms(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.sqrt(np.mean((np.asarray(a, float) - np.asarray(b, float)) ** 2)))


def _noisy(truth: np.ndarray, sigma: float, seed: int) -> np.ndarray:
    return truth + np.random.default_rng(seed).normal(0.0, sigma, truth.shape)


def run_model_bias_sweep(truth: np.ndarray, biases, *, n_trials: int = 20,
                         sigma_o: float = 0.05, sigma_p: float = 0.08,
                         tau_m: float = 0.25, prior_offset_m: float = 0.15,
                         k_sigma: float = 3.0, seed0: int = 1000) -> dict[str, list[SystemResult]]:
    """Condition A. Two good observations, one biased prediction; sweep the bias.

    ``prior_offset_m`` is how stale the standing state is. It is deliberately inside ``tau_m``, so
    abstaining is safe but not free: an abstention keeps a state that is worse than a good
    observation would have been, and that cost shows up in ``mean_error_m``.
    """
    out: dict[str, list[SystemResult]] = {s: [] for s in
                                          ("fixed_precedence", "inverse_variance", "ci_trace_optimal", "gate")}
    for bi, b in enumerate(biases):
        acc = {s: SystemResult(s, float(b), n_trials) for s in out}
        for t in range(n_trials):
            s_a = seed0 + 7919 * bi + 3 * t
            obs_a = _noisy(truth, sigma_o, s_a)
            obs_b = _noisy(truth, sigma_o, s_a + 1)
            phys = _noisy(truth, sigma_p, s_a + 2) + float(b)
            prior = truth + prior_offset_m

            fp = baseline_fixed_precedence(prior, obs_a)
            iv = inverse_variance_fusion(obs_a, sigma_o, phys, sigma_p).values
            ci = covariance_intersection(obs_a, sigma_o, phys, sigma_p).values
            r = evaluate(obs_a, [Evidence("stereo", "observation", obs_a, sigma_o),
                                 Evidence("lidar", "observation", obs_b, sigma_o),
                                 Evidence("terramech", "physics", phys, sigma_p)],
                         prior=prior, k_sigma=k_sigma)
            gate = obs_a if r.decision is Decision.PROMOTE else prior

            for name, est in (("fixed_precedence", fp), ("inverse_variance", iv),
                              ("ci_trace_optimal", ci), ("gate", gate)):
                e = _rms(est, truth)
                acc[name].errors_m.append(e)
                if e > tau_m:
                    acc[name].n_harmful += 1
            if r.decision is Decision.ABSTAIN:
                acc["gate"].n_abstained += 1
        for name, res in acc.items():
            res.mean_error_m = float(np.mean(res.errors_m))
            out[name].append(res)
    return out


def run_sensor_fault_sweep(truth: np.ndarray, offsets, *, n_trials: int = 20,
                           sigma_o: float = 0.05, sigma_p: float = 0.08,
                           tau_m: float = 0.25, prior_offset_m: float = 0.15,
                           k_sigma: float = 3.0, seed0: int = 5000) -> dict[str, list[SystemResult]]:
    """Condition B. One faulty observation, one good prediction; sweep the fault offset.

    Only one observation is offered, so nothing corroborates it. That is the situation in which the
    gate must decline rather than guess, and in which a system that cannot decline must take the
    fault at whatever weight its rule assigns.
    """
    out: dict[str, list[SystemResult]] = {s: [] for s in
                                          ("fixed_precedence", "inverse_variance", "ci_trace_optimal", "gate")}
    for oi, d in enumerate(offsets):
        acc = {s: SystemResult(s, float(d), n_trials) for s in out}
        for t in range(n_trials):
            s_a = seed0 + 6271 * oi + 3 * t
            bad_obs = _noisy(truth, sigma_o, s_a) + float(d)
            phys = _noisy(truth, sigma_p, s_a + 1)
            prior = truth + prior_offset_m

            fp = baseline_fixed_precedence(prior, bad_obs)
            iv = inverse_variance_fusion(bad_obs, sigma_o, phys, sigma_p).values
            ci = covariance_intersection(bad_obs, sigma_o, phys, sigma_p).values
            r = evaluate(bad_obs, [Evidence("stereo", "observation", bad_obs, sigma_o),
                                   Evidence("terramech", "physics", phys, sigma_p)],
                         prior=prior, k_sigma=k_sigma)
            gate = bad_obs if r.decision is Decision.PROMOTE else prior

            for name, est in (("fixed_precedence", fp), ("inverse_variance", iv),
                              ("ci_trace_optimal", ci), ("gate", gate)):
                e = _rms(est, truth)
                acc[name].errors_m.append(e)
                if e > tau_m:
                    acc[name].n_harmful += 1
            if r.decision is Decision.ABSTAIN:
                acc["gate"].n_abstained += 1
        for name, res in acc.items():
            res.mean_error_m = float(np.mean(res.errors_m))
            out[name].append(res)
    return out


def analytic_bias_crossing_m(sigma_o: float, sigma_p: float, tau_m: float) -> float:
    """The bias at which inverse-variance fusion first accepts a harmful state.

    Error under a pure prediction bias ``b`` is ``prediction_weight(sigma_o, sigma_p) * b``, so the
    crossing is ``tau / prediction_weight``. The sweep is checked against this closed form; agreement
    is what shows the sweep is measuring the mechanism and not a seeding artefact.
    """
    return tau_m / prediction_weight(sigma_o, sigma_p)


def analytic_fault_crossing_m(sigma_o: float, sigma_p: float, tau_m: float) -> float:
    """The sensor offset at which inverse-variance fusion first accepts a harmful state.

    The observation enters with weight ``1 - prediction_weight``, so the crossing sits further out
    than fixed precedence's ``tau``: partial trust in the model buys partial protection from a sensor
    fault, and vice versa. Neither buys both.
    """
    return tau_m / (1.0 - prediction_weight(sigma_o, sigma_p))


def detection_band_m(sigma_o: float, sigma_p: float, k_sigma: float) -> float:
    """The smallest observation-versus-prediction discrepancy the gate can resolve.

    A fault below this is inside the combined declared uncertainty and the gate cannot see it. The
    soundness claim therefore carries a side condition that the sketch did not state:

        k * sqrt(sigma_o^2 + sigma_p^2)  <=  tau

    If the detection band exceeds the harm threshold there is a window of faults that are harmful and
    undetectable, and no choice of decision rule inside this evidence set can close it. This was found
    by sweeping, not by inspection, and it belongs in the theorem's assumptions.
    """
    import numpy as _np
    return float(k_sigma * _np.hypot(sigma_o, sigma_p))
