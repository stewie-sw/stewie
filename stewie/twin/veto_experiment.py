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
            r = evaluate(obs_a, [Evidence("stereo", "observation", obs_a, sigma_declared),
                                 Evidence("lidar", "observation", obs_b, sigma_declared),
                                 Evidence("terramech", "physics", phys, sigma_p)],
                         prior=prior, k_sigma=k_sigma)
            gate = obs_a if r.decision is Decision.PROMOTE else prior

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
    """[F3b] Only the ACCEPTED source is mis-calibrated; the corroborating one is honest.

    This is the case the symmetric sweep missed, and it is the harder one. When both sources are
    equally over-confident their disagreement grows as ``kappa`` and the corroboration branch notices
    at ``kappa = k``. When only the candidate is bad, the disagreement grows as
    ``sqrt(kappa^2 + 1)/sqrt(2)`` of the tolerance, so detection is deferred to
    ``kappa = sqrt(2 k^2 - 1)`` while the harm threshold does not move -- the accepted reading is
    precisely the bad one. The safety margin therefore narrows, and for large ``k`` it inverts.
    """
    out: dict[str, list[SystemResult]] = {s: [] for s in ("fixed_precedence", "gate")}
    for ki, kap in enumerate(kappas):
        acc = {s: SystemResult(s, float(kap), n_trials) for s in out}
        for t in range(n_trials):
            s_a = seed0 + 3931 * ki + 3 * t
            obs_a = _noisy(truth, float(kap) * sigma_declared, s_a)   # candidate: mis-calibrated
            obs_b = _noisy(truth, sigma_declared, s_a + 1)            # corroborator: honest
            phys = _noisy(truth, sigma_p, s_a + 2)
            prior = truth + prior_offset_m
            fp = baseline_fixed_precedence(prior, obs_a)
            r = evaluate(obs_a, [Evidence("stereo", "observation", obs_a, sigma_declared),
                                 Evidence("lidar", "observation", obs_b, sigma_declared),
                                 Evidence("terramech", "physics", phys, sigma_p)],
                         prior=prior, k_sigma=k_sigma)
            gate = obs_a if r.decision is Decision.PROMOTE else prior
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
    """Kappa thresholds for mis-calibration, for BOTH the symmetric and asymmetric cases.

    **Corrected 2026-07-27.** An earlier version reported only the symmetric case and gave the
    fail-safe condition as ``k * sigma_declared < tau``. That is incomplete, and certifying safety on
    it is unsound.

    *Symmetric* -- every source equally over-confident. Disagreement grows as ``kappa``, so the
    corroboration branch fires at ``kappa = k``.

    *Asymmetric* -- only the candidate is over-confident and its corroborator is honest. Disagreement
    then grows as ``sqrt(kappa^2 + 1)`` against a tolerance of ``k * sqrt(2)``, so detection is
    deferred to ``kappa = sqrt(2 k^2 - 1)``, which is strictly later. The harm threshold does not
    move, because the reading that gets accepted is precisely the bad one.

    The asymmetric case is therefore the binding one and the honest condition is

        sqrt(2 k^2 - 1) * sigma_declared < tau

    Measured: at ``k=4`` with ``sigma_declared=0.05`` and ``tau=0.25`` the old condition returns safe
    (0.20 < 0.25) while the gate accepts a harmful state in 12 of 20 trials. See
    ``test_miscalibration.py::test_symmetric_condition_alone_certifies_an_unsafe_configuration``.
    """
    if sigma_declared <= 0 or tau_m <= 0 or k_sigma <= 0:
        raise ValueError("sigma_declared, tau_m and k_sigma must all be > 0")
    harm = tau_m / sigma_declared
    detect_sym = k_sigma
    detect_asym = float(np.sqrt(2.0 * k_sigma ** 2 - 1.0))
    return {"detect": detect_sym,
            "detect_symmetric": detect_sym,
            "detect_asymmetric": detect_asym,
            "harm": harm,
            # the binding condition is the later detection, i.e. the asymmetric one
            "fails_safe": float(detect_asym < harm),
            "fails_safe_symmetric_only": float(detect_sym < harm),
            "margin": harm / detect_asym}


