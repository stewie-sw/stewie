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


def _result_state(result, prior: np.ndarray) -> np.ndarray:
    """Apply a promoted observation patch to the prior."""
    state = np.array(prior, dtype=float, copy=True)
    if result.decision is not Decision.PROMOTE:
        return state
    if result.accepted_state is None or result.accepted_mask is None:
        raise AssertionError("PROMOTE returned without an accepted observation aggregate")
    state[result.accepted_mask] = result.accepted_state[result.accepted_mask]
    return state


def _noisy(truth: np.ndarray, sigma: float, seed: int) -> np.ndarray:
    return truth + np.random.default_rng(seed).normal(0.0, sigma, truth.shape)


def run_model_bias_sweep(truth: np.ndarray, biases, *, n_trials: int = 20,
                         sigma_o: float = 0.05, sigma_p: float = 0.08,
                         tau_m: float = 0.25, prior_offset_m: float = 0.15,
                         k_sigma: float | None = 3.0,
                         seed0: int = 1000) -> dict[str, list[SystemResult]]:
    """Condition A. Two good observations, one biased prediction; sweep the bias.

    ``k_sigma`` is the legacy controlled effect-size multiplier. Passing
    ``None`` exercises the chi-square/Bonferroni production calibration.
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
            r = evaluate(
                [
                    Evidence("stereo", "observation", obs_a, sigma_o),
                    Evidence("lidar", "observation", obs_b, sigma_o),
                    Evidence("terramech", "physics", phys, sigma_p),
                ],
                prior=prior,
                correlation_mask=np.zeros(truth.shape, dtype=bool),
                effect_size_multiplier=k_sigma,
            )
            gate = _result_state(r, prior)

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
                           k_sigma: float | None = 3.0,
                           seed0: int = 5000) -> dict[str, list[SystemResult]]:
    """Condition B. One faulty observation, one good prediction; sweep the fault offset.

    ``k_sigma`` is the legacy controlled effect-size multiplier. Passing
    ``None`` exercises the chi-square/Bonferroni production calibration.
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
            r = evaluate(
                [
                    Evidence("stereo", "observation", bad_obs, sigma_o),
                    Evidence("terramech", "physics", phys, sigma_p),
                ],
                prior=prior,
                effect_size_multiplier=k_sigma,
            )
            gate = _result_state(r, prior)

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
    """Bias-only crossing for inverse-variance fusion.

    In the noiseless scalar or spatially uniform case, prediction bias enters
    as ``prediction_weight(sigma_o, sigma_p) * b``, so the crossing is
    ``tau / prediction_weight``. With realised random errors this is a
    reference effect-size crossing, not an exact first harmful sample.
    """
    return tau_m / prediction_weight(sigma_o, sigma_p)


def analytic_fault_crossing_m(sigma_o: float, sigma_p: float, tau_m: float) -> float:
    """Bias-only sensor-offset crossing for inverse-variance fusion.

    The observation enters with weight ``1 - prediction_weight``, so the crossing sits further out
    than fixed precedence's ``tau``: partial trust in the model buys partial protection from a sensor
    fault, and vice versa. Neither buys both. With realised random errors this
    is not an exact first harmful sample.
    """
    return tau_m / (1.0 - prediction_weight(sigma_o, sigma_p))


def detection_band_m(sigma_o: float, sigma_p: float, k_sigma: float) -> float:
    """Legacy effect-size band for one observation-versus-model comparison.

    This is ``k`` times the pointwise standard deviation of the difference of
    two independent, homoscedastic fields. It is not a false-alarm probability
    for an RMS statistic. It is retained for controlled effect-size sweeps; the
    production gate uses a chi-square-calibrated multiplier.

    The band is also not an assumption of the model-bias theorem. A physics
    prediction may veto but cannot enter the observation-only accepted value,
    so arbitrary model bias is removed structurally rather than detected.
    """
    import numpy as _np
    return float(k_sigma * _np.hypot(sigma_o, sigma_p))


