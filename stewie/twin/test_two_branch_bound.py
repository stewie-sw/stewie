"""The repair to the bound's form: a two-branch decomposition, with one branch now derived.

The previous iteration established that no function of ``(k, m_eff, sigma_o)`` can bound harmful
acceptance. This file establishes the shape that can, and proves half of it.

**The decomposition.** The rule accepts on exactly two branches. Either the physical model agreed
with the observation, or it disagreed and corroborating observations overruled it. So

    Pr[accept AND harmful]  =  Pr[branch 4 AND harmful]  +  Pr[override AND harmful]

**Branch 4 is safe under A5, and the argument needs no dependency correction at all.** Write the
common error as ``c`` on a fraction ``d`` of cells. Accepting on branch 4 means the residual test
passed:

    d*c^2 + sigma_o^2 + sigma_p^2  <=  k^2 (sigma_o^2 + sigma_p^2)

and A5 says ``k^2 (sigma_o^2 + sigma_p^2) <= tau^2``. Therefore

    harm RMS^2  =  d*c^2 + sigma_o^2  <=  tau^2 - sigma_p^2  <  tau^2

so the acceptance cannot be harmful. Note what this does *not* depend on: ``m``, ``d`` and
``m_eff`` are all absent. The dilution by ``d`` appears identically in the detection and the harm
condition, so it cancels, and the ordering is independent of how much ground was shared.

**A doubt this settles.** The previous entry worried that the residual test compares an RMS over the
whole region against a per-cell tolerance while the common error is diluted by ``d``, so the two
thresholds might not order consistently. They do: both are conditions on the same quantity ``d*c^2``.
The doubt was unfounded and is recorded as such.

**What remains.** The override branch. That is where ``m_eff`` belongs and where the bound is still
unproved, and it is now the whole of the remaining problem rather than one term among several.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from stewie.twin.promotion import Decision, Evidence, evaluate

_HEIGHT = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "samples", "lunar_dem", "haworth_10km_5m", "heightmap.rf32"))

pytestmark = pytest.mark.skipif(not os.path.exists(_HEIGHT),
                                reason="real Haworth DEM not present on this host")

N = 32
SIGMA_O, SIGMA_P, TAU = 0.05, 0.08, 0.25


def _truth() -> np.ndarray:
    z = np.fromfile(_HEIGHT, dtype=np.float32)
    side = int(round(float(np.sqrt(z.size))))
    base = z.reshape(side, side)[1000:1000 + N, 1000:1000 + N].astype(np.float64)
    cut = np.zeros_like(base)
    cut[8:20, 8:20] = -0.40
    return base + cut


def a5_holds(k: float) -> bool:
    return k * float(np.hypot(SIGMA_O, SIGMA_P)) <= TAU


def _branch4_run(truth, k, overlaps=(0.1, 0.3, 0.5, 0.8, 1.0), scales=(0.3, 0.6, 1.2), trials=30):
    """Count acceptances taken on the physics-agrees branch, and how many were harmful."""
    accepted = harmful = 0
    worst = 0.0
    for d in overlaps:
        mask = np.zeros(truth.shape, dtype=bool)
        mask.ravel()[:int(d * truth.size)] = True
        for t in range(trials):
            rng = np.random.default_rng(53000 + t)
            for scale in scales:
                common = np.zeros(truth.shape)
                common[mask] = rng.normal(0.0, scale)
                obs = [truth + common + rng.normal(0.0, SIGMA_O, truth.shape) for _ in range(3)]
                phys = truth + rng.normal(0.0, SIGMA_P, truth.shape)
                ev = [Evidence(f"a{i}", "observation", o, SIGMA_O) for i, o in enumerate(obs)]
                ev.append(Evidence("p", "physics", phys, SIGMA_P))
                r = evaluate(obs[0], ev, prior=truth + 0.15, correlation_mask=mask,
                             k_sigma=k, min_effective_support=1.0)
                if r.decision is Decision.PROMOTE and "consistent" in r.reason:
                    accepted += 1
                    e = float(np.sqrt(np.mean((obs[0] - truth) ** 2)))
                    worst = max(worst, e)
                    if e > TAU:
                        harmful += 1
    return accepted, harmful, worst


def test_the_two_thresholds_are_conditions_on_the_same_quantity():
    """Detection fires at ``d*c^2 > (k^2-1)(so^2+sp^2)``; harm begins at ``d*c^2 > tau^2 - so^2``.
    Both constrain ``d*c^2``, so the shared-fraction dilution cancels and their ordering does not
    depend on ``d``. This is the algebra behind the empirical result below."""
    s2 = SIGMA_O ** 2 + SIGMA_P ** 2
    for k in (1.5, 2.0, 3.0, 5.0):
        detect = (k ** 2 - 1) * s2
        harm = TAU ** 2 - SIGMA_O ** 2
        # the ordering predicted by algebra
        predicted_safe = detect < harm
        # equivalent closed form
        assert predicted_safe == (k * np.sqrt(s2) < np.sqrt(TAU ** 2 + SIGMA_P ** 2))


def test_a5_is_strictly_stronger_than_branch_four_needs():
    """A5 requires ``k*sqrt(so^2+sp^2) <= tau``; branch 4 needs only
    ``k*sqrt(so^2+sp^2) < sqrt(tau^2+sp^2)``, and the latter bound is larger. So assuming A5 is
    sufficient for this branch with room to spare, which is worth knowing because A5 is the more
    expensive assumption."""
    s = float(np.hypot(SIGMA_O, SIGMA_P))
    assert np.sqrt(TAU ** 2 + SIGMA_P ** 2) > TAU
    k_a5 = TAU / s
    k_branch4 = float(np.sqrt(TAU ** 2 + SIGMA_P ** 2)) / s
    assert k_branch4 > k_a5


def test_under_a5_no_physics_agrees_acceptance_is_harmful():
    """The derived claim, checked against 450 sampled configurations spanning overlap and
    common-error scale. Zero harmful acceptances on this branch, and the worst one comfortably
    inside tau."""
    truth = _truth()
    assert a5_holds(2.0)
    accepted, harmful, worst = _branch4_run(truth, k=2.0)
    assert accepted > 100, "the branch must actually fire, or the test proves nothing"
    assert harmful == 0, f"A5 should make this branch safe, got {harmful} harmful"
    assert worst < TAU


def test_violating_a5_makes_the_same_branch_unsafe():
    """Necessity, not just sufficiency: widen the gate past A5 and the identical branch starts
    accepting harmful states."""
    truth = _truth()
    assert not a5_holds(4.0)
    accepted, harmful, worst = _branch4_run(truth, k=4.0)
    assert accepted > 100
    assert harmful > 0, "without A5 the branch must be able to accept a harmful state"
    assert worst > TAU


def test_m_eff_does_not_appear_in_the_branch_four_argument():
    """Scope of the result, pinned. The branch-4 safety argument uses only k, sigma_o, sigma_p and
    tau. Effective support is irrelevant to it, which is why the original single-expression bound
    stated in terms of m_eff could not be right: it conflated a branch that does not need m_eff with
    one that does."""
    truth = _truth()
    # same configuration, wildly different m_eff via the correlation mask; branch 4 stays safe
    for d in (0.0, 1.0):
        mask = np.zeros(truth.shape, dtype=bool)
        mask.ravel()[:int(d * truth.size)] = True
        accepted, harmful, _ = _branch4_run(truth, k=2.0, overlaps=(d,), scales=(0.6,), trials=30)
        assert harmful == 0
