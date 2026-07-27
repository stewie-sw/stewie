"""[GATE6] Does a gated promotion beat fixed precedence? The test that can falsify the premise.

The thesis premise is that provenance-, reliability-, and physics-gated promotion reduces HARMFUL
STATE ACCEPTANCE relative to a single-authoritative-map baseline. If the gate cannot beat
``z[m] = oh[m]`` even on a deliberately injected failure, the premise is wrong and the topic should
not be locked. This file is written to give it every chance to fail.

Four scenarios, on the real Haworth LOLA DEM:

  S1  good observation, good physics     -> both should accept          (false-rejection control)
  S2  BAD observation, good physics      -> baseline accepts (harm); gate must not
  S3  good observation, MISSPECIFIED physics -> gate must NOT reject the good observation
  S4  bad observation and bad physics    -> gate must not confidently accept

S3 is the important one. A gate that simply trusts physics would "win" S2 and lose S3, which is the
failure mode the scoping review's model-misspecification cell is about. Passing S2 while failing S3
would mean the gate had replaced one blind precedence rule with another.

Harmful acceptance is scored against an independent ORACLE surface that the gate never sees.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from stewie.twin.promotion import Decision, Evidence, baseline_fixed_precedence, evaluate

_HEIGHT = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "samples", "lunar_dem", "haworth_10km_5m", "heightmap.rf32"))

pytestmark = pytest.mark.skipif(not os.path.exists(_HEIGHT),
                                reason="real Haworth DEM not present on this host")

N = 32
SIGMA_OBS = 0.05          # declared sensor 1-sigma [m]
SIGMA_PHYS = 0.08         # declared terramechanics 1-sigma [m]
HARM_THRESHOLD_M = 0.25   # an accepted state this far from truth is a harmful promotion


def _truth() -> np.ndarray:
    """The ORACLE surface: real Haworth terrain after a real cut. The gate never sees this."""
    z = np.fromfile(_HEIGHT, dtype=np.float32)
    side = int(round(float(np.sqrt(z.size))))
    base = z.reshape(side, side)[1000:1000 + N, 1000:1000 + N].astype(np.float64)
    cut = np.zeros_like(base)
    cut[8:20, 8:20] = -0.40
    return base + cut


def _noisy(truth: np.ndarray, sigma: float, seed: int) -> np.ndarray:
    """A measurement of the truth at its declared uncertainty. Seeded, so this is reproducible."""
    return truth + np.random.default_rng(seed).normal(0.0, sigma, truth.shape)


def _harmful(accepted: np.ndarray, truth: np.ndarray) -> bool:
    return float(np.sqrt(np.mean((accepted - truth) ** 2))) > HARM_THRESHOLD_M


# --------------------------------------------------------------------------------------------
# S1: everything is fine. Neither system should refuse. Guards against a gate that just says no.
# --------------------------------------------------------------------------------------------
def test_s1_good_observation_and_good_physics_are_accepted_by_both():
    truth = _truth()
    prior = truth + 0.5                         # a stale prior, wrong by 0.5 m
    obs = _noisy(truth, SIGMA_OBS, seed=1)
    phys = _noisy(truth, SIGMA_PHYS, seed=2)

    r = evaluate(obs, [Evidence("stereo", "observation", obs, SIGMA_OBS),
                       Evidence("terramech", "physics", phys, SIGMA_PHYS)], prior=prior)
    assert r.decision is Decision.PROMOTE, r.reason
    assert not _harmful(obs, truth)
    assert not _harmful(baseline_fixed_precedence(prior, obs), truth)


# --------------------------------------------------------------------------------------------
# S2: the injected failure. A sensor glitch offsets the whole observation.
# --------------------------------------------------------------------------------------------
def test_s2_baseline_accepts_a_bad_observation_and_the_gate_does_not():
    truth = _truth()
    prior = truth.copy()                        # prior is CORRECT here; accepting the glitch is harmful
    bad_obs = truth + 0.9                       # 0.9 m sensor offset, far outside the declared 0.05
    phys = _noisy(truth, SIGMA_PHYS, seed=3)

    accepted_baseline = baseline_fixed_precedence(prior, bad_obs)
    assert _harmful(accepted_baseline, truth), "baseline should be harmed by the glitch"

    r = evaluate(bad_obs, [Evidence("stereo", "observation", bad_obs, SIGMA_OBS),
                           Evidence("terramech", "physics", phys, SIGMA_PHYS)], prior=prior)
    assert r.decision is not Decision.PROMOTE, r.reason
    assert r.residual_rms_m > r.tolerance_m
    accepted_gate = prior if r.decision is not Decision.PROMOTE else bad_obs
    assert not _harmful(accepted_gate, truth)


# --------------------------------------------------------------------------------------------
# S3: the anti-over-trust test. Physics is wrong; the observation is right.
# --------------------------------------------------------------------------------------------
def test_s3_misspecified_physics_does_not_cause_a_good_observation_to_be_rejected():
    """A gate that trusted physics would REJECT here. That is the failure mode this guards."""
    truth = _truth()
    prior = truth + 0.5
    obs_a = _noisy(truth, SIGMA_OBS, seed=4)
    obs_b = _noisy(truth, SIGMA_OBS, seed=5)          # independent corroborating sensor
    bad_phys = truth - 0.7                            # misspecified soil model: predicts 0.7 m too deep

    r = evaluate(obs_a, [Evidence("stereo", "observation", obs_a, SIGMA_OBS),
                         Evidence("lidar", "observation", obs_b, SIGMA_OBS),
                         Evidence("terramech", "physics", bad_phys, SIGMA_PHYS)], prior=prior)
    # the residual IS large -- the gate must notice, and still not reject the observation
    assert r.residual_rms_m > r.tolerance_m
    assert r.decision is Decision.PROMOTE, r.reason
    assert "model is the outlier" in r.reason
    assert not _harmful(obs_a, truth)


def test_s3b_misspecified_physics_without_corroboration_abstains_rather_than_rejecting():
    """With only ONE observation the ambiguity is genuine: bad sensor or bad model, unknowable.
    Abstain is the honest answer; rejecting would be over-trusting the model."""
    truth = _truth()
    obs = _noisy(truth, SIGMA_OBS, seed=6)
    bad_phys = truth - 0.7

    r = evaluate(obs, [Evidence("stereo", "observation", obs, SIGMA_OBS),
                       Evidence("terramech", "physics", bad_phys, SIGMA_PHYS)], prior=truth)
    assert r.decision is Decision.ABSTAIN, r.reason
    assert "cannot distinguish" in r.reason


# --------------------------------------------------------------------------------------------
# S4: both channels bad. The gate must not confidently accept.
# --------------------------------------------------------------------------------------------
def test_s4_two_contradicting_observations_abstain():
    truth = _truth()
    obs_a = truth + 0.9
    obs_b = truth - 0.9
    r = evaluate(obs_a, [Evidence("stereo", "observation", obs_a, SIGMA_OBS),
                         Evidence("lidar", "observation", obs_b, SIGMA_OBS)], prior=truth)
    assert r.decision is Decision.ABSTAIN
    assert "contradict each other" in r.reason


# --------------------------------------------------------------------------------------------
# The headline comparison.
# --------------------------------------------------------------------------------------------
def test_harmful_promotion_rate_gate_beats_fixed_precedence():
    """Across the injected-failure scenarios, count how often each system accepts a harmful state."""
    truth = _truth()
    rng_seeds = range(10, 30)
    baseline_harm = gate_harm = 0
    for s in rng_seeds:
        prior = truth.copy()
        bad_obs = truth + 0.9                                  # the injected sensor failure
        phys = _noisy(truth, SIGMA_PHYS, seed=s)
        if _harmful(baseline_fixed_precedence(prior, bad_obs), truth):
            baseline_harm += 1
        r = evaluate(bad_obs, [Evidence("stereo", "observation", bad_obs, SIGMA_OBS),
                               Evidence("terramech", "physics", phys, SIGMA_PHYS)], prior=prior)
        accepted = bad_obs if r.decision is Decision.PROMOTE else prior
        if _harmful(accepted, truth):
            gate_harm += 1

    n = len(list(rng_seeds))
    assert baseline_harm == n, f"baseline should be harmed every time (got {baseline_harm}/{n})"
    assert gate_harm == 0, f"gate should never accept the glitch (got {gate_harm}/{n})"


def test_gate_does_not_win_by_refusing_everything():
    """The false-rejection control: on clean evidence the gate must promote, every time."""
    truth = _truth()
    promoted = 0
    for s in range(40, 60):
        obs = _noisy(truth, SIGMA_OBS, seed=s)
        phys = _noisy(truth, SIGMA_PHYS, seed=s + 100)
        r = evaluate(obs, [Evidence("stereo", "observation", obs, SIGMA_OBS),
                           Evidence("terramech", "physics", phys, SIGMA_PHYS)], prior=truth + 0.5)
        promoted += (r.decision is Decision.PROMOTE)
    assert promoted == 20, f"gate refused clean evidence {20 - promoted} times"


# --------------------------------------------------------------------------------------------
# G-A: action-correlated evidence is discounted rather than counted as independent support.
# --------------------------------------------------------------------------------------------
def test_action_correlated_cells_reduce_effective_support():
    """G-A: two vehicles that both dug a cell do not supply independent evidence about it.

    Uses TWO observations, because that is what the discount is about. Under the C3 bound the
    correlation between observations is what shrinks, so a single reading is never discounted --
    see ``test_a_single_observation_is_not_discounted_by_shared_ground`` below."""
    truth = _truth()
    obs_a = _noisy(truth, SIGMA_OBS, seed=7)
    obs_b = _noisy(truth, SIGMA_OBS, seed=8)
    ev = [Evidence("scout", "observation", obs_a, SIGMA_OBS, reliability=0.6),
          Evidence("hauler", "observation", obs_b, SIGMA_OBS, reliability=0.6)]

    clean = evaluate(obs_a, ev, prior=truth, min_effective_support=0.9)
    assert clean.decision is Decision.PROMOTE
    assert clean.effective_n == pytest.approx(2 * 0.6)      # nothing shared: full support

    # A realistic co-dig: both vehicles worked most of the pad.
    mask = np.zeros(truth.shape, dtype=bool)
    mask[6:26, 6:26] = True                     # 400 of 1024 cells touched by BOTH
    corr = evaluate(obs_a, ev, prior=truth, correlation_mask=mask, min_effective_support=0.9)
    assert corr.n_correlated == 400
    assert corr.effective_n < clean.effective_n, "shared ground must reduce independent support"
    assert corr.effective_n > 0.6, "but two correlated readings are still worth more than one"
    assert corr.decision is Decision.ABSTAIN
    assert "action-correlated" in corr.reason


def test_a_single_observation_is_not_discounted_by_shared_ground():
    """Semantic correction that came with the C3 bound, and it changed behaviour.

    The superseded linear discount shrank support even with ONE observation, which is meaningless:
    another vehicle having dug the same cell does not make your own reading of it worse. It makes two
    readings less independent OF EACH OTHER. With m=1 there is no corroboration to discount, so C3
    returns full support at any overlap."""
    truth = _truth()
    obs = _noisy(truth, SIGMA_OBS, seed=7)
    ev = [Evidence("scout", "observation", obs, SIGMA_OBS, reliability=0.6)]
    mask = np.zeros(truth.shape, dtype=bool)
    mask[6:26, 6:26] = True
    r = evaluate(obs, ev, prior=truth, correlation_mask=mask, min_effective_support=0.5)
    assert r.n_correlated == 400
    assert r.effective_n == pytest.approx(0.6)   # reliability only; no independence discount
    assert r.decision is Decision.PROMOTE



def test_small_correlated_region_reduces_support_without_flipping_the_decision():
    """The discount is proportional, not a cliff: a little shared ground lowers effective support
    but does not by itself refuse."""
    truth = _truth()
    obs_a = _noisy(truth, SIGMA_OBS, seed=7)
    obs_b = _noisy(truth, SIGMA_OBS, seed=9)
    ev = [Evidence("scout", "observation", obs_a, SIGMA_OBS, reliability=0.6),
          Evidence("hauler", "observation", obs_b, SIGMA_OBS, reliability=0.6)]
    mask = np.zeros(truth.shape, dtype=bool)
    mask[8:20, 8:20] = True                     # 144 of 1024 -> d = 0.140625
    r = evaluate(obs_a, ev, prior=truth, correlation_mask=mask, min_effective_support=0.9)
    assert r.n_correlated == 144
    # C3: m/(1 + d(m-1)) * mean_reliability = 2/(1 + 0.140625) * 0.6
    assert r.effective_n == pytest.approx(2 / (1 + 0.140625) * 0.6, rel=1e-9)
    assert r.decision is Decision.PROMOTE       # still above threshold, correctly