def run_miscalibration_sweep(truth: np.ndarray, kappas, *, n_trials: int = 20,
                             sigma_declared: float = 0.05, sigma_p: float = 0.08,
                             tau_m: float = 0.25, prior_offset_m: float = 0.15,
                             k_sigma: float = 2.0, seed0: int = 9000) -> dict[str, list[SystemResult]]:
    """[F3] Condition C. Sensors DECLARE ``sigma_declared`` but actually err at ``kappa`` times it.

    This is the assumption doing the most work across the whole programme and the one every earlier
    result assumed away: the sweeps to date set declared sigma equal to true sigma by construction.
    Because the soundness claim is stated *over* calibrated sensors, an uncalibrated regime does not
    degrade it gracefully -- it voids the hypothesis. So the question is not whether the bound still
    holds (it is not claimed to) but what the rule actually *does* when a source lies about its own
    precision, and whether it fails safe or fails silently.

    ``kappa > 1`` is the dangerous direction: an over-confident sensor, reporting tighter error bars
    than it earns. ``kappa < 1`` is a merely conservative one.

    Every tolerance inside the rule is built from the DECLARED sigma, while the error that determines
    harm is governed by the TRUE sigma. Two thresholds therefore separate, and the gap between them
    is what this sweep measures.
    """
    out: dict[str, list[SystemResult]] = {s: [] for s in
                                          ("fixed_precedence", "inverse_variance", "gate")}
    for ki, kap in enumerate(kappas):
        sigma_true = float(kap) * sigma_declared
        acc = {s: SystemResult(s, float(kap), n_trials) for s in out}
        for t in range(n_trials):
            s_a = seed0 + 5449 * ki + 3 * t
            # errors at the TRUE scale; the rule is only ever told sigma_declared
            obs_a = _noisy(truth, sigma_true, s_a)
            obs_b = _noisy(truth, sigma_true, s_a + 1)
            phys = _noisy(truth, sigma_p, s_a + 2)
            prior = truth + prior_offset_m

            fp = baseline_fixed_precedence(prior, obs_a)
            iv = inverse_variance_fusion(obs_a, sigma_declared, phys, sigma_p).values
            r = evaluate(
                [
                    Evidence("stereo", "observation", obs_a, sigma_declared),
                    Evidence("lidar", "observation", obs_b, sigma_declared),
                    Evidence("terramech", "physics", phys, sigma_p),
                ],
                prior=prior,
                correlation_mask=np.zeros(truth.shape, dtype=bool),
                effect_size_multiplier=k_sigma,
            )
            gate = _result_state(r, prior)

            for name, est in (("fixed_precedence", fp), ("inverse_variance", iv), ("gate", gate)):
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


def run_asymmetric_miscalibration_sweep(truth: np.ndarray, kappas, *, n_trials: int = 20,
                                        sigma_declared: float = 0.05, sigma_p: float = 0.08,
                                        tau_m: float = 0.25, prior_offset_m: float = 0.15,
                                        k_sigma: float = 2.0, seed0: int = 11000
                                        ) -> dict[str, list[SystemResult]]:
    """[F3b] One source is mis-calibrated and the other is honest.

    The accepted-state repair changed this experiment materially: neither
    source is selected. The accepted value is their mean. Detection is still
    deferred to the expected-effect crossover
    ``kappa = sqrt(2 k^2 - 1)``, but expected aggregate RMS reaches ``tau`` at
    ``sqrt((2 tau / sigma)^2 - 1)`` rather than at ``tau / sigma``.
    """
    out: dict[str, list[SystemResult]] = {s: [] for s in ("fixed_precedence", "gate")}
    for ki, kap in enumerate(kappas):
        acc = {s: SystemResult(s, float(kap), n_trials) for s in out}
        for t in range(n_trials):
            s_a = seed0 + 3931 * ki + 3 * t
            obs_a = _noisy(truth, float(kap) * sigma_declared, s_a)  # first source: mis-calibrated
            obs_b = _noisy(truth, sigma_declared, s_a + 1)  # second source: honest
            phys = _noisy(truth, sigma_p, s_a + 2)
            prior = truth + prior_offset_m
            fp = baseline_fixed_precedence(prior, obs_a)
            r = evaluate(
                [
                    Evidence("stereo", "observation", obs_a, sigma_declared),
                    Evidence("lidar", "observation", obs_b, sigma_declared),
                    Evidence("terramech", "physics", phys, sigma_p),
                ],
                prior=prior,
                correlation_mask=np.zeros(truth.shape, dtype=bool),
                effect_size_multiplier=k_sigma,
            )
            gate = _result_state(r, prior)
            for name, est in (("fixed_precedence", fp), ("gate", gate)):
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


