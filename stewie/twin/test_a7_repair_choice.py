"""[GATE2] Which repair for A7, measured rather than argued.

The previous iteration found A7 false on this platform -- the governance layer refuses to supply a
physics model for a body it has no validated profile for -- and recommended enforcing A7: abstain
whenever no model is available. It then flagged that recommendation as the claim most likely wrong,
on the grounds that abstaining on *every* promotion leaves a permanently stale twin, and a map that
is always wrong may be worse than one that is occasionally wrong.

It was wrong. **Enforcing A7 is the worst of the three policies on an actively worked site**, and
the repair that wins is the one the dissertation is already about.

Three policies, all on a body with no validated model:

  ``current``       accept on corroboration; the action log is never consulted
  ``enforce_a7``    abstain whenever no model is available
  ``require_mask``  no model, but consult the action log and abstain on insufficient support

Measured over 40 sequential promotions on real Haworth terrain, where the ground genuinely moves
because the agents are excavating it, with 35% of promotions carrying a shared error:

  policy         harmful   abstained   mean map error
  current             12         0/40        0.271 m
  enforce_a7           0        40/40        1.718 m
  require_mask         0        12/40        0.067 m

**Enforcing A7 is safe and useless.** It never accepts a harmful state because it never accepts
anything, and its map ends up seven times worse than the policy it was meant to improve on, because
it never learns the ground moved. ``require_mask`` is better on both axes at once.

**Where enforcing A7 is right.** Only on a site that is not being worked. Sweeping how often the
ground actually moves puts the crossover at a dig rate near 1 in 20 promotions; below that,
abstaining costs nothing because nothing changed, and above it the gap widens to a factor of forty.
A site that is not being worked is also a site whose twin has nothing to do, so the regime where
enforcement wins is the regime where the question does not arise.

**The through-line.** Both unproved branches of the bound reduce to ``m_eff``, and now the
recommended repair does too. The action log is not a refinement on top of the veto; where the veto
is unavailable it is the entire mechanism.

**The caveat, measured not assumed.** ``require_mask`` inherits F6: it is only as good as the action
log. With an increasingly unfaithful log it accrues harmful acceptances, reaching the ``current``
policy's behaviour when the log records nothing at all. It still beats ``enforce_a7`` on map error at
every fidelity level tested, but that is a statement about staleness being expensive, not about the
mask being robust.

Real terrain, real excavation, controlled fault injection. Nothing here is synthesised.
"""

from __future__ import annotations

import numpy as np
import pytest

from stewie.twin.promotion import Decision, Evidence, evaluate

TAU_M = 0.25
SIGMA_O = 0.05
SUPPORT_THRESHOLD = 2.0


@pytest.fixture(scope="module")
def base() -> np.ndarray:
    dem = np.fromfile("samples/lunar_dem/haworth_10km_5m/heightmap.rf32", dtype=np.float32)
    n = int(np.sqrt(dem.size))
    return dem.reshape(n, n)[1000:1032, 1000:1032].astype(float)


def _campaign(base: np.ndarray, policy: str, *, dig_prob: float = 1.0, log_miss: float = 0.0,
              steps: int = 40, p_dependent: float = 0.35, seed: int = 5):
    """Sequential operation on a body with no validated physics model.

    The ground really moves: each worked step excavates a real patch, so a twin that never updates
    really does go stale. ``log_miss`` is the probability that a genuine overlap is absent from the
    action log, which is F6 injected into this setting.
    """
    rng = np.random.default_rng(seed)
    truth = base.copy()
    held = base.copy()
    harmful = 0
    abstained = 0
    errors: list[float] = []

    for _ in range(steps):
        if rng.random() < dig_prob:
            r0, c0 = rng.integers(0, 20), rng.integers(0, 20)
            truth[r0:r0 + 12, c0:c0 + 12] -= 0.40

        dependent = rng.random() < p_dependent
        reading = truth + (rng.normal(0.9, 0.05) if dependent else 0.0)
        evidence = [
            Evidence("agent_a", "observation", reading + rng.normal(0, SIGMA_O * 0.1, truth.shape),
                     SIGMA_O, 1.0),
            Evidence("agent_b", "observation", reading + rng.normal(0, SIGMA_O * 0.1, truth.shape),
                     SIGMA_O, 1.0),
        ]
        logged = dependent and (rng.random() >= log_miss)
        mask = np.ones(truth.shape, dtype=bool) if logged else np.zeros(truth.shape, dtype=bool)

        if policy == "enforce_a7":
            result = None
        elif policy == "current":
            result = evaluate(
                evidence,
                correlation_mask=np.zeros(truth.shape, dtype=bool),
                min_effective_support=SUPPORT_THRESHOLD,
            )
        elif policy == "require_mask":
            result = evaluate(
                evidence,
                correlation_mask=mask,
                min_effective_support=SUPPORT_THRESHOLD,
            )
        else:
            raise ValueError(policy)

        if result is not None and result.decision is Decision.PROMOTE:
            assert result.accepted_state is not None
            held = result.accepted_state.copy()
            if float(np.sqrt(np.mean((held - truth) ** 2))) > TAU_M:
                harmful += 1
        else:
            abstained += 1
        errors.append(float(np.sqrt(np.mean((held - truth) ** 2))))

    return harmful, abstained, float(np.mean(errors))


def test_enforcing_a7_is_safe_and_useless_on_a_worked_site(base):
    """It accepts nothing, so it is never harmful, and its map is the worst of the three."""
    harmful, abstained, mean_err = _campaign(base, "enforce_a7")

    assert harmful == 0
    assert abstained == 40, "enforcement abstains on every promotion when no model is available"
    assert mean_err > 1.0, (
        f"expected a permanently stale twin, got {mean_err:.3f} m -- if this improved, the "
        "campaign is no longer moving the ground and the comparison is not measuring staleness"
    )


