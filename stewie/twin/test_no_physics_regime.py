"""[GATE2] The third regime: what happens when the veto cannot fire.

The previous iteration derived that the agreeing branch is safe under A5 and flagged one claim as
most likely wrong -- that the two branches are exhaustive. Checking it found this.

The rule has exactly two ``PROMOTE`` returns, so the decomposition is exhaustive over *control
flow*. It is not exhaustive over *proof regimes*. The agreeing return is reachable two ways:

  4a. a physical model was offered and agreed -- the residual test ran and passed, which is the
      premise the derivation uses, and the branch is safe under A5 with no dependency correction;
  4b. no physical model was offered at all -- the residual test never ran, ``residual_rms`` and
      ``tolerance`` are both a sentinel 0.0 indistinguishable from perfect agreement, and the
      derivation's premise is simply absent.

**A veto that cannot fire is not a veto.** In regime 4b the design degenerates to "accept what
corroborated observations say", which is the fusing baseline the whole construction exists to beat.

What the measurements below establish, on real Haworth LOLA terrain with controlled fault
injection:

  * With no correlation mask, regime 4b offers **no protection whatsoever and no bound**. Two
    agents sharing an error are accepted at 20/20 for any error above tau, out to 10 m. The
    acceptance does not degrade with the size of the fault; it is indifferent to it.
  * With a faithful mask, the support test alone stops all of it, at every fault size tested.

So regime 4b rests entirely on ``m_eff``, and the override branch rests on ``m_eff``. **Both
unproved branches reduce to the same object**, which is worth knowing: the remaining problem is
smaller and more focused than three separate arguments would suggest.

It also makes the dependence on the action log (F6) load-bearing in a way worth stating. In regime
4a the log is a refinement; in regime 4b it is the only thing standing between a shared error and
the authoritative state.
"""

from __future__ import annotations

import numpy as np
import pytest

from stewie.twin.promotion import Decision, Evidence, evaluate

TAU_M = 0.25
SIGMA_O = 0.05


@pytest.fixture(scope="module")
def truth() -> np.ndarray:
    """A real 32x32 patch of the Haworth LOLA DEM. Nothing here is synthesised."""
    dem = np.fromfile("samples/lunar_dem/haworth_10km_5m/heightmap.rf32", dtype=np.float32)
    n = int(np.sqrt(dem.size))
    return dem.reshape(n, n)[1000:1032, 1000:1032].astype(float)


def _shared_error_evidence(truth: np.ndarray, common_m: float, rng) -> list[Evidence]:
    """Two agents worked the same ground, so both readings carry the same error. F4, injected."""
    reading = truth + common_m
    return [Evidence("agent_a", "observation", reading + rng.normal(0, 0.005, truth.shape),
                     SIGMA_O, 1.0),
            Evidence("agent_b", "observation", reading + rng.normal(0, 0.005, truth.shape),
                     SIGMA_O, 1.0)]


def test_the_acceptance_surface_is_exactly_three_regimes(truth):
    """The regimes, reached by evaluation rather than by reading the source.

    The previous iteration claimed two. Control flow had two ``PROMOTE`` returns and that much was
    right, but one of them served two regimes with one sentence. Splitting it is what makes the
    third visible; this test is the guard against a fourth appearing unnoticed.
    """
    rng = np.random.default_rng(3)
    good = truth + rng.normal(0, SIGMA_O * 0.1, truth.shape)
    obs = [Evidence("a", "observation", good, SIGMA_O, 1.0),
           Evidence("b", "observation", truth + rng.normal(0, SIGMA_O * 0.1, truth.shape),
                    SIGMA_O, 1.0)]

    agreed = evaluate(good, [*obs, Evidence("terramech", "physics",
                                            truth + rng.normal(0, 0.08, truth.shape), 0.10, 1.0)],
                      min_effective_support=2.0)
    overruled = evaluate(good, [*obs, Evidence("terramech", "physics", truth + 5.0, 0.10, 1.0)],
                         min_effective_support=2.0)
    unvetoed = evaluate(good, obs, min_effective_support=2.0)

    assert {r.decision for r in (agreed, overruled, unvetoed)} == {Decision.PROMOTE}
    assert agreed.detail["veto_available"] and not agreed.detail["physics_disagrees"]      # 4a
    assert overruled.detail["veto_available"] and overruled.detail["physics_disagrees"]    # override
    assert not unvetoed.detail["veto_available"]                                           # 4b
    assert len({agreed.reason, overruled.reason, unvetoed.reason}) == 3, (
        "each regime must report itself distinctly; two sharing a sentence is how 4b hid"
    )