def miscalibration_thresholds(sigma_declared: float, tau_m: float, k_sigma: float) -> dict[str, float]:
    """Asymptotic effect-size crossovers after the accepted-state repair.

    The rule now accepts the mean of two observations.

    * Symmetric true scale ``kappa*sigma``: disagreement is detected near
      ``kappa = k``, while aggregate RMS reaches harm near
      ``kappa = sqrt(2)*tau/sigma``.
    * One bad and one honest source: disagreement is detected near
      ``sqrt(2*k^2-1)`` and aggregate RMS reaches harm near
      ``sqrt((2*tau/sigma)^2-1)``.

    These are large-``n`` root-expected-MSE crossovers for an explicit
    effect-size multiplier, not ``E[RMS]``, deterministic onsets, or
    false-alarm probabilities. Calling them overconfidence ``onsets`` assumes
    ``k >= 1`` and ``tau > sigma/sqrt(2)``: the honest point ``kappa=1`` then
    lies before both crossings. If the latter condition fails, the honest
    two-source mean already exceeds ``tau`` in root expected MSE and there is
    no positive miscalibration margin to protect.
    """
    if sigma_declared <= 0 or tau_m <= 0:
        raise ValueError("sigma_declared and tau_m must be > 0")
    if k_sigma < 1.0:
        raise ValueError(
            "k_sigma must be >= 1 for an overconfidence crossover"
        )
    detect_sym = k_sigma
    detect_asym = float(np.sqrt(2.0 * k_sigma ** 2 - 1.0))
    harm_sym = float(np.sqrt(2.0) * tau_m / sigma_declared)
    harm_asym = float(
        np.sqrt(max(0.0, (2.0 * tau_m / sigma_declared) ** 2 - 1.0))
    )
    ordered_sym = detect_sym < harm_sym
    ordered_asym = detect_asym < harm_asym
    honest_expected_safe = sigma_declared / np.sqrt(2.0) < tau_m
    crossings_in_overconfidence_regime = (
        k_sigma >= 1.0 and honest_expected_safe
    )
    return {"detect_symmetric": detect_sym,
            "detect_asymmetric": detect_asym,
            "harm_symmetric": harm_sym,
            "harm_asymmetric": harm_asym,
            "honest_expected_safe": float(honest_expected_safe),
            "crossings_in_overconfidence_regime": float(
                crossings_in_overconfidence_regime
            ),
            "expected_order_symmetric": float(ordered_sym),
            "expected_order_asymmetric": float(ordered_asym),
            "expected_order_both": float(ordered_sym and ordered_asym),
            "margin_symmetric": harm_sym / detect_sym,
            "margin_asymmetric": harm_asym / detect_asym,
            "margin": min(harm_sym / detect_sym, harm_asym / detect_asym)}


