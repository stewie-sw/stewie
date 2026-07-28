"""[F5] Evidence that is correct about a surface which no longer exists.

An observation taken before an action and arriving after it is not wrong. It is a faithful
description of ground that has since been dug away. The rule had no way to tell: ``Evidence`` carried
no time at all, so a stale reading and a current one were indistinguishable to it.

What that cost was NOT harm. The physics channel catches a lone stale reading, because the model
predicts the surface as it now is and disagrees with it, and the rule declines. What it cost was
**availability**: with a stale reading present the rule declined every single time, even when a
correct current reading was sitting in the same evidence set unused. Safe and useless.

The fix uses the action history, which is the object this whole dissertation is about. It already
carries the intervals during which each cell was modified, so it can say when the ground a reading
describes was last changed. That gives the action history a second job beyond computing D: it dates
the evidence.

**Caveat stated in advance.** These trials give the standing prior the exact current surface, so
abstaining scores a perfect zero and promoting a fresh reading scores its sensor noise. That is an
unfair advantage to abstention and it is deliberate: it means the availability finding cannot be an
artefact of a conveniently bad prior. Accuracy comparisons from this file would be meaningless.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from stewie.twin.promotion import Evidence, stale_sources
from stewie.twin.veto_experiment import run_stale_evidence_sweep

_HEIGHT = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "samples", "lunar_dem", "haworth_10km_5m", "heightmap.rf32"))

pytestmark = pytest.mark.skipif(not os.path.exists(_HEIGHT),
                                reason="real Haworth DEM not present on this host")

N = 32
SIGMA_O = 0.05


def _old_new_dug(depth: float):
    z = np.fromfile(_HEIGHT, dtype=np.float32)
    side = int(round(float(np.sqrt(z.size))))
    old = z.reshape(side, side)[1000:1000 + N, 1000:1000 + N].astype(np.float64)
    dug = np.zeros(old.shape, dtype=bool)
    dug[8:24, 8:24] = True
    new = old.copy()
    new[dug] -= depth
    return old, new, dug


# --------------------------------------------------------------------------------------------
# The staleness predicate
# --------------------------------------------------------------------------------------------
def test_stale_sources_flags_only_readings_that_predate_the_action():
    z = np.zeros((4, 4))
    ev = [Evidence("old", "observation", z, SIGMA_O, observed_at=1.0),
          Evidence("new", "observation", z, SIGMA_O, observed_at=9.0),
          Evidence("untimed", "observation", z, SIGMA_O)]
    assert stale_sources(ev, 5.0) == ["old"]


def test_absent_temporal_information_changes_nothing():
    """Evidence predating the temporal model still has to be judged, so an unknown time must not be
    guessed at in either direction."""
    z = np.zeros((4, 4))
    ev = [Evidence("a", "observation", z, SIGMA_O, observed_at=1.0),
          Evidence("untimed", "observation", z, SIGMA_O)]
    assert stale_sources(ev, None) == []              # no modification time known
    assert "untimed" not in stale_sources(ev, 5.0)    # no observation time known


# --------------------------------------------------------------------------------------------
# The cost, and the fix
# --------------------------------------------------------------------------------------------
@pytest.mark.parametrize("depth", [0.3, 0.6, 1.0])
def test_without_time_a_stale_reading_blocks_a_current_one(depth):
    """The availability cost. A correct current reading is present and unused."""
    old, new, dug = _old_new_dug(depth)
    r = run_stale_evidence_sweep(old, new, dug, with_fresh=True, temporal=False)["gate"][0]
    assert r.abstain_rate == 1.0, "the rule should be blocked by the contradiction it cannot date"
    assert r.n_harmful == 0, "and it should still be safe while being useless"


@pytest.mark.parametrize("depth", [0.3, 0.6, 1.0])
def test_dating_the_evidence_restores_availability_without_costing_safety(depth):
    old, new, dug = _old_new_dug(depth)
    r = run_stale_evidence_sweep(old, new, dug, with_fresh=True, temporal=True)["gate"][0]
    assert r.abstain_rate == 0.0, "the stale reading should be dropped, not treated as contradiction"
    assert r.n_harmful == 0
    assert r.mean_error_m == pytest.approx(SIGMA_O, abs=0.01), \
        "the accepted state should be the current reading, carrying only its own sensor noise"


def test_a_stale_reading_alone_is_still_declined():
    """Dropping stale evidence must not mean promoting whatever is left. With nothing current, there
    is nothing to accept."""
    old, new, dug = _old_new_dug(0.6)
    r = run_stale_evidence_sweep(old, new, dug, with_fresh=False, temporal=True)["gate"][0]
    assert r.abstain_rate == 1.0
    assert r.n_harmful == 0


def test_the_physics_channel_already_caught_the_lone_stale_reading():
    """Recorded because it corrects a prediction. I expected a lone stale reading to be accepted and
    cause harm. It is not: the model predicts the current surface, disagrees with the stale one, and
    with no corroboration the rule declines. The temporal gap was never a safety gap."""
    old, new, dug = _old_new_dug(0.6)
    r = run_stale_evidence_sweep(old, new, dug, with_fresh=False, temporal=False)["gate"][0]
    assert r.n_harmful == 0
    assert r.abstain_rate == 1.0
