"""[F6b] The action log fabricates overlap, and the tolerance turns out to be exact.

F6 sweeps a log that **omits** real shared ground, and its docstring called that "the dangerous
direction". That was a scoping assumption rather than a measurement: the family never made the log
report an overlap that did not happen, so nothing in the benchmark could contradict it.

The previous iteration flagged this. Every measurement of the mask policy supplied the mask as
ground truth -- all-ones exactly when a shared error was injected, all-zeros otherwise -- so the
0.067 m map error attributed to it was the ceiling of an oracle, not an achievable figure.

**Under-reporting is the direction that causes harm. Over-reporting is roughly four times more
sensitive.** With three agents against a support threshold of 2.25, an omitting log is tolerated to
50% before harmful acceptances appear, while a fabricating log destroys availability at 20%: on
evidence that is genuinely independent and entirely within its declared sigma, the rule declines
every promotion.

That failure is availability rather than harm, which is not the same as harmless. A rule that
abstains on everything leaves a twin that never learns the ground moved, and
``test_a7_repair_choice`` measures exactly that outcome as the worst map error of the available
policies on a worked site.

**Both cliffs sit at one closed-form constant.** Solving ``m / (1 + d(m-1)) = threshold``:

    d_crit = (m / threshold - 1) / (m - 1)

The decision flips there exactly -- verified per trial to within a single cell for ``m`` from 2 to
8. And the constant has two opposed readings at once: it is how much fabrication the rule tolerates
*and* how much real dependency it accepts. **Raising the threshold to buy safety against an omitting
log lowers d_crit and buys fragility against a fabricating one, in exact proportion.** There is no
setting robust to both. There is only a choice about which way to fail, and that choice should be
made deliberately rather than inherited from a default.

Real Haworth LOLA terrain. The log errors are controlled fault injection; the surface is not
synthesised, and in this family neither is the evidence -- only the record of what produced it.
"""

from __future__ import annotations

import numpy as np
import pytest

from stewie.twin.effective_support import log_error_tolerance
from stewie.twin.promotion import Decision, Evidence, evaluate
from stewie.twin.veto_experiment import run_action_log_overreporting_sweep

SIGMA_O = 0.05
SIGMA_P = 0.08
K_SIGMA = 2.0


@pytest.fixture(scope="module")
def truth() -> np.ndarray:
    dem = np.fromfile("samples/lunar_dem/haworth_10km_5m/heightmap.rf32", dtype=np.float32)
    n = int(np.sqrt(dem.size))
    return dem.reshape(n, n)[1000:1032, 1000:1032].astype(float)


def _good_independent_evidence(truth: np.ndarray, m: int, rng) -> list[Evidence]:
    """Separate ground, no common error, every reading inside its declared sigma."""
    obs = [Evidence(f"agent_{i}", "observation", truth + rng.normal(0.0, SIGMA_O, truth.shape),
                    SIGMA_O, 1.0) for i in range(m)]
    return [*obs, Evidence("terramech", "physics",
                           truth + rng.normal(0.0, SIGMA_P, truth.shape), SIGMA_P, 1.0)]


def test_a_fabricating_log_destroys_availability_on_good_evidence(truth):
    """The finding. Nothing is wrong except the record of what the machines did."""
    results = run_action_log_overreporting_sweep(truth, [0.0, 0.10, 0.20, 0.50, 1.0])["gate"]
    by_rate = {round(r.level_m, 2): r for r in results}

    assert by_rate[0.0].n_abstained == 0, "an accurate log must accept good independent evidence"
    assert by_rate[0.10].n_abstained == 0, "10% fabrication is below the tolerance"
    for rate in (0.20, 0.50, 1.0):
        assert by_rate[rate].n_abstained == by_rate[rate].n_trials, (
            f"{rate:.0%} fabricated overlap should decline every promotion"
        )
    assert all(r.n_harmful == 0 for r in results), (
        "over-reporting must never produce a harmful acceptance; its cost is availability"
    )


@pytest.mark.parametrize(("m", "threshold"),
                         [(2, 1.5), (3, 2.25), (3, 2.0), (4, 3.0), (5, 2.5), (6, 4.0), (8, 5.0)])