def run_shared_ground_sweep(truth: np.ndarray, overlaps, *, m_agents: int = 3,
                            shared_error_m: float = 0.6, n_trials: int = 20,
                            sigma_o: float = 0.05, sigma_p: float = 0.08,
                            tau_m: float = 0.25, prior_offset_m: float = 0.15,
                            k_sigma: float = 2.0, min_support: float = 2.0,
                            physics_sees_truth: bool = False,
                            seed0: int = 13000) -> dict[str, list[SystemResult]]:
    """[F4] The experiment the whole thesis reduces to.

    On cells marked by the action-derived dependency graph, this controlled
    fault injection adds the same observation error to every agent. Shared
    action is provenance evidence for possible dependence; it is not itself a
    stochastic mechanism that makes otherwise independent sensor noise
    correlated.

    That is what ``m_eff`` is for, and this sweep is where it either earns its place or does not.

    Three support models are compared on identical evidence:
      ``none``    no dependency correction; agreement is taken at face value
      ``linear``  the superseded discount
      ``c3``      the conservative bound

    ``shared_error_m`` is the fixed magnitude of the common observation error
    on shared ground. Its sign alternates by trial. Independent sensor noise is
    sampled on real Haworth terrain.
    """
    models = ("none", "linear", "c3")
    out: dict[str, list[SystemResult]] = {s: [] for s in models}
    n = truth.size
    for di, d in enumerate(overlaps):
        acc = {s: SystemResult(s, float(d), n_trials) for s in models}
        n_shared = int(round(float(d) * n))
        mask = np.zeros(truth.shape, dtype=bool)
        if n_shared:
            mask.ravel()[:n_shared] = True
        for t in range(n_trials):
            rng = np.random.default_rng(seed0 + 7717 * di + t)
            # Controlled common-mode observation fault: fixed magnitude and
            # alternating sign, applied to every agent on the shared cells.
            common = np.zeros(truth.shape, dtype=float)
            common[mask] = shared_error_m if t % 2 == 0 else -shared_error_m
            obs = [truth + common + rng.normal(0.0, sigma_o, truth.shape)
                   for _ in range(m_agents)]
            # Two defensible models of the physics channel, and they are NOT equivalent.
            # physics_sees_truth=False: the common error is something the model shares, so it agrees
            #   with the biased sensors and the physics branch is blind. Isolates the support test.
            # physics_sees_truth=True: the common error is a SENSING artefact -- every sensor mis-sees
            #   the disturbed surface the same way -- so the model predicts the true surface and
            #   disagrees with all of them. This is the physically apt reading for G-A, since the
            #   mechanism is dependence among OBSERVATION errors, and it is the harder case.
            phys = (truth + rng.normal(0.0, sigma_p, truth.shape) if physics_sees_truth
                    else truth + common + rng.normal(0.0, sigma_p, truth.shape))
            prior = truth + prior_offset_m
            ev = [Evidence(f"agent{i}", "observation", o, sigma_o) for i, o in enumerate(obs)]
            ev.append(Evidence("terramech", "physics", phys, sigma_p))
            for sm in models:
                r = evaluate(
                    ev,
                    prior=prior,
                    correlation_mask=mask,
                    effect_size_multiplier=k_sigma,
                    min_effective_support=min_support,
                    support_model=sm,
                )
                est = _result_state(r, prior)
                e = _rms(est, truth)
                acc[sm].errors_m.append(e)
                if e > tau_m:
                    acc[sm].n_harmful += 1
                if r.decision is Decision.ABSTAIN:
                    acc[sm].n_abstained += 1
        for sm, res in acc.items():
            res.mean_error_m = float(np.mean(res.errors_m))
            out[sm].append(res)
    return out


def shared_ground_expected_mse_crossover(
    m_agents: int,
    sigma_o: float,
    tau_m: float,
    shared_error_m: float,
) -> float:
    """Fraction where the observation mean's *expected* MSE equals ``tau^2``.

    With a deterministic common shift ``S`` on fraction ``d`` and independent
    per-source noise ``sigma_o``, the plain mean has

        E[RMS^2] = d S^2 + sigma_o^2 / m.

    This is an expectation crossover, not a sharp harm onset. Realised RMS is
    random on both sides.
    """
    if m_agents < 1:
        raise ValueError(f"m_agents must be >= 1 (got {m_agents})")
    if not (sigma_o > 0.0 and tau_m > 0.0 and shared_error_m > 0.0):
        raise ValueError("sigma_o, tau_m, and shared_error_m must be > 0")
    noise_mse = sigma_o**2 / m_agents
    return max(0.0, (tau_m**2 - noise_mse) / shared_error_m**2)