def test_requiring_the_mask_beats_both_alternatives_on_both_axes(base):
    """The result. Zero harmful acceptances AND the best map, which neither alternative manages."""
    cur_harm, _, cur_err = _campaign(base, "current")
    a7_harm, _, a7_err = _campaign(base, "enforce_a7")
    msk_harm, msk_abst, msk_err = _campaign(base, "require_mask")

    assert cur_harm > 0 and a7_harm == 0 and msk_harm == 0
    assert msk_err < cur_err, "the mask policy must beat doing nothing on map error"
    assert msk_err < a7_err, "and it must beat enforcement, which is the finding"
    assert 0 < msk_abst < 40, "it abstains selectively rather than always or never"


def test_enforcement_wins_only_where_the_ground_does_not_move(base):
    """The honest scope of the finding: a crossover, not a blanket claim.

    On a static site abstaining costs nothing, so enforcement wins trivially -- and that is also
    the site whose twin has nothing to do. Once the ground moves on roughly one promotion in twenty,
    the mask policy takes over and the gap widens quickly.
    """
    _, _, a7_static = _campaign(base, "enforce_a7", dig_prob=0.0)
    _, _, msk_static = _campaign(base, "require_mask", dig_prob=0.0)
    assert a7_static <= msk_static, "with nothing changing, abstaining is free"

    _, _, a7_worked = _campaign(base, "enforce_a7", dig_prob=0.5)
    _, _, msk_worked = _campaign(base, "require_mask", dig_prob=0.5)
    assert msk_worked < a7_worked / 10.0, "on a worked site the gap is an order of magnitude"


def test_the_mask_policy_inherits_f6_and_degrades_to_doing_nothing(base):
    """The caveat, measured. Its advantage is only as good as the action log.

    This is why the finding is "the repair reduces to m_eff" rather than "the problem is solved":
    it relocates the dependence from model availability onto log fidelity, which is a weaker
    requirement but not a free one.
    """
    faithful_harm, _, _ = _campaign(base, "require_mask", log_miss=0.0)
    blind_harm, _, _ = _campaign(base, "require_mask", log_miss=1.0)
    current_harm, _, _ = _campaign(base, "current")

    assert faithful_harm == 0
    assert blind_harm > faithful_harm, "an unfaithful log costs harmful acceptances"
    assert blind_harm >= current_harm, "with no log at all it is exactly the current policy"


def test_the_ordering_survives_bursty_spatially_clustered_drift(base):
    """The doubt raised against the finding, checked and NOT upheld.

    The campaign above excavates a fixed patch by a fixed depth at every worked step. Regular drift
    is the friendliest case for a policy that updates often, so the worry was that the measured
    penalty for abstaining was an artefact of it: real excavation is bursty and spatially
    concentrated, with long idle stretches and then a berm going up in one place, and most of an
    abstaining policy's refusals would fall on ground that had not moved.

    It goes the other way. Holding the total volume moved fixed and delivering it in two
    concentrated bursts at four times the depth, the gap *widens* -- because a policy that never
    updates absorbs the whole of a large step and then carries it for the rest of the run, where
    regular drift lets error accumulate gently. The ordering is not an artefact of the drift model,
    and the factor quoted for the regular case is the conservative one.
    """
    _, _, a7_regular = _campaign(base, "enforce_a7")
    _, _, mask_regular = _campaign(base, "require_mask")
    a7_bursty, mask_bursty = _bursty_campaign(base, "enforce_a7"), _bursty_campaign(base, "require_mask")

    assert mask_regular < a7_regular and mask_bursty < a7_bursty
    assert a7_bursty / mask_bursty > a7_regular / mask_regular, (
        "bursty drift should widen the gap, not close it; if this flips, the staleness cost is "
        "sensitive to the drift model and the quoted factor must be re-derived before it is used"
    )


def _bursty_campaign(base: np.ndarray, policy: str, *, steps: int = 40, p_dependent: float = 0.35,
                     seed: int = 5) -> float:
    """Same total volume moved as ``_campaign``, delivered in two bursts on one site."""
    rng = np.random.default_rng(seed)
    truth = base.copy()
    held = base.copy()
    errors: list[float] = []
    burst = {s for start in (8, 24) for s in range(start, start + 5)}

    for t in range(steps):
        if t in burst:
            truth[4:16, 4:16] -= 1.60            # four times the depth, a quarter as often
        dependent = rng.random() < p_dependent
        reading = truth + (rng.normal(0.9, 0.05) if dependent else 0.0)
        evidence = [
            Evidence("agent_a", "observation", reading + rng.normal(0, SIGMA_O * 0.1, truth.shape),
                     SIGMA_O, 1.0),
            Evidence("agent_b", "observation", reading + rng.normal(0, SIGMA_O * 0.1, truth.shape),
                     SIGMA_O, 1.0),
        ]
        mask = np.ones(truth.shape, dtype=bool) if dependent else np.zeros(truth.shape, dtype=bool)
        result = None if policy == "enforce_a7" else evaluate(
            evidence,
            correlation_mask=mask,
            min_effective_support=SUPPORT_THRESHOLD,
        )
        if result is not None and result.decision is Decision.PROMOTE:
            assert result.accepted_state is not None
            held = result.accepted_state.copy()
        errors.append(float(np.sqrt(np.mean((held - truth) ** 2))))
    return float(np.mean(errors))