def test_the_tolerance_is_exact_not_approximate(truth, m: int, threshold: float):
    """The decision flips at ``d_crit`` to within one cell, across the whole range of m tested.

    Swept over the REALIZED mask fraction rather than a probability, because a Bernoulli mask makes
    the realized fraction a random variable and turns an exact boundary into a noisy one. That is
    what made a first pass read the cliff as roughly two percentage points high in every
    configuration -- a bias in the estimator, not in the formula.
    """
    d_crit = log_error_tolerance(m, threshold)
    rng = np.random.default_rng(9000)
    evidence = _good_independent_evidence(truth, m, rng)
    cell = 1.0 / truth.size

    accepted_max = 0.0
    abstained_min = 1.0
    for step in range(60):
        d = d_crit - 0.05 + 0.1 * (step / 59.0)
        k = max(0, min(truth.size, int(round(d * truth.size))))
        mask = np.zeros(truth.shape, dtype=bool)
        mask.ravel()[:k] = True
        realized = k / truth.size
        result = evaluate(evidence[0].values, evidence, correlation_mask=mask,
                          k_sigma=K_SIGMA, min_effective_support=threshold)
        if result.decision is Decision.PROMOTE:
            accepted_max = max(accepted_max, realized)
        else:
            abstained_min = min(abstained_min, realized)

    assert accepted_max <= d_crit + cell
    assert abstained_min >= d_crit - 4 * cell


def test_one_constant_governs_both_directions_so_they_trade_off(truth):
    """The consequence, and the reason this is a design statement rather than a bug report.

    ``d_crit`` is simultaneously how much fabricated overlap the rule tolerates and how much real
    dependency it will accept. Tightening the threshold to resist an omitting log necessarily makes
    a fabricating log bite sooner. No setting is robust to both.
    """
    m = 3
    tolerances = {thr: log_error_tolerance(m, thr) for thr in (1.5, 2.0, 2.25, 2.5, 2.9)}
    ordered = [tolerances[t] for t in sorted(tolerances)]
    assert ordered == sorted(ordered, reverse=True), (
        "a stricter support threshold must lower the tolerance to fabrication; if it did not, the "
        "two requirements would be independent and could be satisfied separately"
    )
    assert log_error_tolerance(m, 3.0) == 0.0, "a threshold at m accepts no dependency at all"
    assert log_error_tolerance(2, 1.0) == 1.0, "and a threshold of 1 with two sources accepts any"

    with pytest.raises(ValueError):
        log_error_tolerance(1, 1.0)


def test_the_two_directions_fail_in_opposite_ways(truth):
    """Under-reporting yields harm; over-reporting yields refusal. Same mechanism, same constant."""
    rng = np.random.default_rng(4242)
    m = 3
    threshold = 2.25
    d_true = 0.40
    true_mask = np.zeros(truth.shape, dtype=bool)
    true_mask.ravel()[:int(d_true * truth.size)] = True
    common = np.where(true_mask, 0.6, 0.0)

    dependent = [Evidence(f"agent_{i}", "observation",
                          truth + common + rng.normal(0.0, SIGMA_O, truth.shape), SIGMA_O, 1.0)
                 for i in range(m)]
    dependent.append(Evidence("terramech", "physics",
                              truth + rng.normal(0.0, SIGMA_P, truth.shape), SIGMA_P, 1.0))

    blind = evaluate(dependent[0].values, dependent,
                     correlation_mask=np.zeros(truth.shape, dtype=bool),
                     k_sigma=K_SIGMA, min_effective_support=threshold)
    assert blind.decision is Decision.PROMOTE, "a log reporting nothing accepts dependent evidence"
    assert float(np.sqrt(np.mean((dependent[0].values - truth) ** 2))) > 0.25, (
        "and that acceptance is harmful, which is the F6 result"
    )

    good = _good_independent_evidence(truth, m, np.random.default_rng(77))
    fabricated = np.zeros(truth.shape, dtype=bool)
    fabricated.ravel()[:int(0.30 * truth.size)] = True
    assert evaluate(good[0].values, good, correlation_mask=fabricated, k_sigma=K_SIGMA,
                    min_effective_support=threshold).decision is Decision.ABSTAIN, (
        "while a log inventing 30% refuses evidence that is entirely sound"
    )