def shared_ground_harm_probability(
    n_cells: int,
    m_agents: int,
    sigma_o: float,
    tau_m: float,
    shared_error_m: float,
    correlated_fraction: float,
) -> float:
    """Exact harmful-RMS probability for the deterministic common-shift model.

    If ``n_shared`` cells carry fixed shift ``S`` and the accepted value is the
    mean of ``m`` observations with independent Gaussian noise, then

        n RMS^2 / (sigma_o^2 / m)
            ~ noncentral-chi-square(n, n_shared S^2 / (sigma_o^2 / m)).

    Spatial independence of the sensor-noise field is required. A random common
    Gaussian amplitude instead gives a weighted chi-square law.
    """
    if n_cells < 1 or m_agents < 1:
        raise ValueError("n_cells and m_agents must be >= 1")
    if not (sigma_o > 0.0 and tau_m > 0.0 and shared_error_m >= 0.0):
        raise ValueError("sigma_o and tau_m must be > 0; shared_error_m must be >= 0")
    d = float(correlated_fraction)
    if not 0.0 <= d <= 1.0:
        raise ValueError("correlated_fraction must be in [0, 1]")
    from scipy.stats import ncx2

    n_shared = int(round(d * n_cells))
    aggregate_variance = sigma_o**2 / m_agents
    noncentrality = n_shared * shared_error_m**2 / aggregate_variance
    threshold = n_cells * tau_m**2 / aggregate_variance
    return float(ncx2.sf(threshold, n_cells, noncentrality))


def support_threshold_sensitivity(
    m_agents: int,
    sigma_o: float,
    tau_m: float,
    assumed_shared_error_bound_m: float,
) -> float:
    """Offline sensitivity threshold under an explicit common-error bound.

    This maps the expected-MSE crossover to the legacy global-mask support
    scalar. It is not deployable unless
    ``assumed_shared_error_bound_m`` is independently justified. Without a
    finite bound, an independent reference, or a richer error model, no
    observation-only system can infer the common error from mutually agreeing
    readings; worst-case safety requires abstaining on every nonempty
    dependency component.
    """
    d = shared_ground_expected_mse_crossover(
        m_agents,
        sigma_o,
        tau_m,
        assumed_shared_error_bound_m,
    )
    if tau_m**2 <= sigma_o**2 / m_agents:
        raise ValueError(
            "the independent observation mean already reaches the harm "
            "threshold in expected MSE; no support cutoff can repair it"
        )
    d = min(1.0, d)
    return m_agents / (1.0 + d * (m_agents - 1))


def run_stale_evidence_sweep(truth_old: np.ndarray, truth_new: np.ndarray, dug_mask: np.ndarray,
                             *, n_trials: int = 20, sigma_o: float = 0.05, sigma_p: float = 0.08,
                             tau_m: float = 0.25, k_sigma: float = 2.0, min_support: float = 1.0,
                             with_fresh: bool = True, temporal: bool = False, seed0: int = 17000
                             ) -> dict[str, list[SystemResult]]:
    """[F5] Evidence that describes a surface which no longer exists.

    An observation made before an action and arriving after it is not wrong
    about anything -- it is a correct description of a surface that has since
    been dug away. The experiment contrasts ``temporal=False``, where the gate
    is deliberately not told the intervening modification time, with
    ``temporal=True``, where ``Evidence.observed_at`` permits stale filtering.

    Two situations, and they fail differently:

    ``with_fresh=True``   a stale reading arrives alongside a current one. They disagree, because the
        ground changed between them, so the corroboration branch fires and the rule ABSTAINS. Safe
        and wrong: the disagreement is not genuine ambiguity, and the current reading is right. The
        cost is availability.

    ``with_fresh=False``  the stale reading arrives alone. Nothing contradicts it, so it is accepted
        and the state reverts to a surface that no longer exists. The cost is harm.

    Both are scored against ``truth_new``, the surface that actually exists. ``dug_mask`` marks the
    cells the intervening action changed.
    """
    out: dict[str, list[SystemResult]] = {"gate": []}
    acc = {"gate": SystemResult("gate", 0.0, n_trials)}
    for t in range(n_trials):
        rng = np.random.default_rng(seed0 + 5 * t)
        stale = truth_old + rng.normal(0.0, sigma_o, truth_old.shape)
        fresh = truth_new + rng.normal(0.0, sigma_o, truth_new.shape)
        phys = truth_new + rng.normal(0.0, sigma_p, truth_new.shape)
        prior = truth_new.copy()          # the standing state is already correct
        # times: the dig happens at t=5; the stale reading predates it, the fresh one follows it
        ev = [Evidence("stale", "observation", stale, sigma_o, observed_at=1.0)]
        if with_fresh:
            ev.append(Evidence("fresh", "observation", fresh, sigma_o, observed_at=9.0))
        ev.append(Evidence("terramech", "physics", phys, sigma_p, observed_at=9.0))
        r = evaluate(
            ev,
            prior=prior,
            correlation_mask=np.zeros(truth_new.shape, dtype=bool),
            effect_size_multiplier=k_sigma,
            min_effective_support=min_support,
            last_modified_at=(5.0 if temporal else None),
        )
        est = _result_state(r, prior)
        e = _rms(est, truth_new)
        acc["gate"].errors_m.append(e)
        if e > tau_m:
            acc["gate"].n_harmful += 1
        if r.decision is Decision.ABSTAIN:
            acc["gate"].n_abstained += 1
    for s, res in acc.items():
        res.mean_error_m = float(np.mean(res.errors_m))
        out[s].append(res)
    return out