def test_regime_4b_is_reachable_and_reports_that_nothing_vetoed_it(truth):
    """The agreeing return fires with no physics at all, and now says so."""
    rng = np.random.default_rng(7)
    ev = _shared_error_evidence(truth, 0.9, rng)
    result = evaluate(ev[0].values, ev, min_effective_support=2.0)

    assert result.decision is Decision.PROMOTE
    assert result.detail["n_physics"] == 0
    assert result.detail["veto_available"] is False
    assert "NO physical model was offered" in result.reason
    # The sentinel that made this indistinguishable from genuine agreement.
    assert result.residual_rms_m == 0.0 and result.tolerance_m == 0.0


def test_regime_4b_without_a_mask_offers_no_protection_and_no_bound(truth):
    """The finding. Harm is limited only by the size of the injected fault, not by the rule."""
    worst_accepted = 0.0
    for common in (0.30, 0.90, 2.0, 10.0):
        rng = np.random.default_rng(11)
        harmful = 0
        for _ in range(20):
            ev = _shared_error_evidence(truth, common, rng)
            result = evaluate(ev[0].values, ev, min_effective_support=2.0)
            err = float(np.sqrt(np.mean((ev[0].values - truth) ** 2)))
            if result.decision is Decision.PROMOTE and err > TAU_M:
                harmful += 1
                worst_accepted = max(worst_accepted, err)
        assert harmful == 20, (
            f"common error {common} m: expected the unprotected regime to accept every trial, "
            f"got {harmful}/20 -- if this drops, some mechanism started working and the "
            "characterisation of 4b needs revisiting"
        )
    assert worst_accepted > 10.0, "a 10 m error was accepted; the regime has no bound at all"


def test_a_faithful_mask_is_the_only_thing_that_saves_regime_4b(truth):
    """Support alone stops all of it -- which is why 4b reduces entirely to m_eff."""
    mask = np.zeros(truth.shape, dtype=bool)
    mask.flat[:mask.size // 4] = True          # a quarter of cells worked by both agents

    for common in (0.30, 0.90, 10.0):
        rng = np.random.default_rng(11)
        for _ in range(20):
            ev = _shared_error_evidence(truth, common, rng)
            result = evaluate(ev[0].values, ev, correlation_mask=mask, min_effective_support=2.0)
            assert result.decision is Decision.ABSTAIN, (
                f"common error {common} m with d = 0.25 should fall below the support threshold"
            )


def test_the_protection_in_4b_is_knife_edge(truth):
    """Worth stating: with m = 2 and threshold 2.0, any dependency at all flips the decision.

    That is not robustness. It means the mask being merely non-empty is what separates accepting a
    10 m error from refusing it, and it is the sharpest illustration available of why the action
    log's fidelity (F6) is load-bearing rather than a refinement.
    """
    rng = np.random.default_rng(11)
    ev = _shared_error_evidence(truth, 0.9, rng)

    none_correlated = np.zeros(truth.shape, dtype=bool)
    assert evaluate(ev[0].values, ev, correlation_mask=none_correlated,
                    min_effective_support=2.0).decision is Decision.PROMOTE

    one_cell = np.zeros(truth.shape, dtype=bool)
    one_cell.flat[0] = True
    result = evaluate(ev[0].values, ev, correlation_mask=one_cell, min_effective_support=2.0)
    assert result.decision is Decision.ABSTAIN
    assert result.effective_n < 2.0
