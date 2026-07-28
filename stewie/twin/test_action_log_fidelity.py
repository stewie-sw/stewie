"""[F6] The action log is wrong, and everything else is built on it.

``m_eff`` is derived from the record of what the machines did. If that record is inaccurate the
derivation inherits the inaccuracy, and the dangerous direction is **under-reporting**: a log
claiming less shared ground than there was makes the rule believe the readings are more independent
than they are. That is the optimistic error the whole design exists to prevent.

This file also runs the strongest control in the pre-registered set, the **action-log shuffle**:
permute the log while keeping its size, so ``m_eff`` is numerically right and attached to nothing
real. It was written to test whether the action history is load-bearing at all.

It returns a sharper answer than expected, and the answer is about the shape of the quantity rather
than the fidelity of the log. See ``test_shuffling_the_log_changes_nothing_because_m_eff_ignores_geometry``.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from stewie.twin.effective_support import effective_support_from_mask
from stewie.twin.veto_experiment import run_action_log_fidelity_sweep

_HEIGHT = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "samples", "lunar_dem", "haworth_10km_5m", "heightmap.rf32"))

pytestmark = pytest.mark.skipif(not os.path.exists(_HEIGHT),
                                reason="real Haworth DEM not present on this host")

N = 32


def _truth() -> np.ndarray:
    z = np.fromfile(_HEIGHT, dtype=np.float32)
    side = int(round(float(np.sqrt(z.size))))
    base = z.reshape(side, side)[1000:1000 + N, 1000:1000 + N].astype(np.float64)
    cut = np.zeros_like(base)
    cut[8:20, 8:20] = -0.40
    return base + cut


# --------------------------------------------------------------------------------------------
# The action history is load-bearing, and under-reporting is the dangerous direction
# --------------------------------------------------------------------------------------------
def test_an_accurate_log_keeps_the_rule_safe():
    truth = _truth()
    res = run_action_log_fidelity_sweep(truth, [1.0], n_trials=20)
    assert res["gate"][0].n_harmful == 0
    assert res["gate"][0].abstain_rate == 1.0


def test_severe_under_reporting_breaks_the_rule():
    """A log recording a quarter of the shared ground lifts m_eff above the support threshold, so the
    rule promotes evidence it should have declined. The action history is therefore load-bearing:
    corrupt it enough and the guarantee goes with it."""
    truth = _truth()
    res = run_action_log_fidelity_sweep(truth, [0.25, 0.0], n_trials=20)
    assert sum(x.n_harmful for x in res["gate"]) > 0, \
        "if a badly wrong log changed nothing, m_eff would not be doing any work"
    assert all(x.abstain_rate == 0.0 for x in res["gate"])


def test_moderate_under_reporting_is_tolerated():
    """Down to half the shared ground the reduced d still drags m_eff below threshold, so the rule
    declines. The failure is a cliff at the threshold rather than a gradual decay, which is worth
    knowing because it means log quality matters in a step rather than in proportion."""
    truth = _truth()
    res = run_action_log_fidelity_sweep(truth, [0.75, 0.5], n_trials=20)
    assert all(x.n_harmful == 0 for x in res["gate"])
    assert all(x.abstain_rate == 1.0 for x in res["gate"])


# --------------------------------------------------------------------------------------------
# The shuffle control, and what it actually revealed
# --------------------------------------------------------------------------------------------
def test_m_eff_depends_only_on_the_cardinality_of_D():
    """Three masks of the same size and completely different geometry give the same effective
    support to six decimal places. That is not an implementation detail: the region-aggregate bound
    is derived by mean squared error over cells treated symmetrically, so geometry cannot enter."""
    rng = np.random.default_rng(0)
    n = N * N
    k = int(0.4 * n)
    contiguous = np.zeros((N, N), dtype=bool)
    contiguous.ravel()[:k] = True
    scattered = np.zeros((N, N), dtype=bool)
    scattered.ravel()[rng.permutation(n)[:k]] = True
    assert contiguous.sum() == scattered.sum() == k
    assert effective_support_from_mask(3, contiguous) == pytest.approx(
        effective_support_from_mask(3, scattered), abs=1e-9)


def test_shuffling_the_log_changes_nothing_because_m_eff_ignores_geometry():
    """The pre-registered control asked whether the action history is load-bearing. Permuting the log
    while preserving its size leaves the outcome identical -- but NOT because the history is inert.
    It is because ``m_eff`` consumes only ``|D|/n`` and discards where the dependency actually is.

    So the control passes, and in passing it demonstrates something the fidelity sweep cannot: the
    spatial structure of the action history is thrown away. That is direct empirical support for the
    open question of whether a scalar is the right shape of object for this quantity, which is
    recorded in the proposal as the deepest unresolved item rather than as a defect."""
    truth = _truth()
    accurate = run_action_log_fidelity_sweep(truth, [1.0], n_trials=20, shuffle=False)
    shuffled = run_action_log_fidelity_sweep(truth, [1.0], n_trials=20, shuffle=True)
    assert accurate["gate"][0].n_harmful == shuffled["gate"][0].n_harmful == 0
    assert accurate["gate"][0].abstain_rate == shuffled["gate"][0].abstain_rate == 1.0


def test_a_geometry_aware_control_would_be_needed_to_test_the_premise():
    """Consequence, stated so the pre-registration is not read as satisfied when it is not.

    The shuffle control cannot falsify the premise while m_eff is a scalar, because the manipulation
    it applies is one the quantity is blind to by construction. Testing whether the action history's
    STRUCTURE matters requires a dependency representation that carries structure. Until then this
    control verifies the cardinality path only."""
    rng = np.random.default_rng(1)
    n = N * N
    k = int(0.3 * n)
    a = np.zeros((N, N), dtype=bool)
    a.ravel()[:k] = True
    b = np.zeros((N, N), dtype=bool)
    b.ravel()[rng.permutation(n)[:k]] = True
    assert effective_support_from_mask(4, a) == pytest.approx(effective_support_from_mask(4, b))