def run_action_log_fidelity_sweep(truth: np.ndarray, fidelities, *, d_true: float = 0.40,
                                  m_agents: int = 3, shared_error_m: float = 0.6,
                                  n_trials: int = 20, sigma_o: float = 0.05, sigma_p: float = 0.08,
                                  tau_m: float = 0.25, prior_offset_m: float = 0.15,
                                  k_sigma: float = 2.0, min_support: float = 2.25,
                                  shuffle: bool = False, seed0: int = 19000
                                  ) -> dict[str, list[SystemResult]]:
    """[F6] The action log is wrong, and everything downstream is built on it.

    ``m_eff`` is derived from the record of what the machines did. If that record is inaccurate the
    derivation inherits the inaccuracy. **Under-reporting** is the direction this sweep varies: a log
    claiming less shared ground than there was makes the rule believe the readings are more
    independent than they are, which is the optimistic error this whole design exists to prevent.

    [CORRECTION 2026-07-28] This docstring previously called under-reporting "the dangerous
    direction". That was a scoping assumption, never tested against the other direction, and it is
    wrong on sensitivity. Over-reporting is roughly four times more sensitive here --- tolerated to
    10% against 50% --- and its failure is total loss of availability, which
    ``test_a7_repair_choice`` already measured to be the worst outcome on a worked site. Both cliffs
    sit at the same closed-form constant; see ``effective_support.log_error_tolerance`` and
    ``run_action_log_overreporting_sweep``.

    ``fidelity`` is the share of genuinely shared cells the log actually records. 1.0 is an accurate
    log; 0.0 claims no shared ground at all, at which point the rule behaves like the no-correction
    ablation. The common error is always applied to the TRUE shared region, so the terrain does not
    care what the log says.

    ``shuffle=True`` is the stronger control and tests the premise rather than the implementation.
    The reported region keeps the correct SIZE but is moved to the wrong cells, so ``m_eff`` is
    numerically right and attached to nothing real. If harmful acceptance is unchanged by that, the
    action history was never load-bearing and the central claim is in trouble.
    """
    out: dict[str, list[SystemResult]] = {"gate": []}
    n = truth.size
    n_true = int(round(d_true * n))
    true_mask = np.zeros(truth.shape, dtype=bool)
    true_mask.ravel()[:n_true] = True
    for fi, fid in enumerate(fidelities):
        acc = {"gate": SystemResult("gate", float(fid), n_trials)}
        n_rep = int(round(float(fid) * n_true))
        for t in range(n_trials):
            rng = np.random.default_rng(seed0 + 4093 * fi + t)
            reported = np.zeros(truth.shape, dtype=bool)
            if shuffle:
                # correct size, wrong cells: drawn from outside the true region where possible
                idx = rng.permutation(n)
                reported.ravel()[idx[:n_rep]] = True
            else:
                reported.ravel()[:n_rep] = True          # a prefix of the true region: under-report
            common = np.zeros(truth.shape, dtype=float)
            common[true_mask] = (
                shared_error_m if t % 2 == 0 else -shared_error_m
            )
            obs = [truth + common + rng.normal(0.0, sigma_o, truth.shape) for _ in range(m_agents)]
            phys = truth + rng.normal(0.0, sigma_p, truth.shape)  # model predicts the true surface
            prior = truth + prior_offset_m
            ev = [Evidence(f"agent{i}", "observation", o, sigma_o) for i, o in enumerate(obs)]
            ev.append(Evidence("terramech", "physics", phys, sigma_p))
            r = evaluate(
                ev,
                prior=prior,
                correlation_mask=reported,
                effect_size_multiplier=k_sigma,
                min_effective_support=min_support,
            )
            est = _result_state(r, prior)
            e = _rms(est, truth)
            acc["gate"].errors_m.append(e)
            if e > tau_m:
                acc["gate"].n_harmful += 1
            if r.decision is Decision.ABSTAIN:
                acc["gate"].n_abstained += 1
        acc["gate"].mean_error_m = float(np.mean(acc["gate"].errors_m))
        out["gate"].append(acc["gate"])
    return out