def run_shared_ground_sweep(truth: np.ndarray, overlaps, *, m_agents: int = 3,
                            shared_error_m: float = 0.6, n_trials: int = 20,
                            sigma_o: float = 0.05, sigma_p: float = 0.08,
                            tau_m: float = 0.25, prior_offset_m: float = 0.15,
                            k_sigma: float = 2.0, min_support: float = 2.0,
                            physics_sees_truth: bool = False,
                            seed0: int = 13000) -> dict[str, list[SystemResult]]:
    """[F4] The experiment the whole thesis reduces to.

    On cells that several agents have dug, every agent's reading carries the SAME error, because the
    same physical modification produced it. The readings therefore **agree with each other while all
    of them are wrong**. Corroboration cannot detect this -- agreement is exactly what it looks for --
    and neither can a physical-consistency check, since the error is in the terrain rather than in the
    model. The only thing that can catch it is knowing that agreement between action-correlated
    sources is worth less than agreement between independent ones.

    That is what ``m_eff`` is for, and this sweep is where it either earns its place or does not.

    Three support models are compared on identical evidence:
      ``none``    no dependency correction; agreement is taken at face value
      ``linear``  the superseded discount
      ``c3``      the conservative bound

    ``shared_error_m`` is the magnitude of the common error on shared ground. It is injected under
    control and labelled as such; the terrain beneath it is real.
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
            # the common error: one draw, applied to EVERY agent on the shared cells
            common = np.zeros(truth.shape, dtype=float)
            common[mask] = rng.normal(0.0, shared_error_m)
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
                r = evaluate(obs[0], ev, prior=prior, correlation_mask=mask, k_sigma=k_sigma,
                             min_effective_support=min_support, support_model=sm)
                est = obs[0] if r.decision is Decision.PROMOTE else prior
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


def shared_ground_harm_onset(sigma_o: float, tau_m: float, shared_error_m: float) -> float:
    """Overlap fraction at which the accepted state first exceeds ``tau``, derived not fitted.

    RMS error over the region is ``sqrt(d * shared^2 + sigma_o^2)``, so harm begins at
    ``d = (tau^2 - sigma_o^2) / shared^2``.
    """
    if shared_error_m <= 0:
        raise ValueError("shared_error_m must be > 0")
    return max(0.0, (tau_m ** 2 - sigma_o ** 2) / shared_error_m ** 2)


def derived_support_threshold(m_agents: int, sigma_o: float, tau_m: float,
                              shared_error_m: float) -> float:
    """The support threshold implied by the harm threshold, rather than chosen.

    A support threshold picked by hand is a free parameter, and picking it too low leaves a window in
    which the accepted state is already harmful but the support test has not yet fired. Requiring the
    test to fire exactly at the harm onset removes the freedom:

        d_harm = (tau^2 - sigma_o^2) / shared^2          # where the accepted state first exceeds tau
        threshold = m / (1 + d_harm * (m - 1))           # the C3 support at that overlap

    Measured effect at m=3, sigma_o=0.05, tau=0.25, shared=0.6: the hand-picked 2.0 fires only at
    d=0.25 and leaves 31 harmful acceptances across the sweep; the derived 2.25 fires at d=0.167 and
    leaves 5. The bound was never the problem -- the free parameter was.
    """
    if m_agents < 1:
        raise ValueError(f"m_agents must be >= 1 (got {m_agents})")
    d_harm = shared_ground_harm_onset(sigma_o, tau_m, shared_error_m)
    return m_agents / (1.0 + d_harm * (m_agents - 1))


def run_stale_evidence_sweep(truth_old: np.ndarray, truth_new: np.ndarray, dug_mask: np.ndarray,
                             *, n_trials: int = 20, sigma_o: float = 0.05, sigma_p: float = 0.08,
                             tau_m: float = 0.25, k_sigma: float = 2.0, min_support: float = 1.0,
                             with_fresh: bool = True, temporal: bool = False, seed0: int = 17000
                             ) -> dict[str, list[SystemResult]]:
    """[F5] Evidence that describes a surface which no longer exists.

    An observation made before an action and arriving after it is not wrong about anything -- it is a
    correct description of a surface that has since been dug away. The rule currently has no way to
    know that: ``Evidence`` carries no time, so a stale reading and a current one are
    indistinguishable to it.

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
        # the candidate is the CURRENT reading where one exists -- a stale reading should be dropped,
        # not promoted, and with temporal information the rule can tell the difference
        cand = fresh if (with_fresh and temporal) else stale
        r = evaluate(cand, ev, prior=prior, k_sigma=k_sigma, min_effective_support=min_support,
                     last_modified_at=(5.0 if temporal else None))
        est = cand if r.decision is Decision.PROMOTE else prior
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
    derivation inherits the inaccuracy, and the dangerous direction is **under-reporting**: a log
    claiming less shared ground than there was makes the rule believe the readings are more
    independent than they are, which is the optimistic error this whole design exists to prevent.

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
            common[true_mask] = rng.normal(0.0, shared_error_m)   # terrain ignores the log
            obs = [truth + common + rng.normal(0.0, sigma_o, truth.shape) for _ in range(m_agents)]
            phys = truth + rng.normal(0.0, sigma_p, truth.shape)  # model predicts the true surface
            prior = truth + prior_offset_m
            ev = [Evidence(f"agent{i}", "observation", o, sigma_o) for i, o in enumerate(obs)]
            ev.append(Evidence("terramech", "physics", phys, sigma_p))
            r = evaluate(obs[0], ev, prior=prior, correlation_mask=reported, k_sigma=k_sigma,
                         min_effective_support=min_support)
            est = obs[0] if r.decision is Decision.PROMOTE else prior
            e = _rms(est, truth)
            acc["gate"].errors_m.append(e)
            if e > tau_m:
                acc["gate"].n_harmful += 1
            if r.decision is Decision.ABSTAIN:
                acc["gate"].n_abstained += 1
        acc["gate"].mean_error_m = float(np.mean(acc["gate"].errors_m))
        out["gate"].append(acc["gate"])
    return out