def run_duplicated_evidence_sweep(truth: np.ndarray, offsets, *, n_trials: int = 20,
                                  sigma_o: float = 0.05, sigma_p: float = 0.08,
                                  tau_m: float = 0.25, prior_offset_m: float = 0.15,
                                  k_sigma: float = 2.0, min_support: float = 2.0,
                                  duplicate: bool = True, seed0: int = 23000
                                  ) -> dict[str, list[SystemResult]]:
    """[F7] One reading presented twice as two sources: the degenerate case of dependency.

    This is where the mechanism's scope shows. ``m_eff`` is derived from the
    declared source graph. Known duplication can be encoded by an edge, but a
    relabelled copy presented as a genuine new identity with no edge
    counterfeits an independent component.

    The two copies then agree perfectly, because they are the same numbers, so corroboration passes
    trivially. Where the physical model disagrees, the duplicated reading overrules it.

    ``duplicate=False`` runs the same faulty reading once, as the control: with a single source there
    is nothing to corroborate and the rule should decline.

    The point of this family is not to add value-based duplicate detection. It
    establishes that source integrity is an upstream theorem assumption: this
    layer cannot discover a hidden common identity from the readings alone.
    """
    out: dict[str, list[SystemResult]] = {"gate": []}
    for oi, d in enumerate(offsets):
        acc = {"gate": SystemResult("gate", float(d), n_trials)}
        for t in range(n_trials):
            rng = np.random.default_rng(seed0 + 3571 * oi + t)
            bad = truth + float(d) + rng.normal(0.0, sigma_o, truth.shape)
            phys = truth + rng.normal(0.0, sigma_p, truth.shape)     # model is correct
            prior = truth + prior_offset_m
            ev = [Evidence("stereo", "observation", bad, sigma_o)]
            if duplicate:
                # same array, different source label: a relabelled copy, not a second look
                ev.append(Evidence("stereo_relay", "observation", bad, sigma_o))
            ev.append(Evidence("terramech", "physics", phys, sigma_p))
            r = evaluate(
                ev,
                prior=prior,
                correlation_mask=np.zeros(truth.shape, dtype=bool),
                effect_size_multiplier=k_sigma,
                min_effective_support=min_support,
            )
            est = _result_state(r, prior)
            e = _rms(est, truth)
            acc["gate"].errors_m.append(e)
            if e > tau_m:
                acc["gate"].n_harmful += 1
            if r.decision is Decision.ABSTAIN:
                acc["gate"].n_abstained += 1
        acc["gate"].mean_error_m = float(np.mean(acc["gate"].errors_m))
        out["gate"].append(acc["gate"])
    return out

def run_no_physics_sweep(truth: np.ndarray,
                         common_error_m: float,
                         *,
                         trials: int = 20,
                         sigma_o: float = 0.05,
                         tau_m: float = 0.25,
                         min_effective_support: float = 2.0,
                         seed: int = 0) -> SystemResult:
    """Measure the regime where the veto is structurally unable to fire.

    The rule's safety argument for the agreeing branch assumes the residual test PASSED. It is also
    reachable when no physical model was offered at all, in which case the test never ran. This
    sweep isolates that regime: two agents worked the same ground and carry the same error, exactly
    the F4 fault, but the physics prediction that would catch it is absent.

    Controlled fault injection on real terrain. ``common_error_m`` is the shared bias both readings
    carry; the terrain is real Haworth LOLA.
    """
    rng = np.random.default_rng(seed)
    harmful = 0
    abstained = 0
    errors: list[float] = []
    for _ in range(trials):
        shared = rng.normal(common_error_m, 0.02 * abs(common_error_m) or 1e-6)
        reading = truth + shared
        ev = [Evidence("agent_a", "observation", reading + rng.normal(0, sigma_o * 0.1, truth.shape),
                       sigma_o, 1.0),
              Evidence("agent_b", "observation", reading + rng.normal(0, sigma_o * 0.1, truth.shape),
                       sigma_o, 1.0)]
        result = evaluate(
            ev,
            correlation_mask=np.zeros(truth.shape, dtype=bool),
            min_effective_support=min_effective_support,
        )
        if result.decision is Decision.PROMOTE:
            if result.accepted_state is None:
                raise RuntimeError("PROMOTE returned without an accepted aggregate")
            err = float(np.sqrt(np.mean((result.accepted_state - truth) ** 2)))
            errors.append(err)
            if err > tau_m:
                harmful += 1
        else:
            abstained += 1
    return SystemResult(system="veto_no_physics", level_m=common_error_m, n_trials=trials,
                        n_harmful=harmful, n_abstained=abstained,
                        mean_error_m=float(np.mean(errors)) if errors else 0.0,
                        errors_m=errors)

def run_action_log_overreporting_sweep(truth: np.ndarray, fp_rates, *, m_agents: int = 3,
                                       n_trials: int = 20, sigma_o: float = 0.05,
                                       sigma_p: float = 0.08, tau_m: float = 0.25,
                                       k_sigma: float = 2.0, min_support: float = 2.25,
                                       seed0: int = 41000) -> dict[str, list[SystemResult]]:
    """[F6b] The action log claims shared ground that was never worked.

    F6 sweeps the log omitting real overlap. This sweeps the opposite error, which the family did
    not cover and which its docstring wrongly dismissed as the safe direction.

    The evidence here is genuinely independent and genuinely good: the agents worked separate
    ground, there is no common error, and every reading is within its declared sigma. **Only the log
    is wrong.** ``fp_rate`` is the share of independent cells it wrongly reports as shared, so any
    abstention is a promotion the rule should have made and did not.

    The failure is availability rather than harm, and that is not the same as harmless: a rule that
    abstains on every promotion leaves a twin that never learns the ground moved, measured elsewhere
    as the worst map error of the available policies on a worked site.
    """
    out: dict[str, list[SystemResult]] = {"gate": []}
    for fi, fp in enumerate(fp_rates):
        acc = SystemResult("gate", float(fp), n_trials)
        for t in range(n_trials):
            rng = np.random.default_rng(seed0 + 7919 * fi + 13 * t)
            obs = [Evidence(f"agent_{i}", "observation",
                            truth + rng.normal(0.0, sigma_o, truth.shape), sigma_o, 1.0)
                   for i in range(m_agents)]
            phys = Evidence("terramech", "physics",
                            truth + rng.normal(0.0, sigma_p, truth.shape), sigma_p, 1.0)
            logged = rng.random(truth.shape) < float(fp)      # pure fabrication
            result = evaluate(
                [*obs, phys],
                correlation_mask=logged,
                effect_size_multiplier=k_sigma,
                min_effective_support=min_support,
            )
            estimate = _result_state(result, truth)
            err = _rms(estimate, truth)
            acc.errors_m.append(err)
            if result.decision is Decision.PROMOTE:
                if err > tau_m:
                    acc.n_harmful += 1
            else:
                acc.n_abstained += 1
        acc.mean_error_m = float(np.mean(acc.errors_m))
        out["gate"].append(acc)
    return out
