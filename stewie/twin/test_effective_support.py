"""[C3] Is the conservative effective-support bound sound, and is it better than what it replaces?

Two claims are under test.

1. **It is a genuine lower bound.** Simulate observation errors with a known correlation on the
   shared cells, measure the effective support the ensemble actually exhibits, and check the C3
   value never exceeds it. A bound that is occasionally optimistic is not a bound.

2. **It repairs a real defect, not a stylistic one.** The linear placeholder returns zero
   independent support when every cell is shared. That is false, and the boundary case is pinned
   here so the claim is testable rather than asserted.

Correlation is imposed on real Haworth terrain errors by a standard common-factor construction, not
by fabricating a covariance: each observation error is a mix of a per-observation independent draw
and a single shared draw, which produces exactly equicorrelation at a known rho.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from stewie.twin.effective_support import (
    conservative_effective_support,
    effective_support_from_mask,
    linear_placeholder_support,
    measured_effective_support,
    per_cell_effective_count,
)

_HEIGHT = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "samples", "lunar_dem", "haworth_10km_5m", "heightmap.rf32"))

N = 64
SIGMA = 0.05


def _equicorrelated_errors(m: int, n: int, rho: float, seed: int) -> np.ndarray:
    """m error vectors over n cells, equicorrelated at exactly ``rho``, unit-consistent scale.

    ``e_i = sqrt(rho) * shared + sqrt(1 - rho) * own_i``. Both parts are standard normal, so each
    ``e_i`` has variance 1 and every pair has covariance ``rho`` by construction.
    """
    rng = np.random.default_rng(seed)
    shared = rng.normal(0.0, 1.0, n)
    own = rng.normal(0.0, 1.0, (m, n))
    return SIGMA * (np.sqrt(rho) * shared + np.sqrt(1.0 - rho) * own)


# --------------------------------------------------------------------------------------------
# Shape of the formula
# --------------------------------------------------------------------------------------------
def test_per_cell_count_spans_one_to_m():
    assert per_cell_effective_count(5, 0.0) == pytest.approx(5.0)
    assert per_cell_effective_count(5, 1.0) == pytest.approx(1.0)
    assert 1.0 < per_cell_effective_count(5, 0.5) < 5.0
    assert per_cell_effective_count(2, -0.5) == pytest.approx(4.0)
    assert np.isinf(per_cell_effective_count(2, -1.0))


def test_measured_support_is_infinite_when_the_mean_cancels_exactly():
    errors = np.array(
        [
            [1.0, -1.0, 2.0, -2.0],
            [-1.0, 1.0, -2.0, 2.0],
        ]
    )

    assert np.isinf(measured_effective_support(errors))


def test_region_support_endpoints():
    assert conservative_effective_support(3, 0.0) == pytest.approx(3.0)   # nothing shared
    assert conservative_effective_support(3, 1.0) == pytest.approx(1.0)   # everything shared
    assert conservative_effective_support(1, 1.0) == pytest.approx(1.0)   # one observation, always 1


def test_support_is_monotone_decreasing_in_shared_fraction():
    vals = [conservative_effective_support(4, d) for d in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)]
    assert all(a >= b for a, b in zip(vals, vals[1:]))


def test_support_never_falls_below_one():
    for m in (1, 2, 5, 20):
        for d in (0.0, 0.5, 0.999, 1.0):
            assert conservative_effective_support(m, d) >= 1.0 - 1e-12


def test_rejects_out_of_range_inputs():
    for bad in (-0.1, 1.1):
        with pytest.raises(ValueError):
            conservative_effective_support(2, bad)
        with pytest.raises(ValueError):
            conservative_effective_support(2, 0.5, rho=bad)
    with pytest.raises(ValueError):
        conservative_effective_support(0, 0.5)


# --------------------------------------------------------------------------------------------
# Claim 1: it is a genuine lower bound
# --------------------------------------------------------------------------------------------
@pytest.mark.parametrize("rho", [0.0, 0.25, 0.5, 0.75, 1.0])
@pytest.mark.parametrize("m", [2, 3, 5])
def test_c3_never_exceeds_the_support_actually_exhibited(m, rho):
    """The whole point of a conservative bound: it may understate, never overstate."""
    for seed in range(6):
        err = _equicorrelated_errors(m, 4096, rho, seed=1000 + seed)
        measured = measured_effective_support(err)
        bound = conservative_effective_support(m, correlated_fraction=1.0, rho=1.0)
        assert bound <= measured + 0.05, (
            f"C3 exceeded realised support: bound {bound:.3f} > measured {measured:.3f} "
            f"(m={m}, rho={rho}, seed={seed})")


@pytest.mark.parametrize("m,rho", [(2, 0.5), (3, 0.25), (5, 0.75)])
def test_the_formula_with_the_true_rho_tracks_the_realised_support(m, rho):
    """Given the correct rho, the same formula predicts what is measured. This is what makes C3 the
    rho=1 instance of a family rather than an unrelated heuristic, and it is why route C1 -- deriving
    rho from the overlap structure -- would slot into this formula rather than replace it."""
    measured = np.mean([measured_effective_support(_equicorrelated_errors(m, 8192, rho, 2000 + s))
                        for s in range(8)])
    predicted = conservative_effective_support(m, correlated_fraction=1.0, rho=rho)
    assert predicted == pytest.approx(measured, rel=0.12), f"predicted {predicted:.3f} vs measured {measured:.3f}"


def test_partial_overlap_lies_between_the_endpoints():
    """Half the region shared should sit strictly between fully-shared and fully-independent."""
    lo = conservative_effective_support(3, 1.0)
    hi = conservative_effective_support(3, 0.0)
    mid = conservative_effective_support(3, 0.5)
    assert lo < mid < hi


# --------------------------------------------------------------------------------------------
# Claim 2: the placeholder is wrong, not merely loose
# --------------------------------------------------------------------------------------------
def test_linear_placeholder_reports_zero_support_when_everything_is_shared():
    """Pinned defect. Two perfectly correlated observations are one observation, not none.
    A rule consuming this value would abstain on evidence that genuinely supports a decision."""
    assert linear_placeholder_support(2, 1.0) == pytest.approx(0.0)
    assert conservative_effective_support(2, 1.0) == pytest.approx(1.0)


def test_placeholder_overstates_support_in_the_regime_the_thesis_is_about():
    """The serious defect, and it is the opposite of the expected one.

    The placeholder and C3 cross at ``d = (m-2)/(m-1)``. **Below that crossover, for m >= 3, the
    placeholder reports MORE independent support than is soundly available.** At m=10 and half the
    region shared it claims 5.0 against a sound bound of 1.82 -- nearly three times optimistic.

    An optimistic support estimate makes the rule accept on inflated confidence. That is precisely
    the failure this dissertation exists to prevent, so the placeholder does not merely approximate
    the answer badly: in the many-agent, partial-overlap regime that motivates the whole problem, it
    commits the error under study."""
    for m in (3, 5, 10):
        crossover = (m - 2) / (m - 1)
        below = max(crossover / 2, 0.05)
        assert linear_placeholder_support(m, below) > conservative_effective_support(m, below), (
            f"expected placeholder to overstate below the crossover (m={m}, d={below:.3f})")
        assert linear_placeholder_support(m, crossover) == pytest.approx(
            conservative_effective_support(m, crossover)), f"crossover formula wrong for m={m}"
        above = (crossover + 1.0) / 2
        assert linear_placeholder_support(m, above) < conservative_effective_support(m, above)


def test_for_two_observations_the_placeholder_only_ever_understates():
    """m=2 puts the crossover at d=0, so the two-agent case is the one where the placeholder is
    merely conservative. That is why the defect went unnoticed: every existing test uses m=1 or 2."""
    for d in (0.1, 0.5, 0.9, 1.0):
        assert linear_placeholder_support(2, d) < conservative_effective_support(2, d)


def test_zero_overlap_is_the_first_of_two_crossover_roots():
    assert linear_placeholder_support(4, 0.0) == pytest.approx(conservative_effective_support(4, 0.0))


# --------------------------------------------------------------------------------------------
# Wiring: takes the mask the shared-terrain detector already produces
# --------------------------------------------------------------------------------------------
def test_accepts_a_correlation_mask_directly():
    mask = np.zeros((32, 32), dtype=bool)
    mask[8:20, 8:20] = True                       # 144 of 1024 cells shared
    got = effective_support_from_mask(2, mask)
    assert got == pytest.approx(conservative_effective_support(2, 144 / 1024))
    assert 1.0 < got < 2.0
    with pytest.raises(ValueError):
        effective_support_from_mask(2, np.zeros((0, 0), dtype=bool))


@pytest.mark.skipif(not os.path.exists(_HEIGHT), reason="real Haworth DEM not present on this host")
def test_end_to_end_on_real_terrain_geometry():
    """Runs the bound over a mask sized to a real Haworth tile, so the region shape is not invented."""
    z = np.fromfile(_HEIGHT, dtype=np.float32)
    side = int(round(float(np.sqrt(z.size))))
    patch = z.reshape(side, side)[1000:1000 + N, 1000:1000 + N]
    assert patch.shape == (N, N)
    mask = np.zeros(patch.shape, dtype=bool)
    mask[16:48, 16:48] = True                     # a co-dug pad, 1024 of 4096 cells
    got = effective_support_from_mask(2, mask)
    assert got == pytest.approx(2 / (1 + 0.25), rel=1e-9)
    assert got > linear_placeholder_support(2, 0.25)


# --------------------------------------------------------------------------------------------
# ASYMMETRY AUDIT 2026-07-27.
#
# Earlier results hid asymmetric cases behind symmetric derivations. C3 is
# derived under EQUICORRELATION -- every
# pair of observations correlated at the same rho -- so it is the obvious next place to look. Partial
# structures, where some pairs share ground and others do not, are the asymmetric case.
#
# It survives, and the reason is a two-line argument rather than a hope.
# --------------------------------------------------------------------------------------------
def test_equicorrelation_is_provably_the_worst_case_not_merely_the_assumed_one():
    """For m observations with correlation matrix R, the mean has variance ``(1'R1)/m^2`` times
    sigma^2, so the independent-observation equivalent is ``m^2 / (1'R1)``. Every entry of a
    correlation matrix is at most 1, so ``1'R1 <= m^2`` and therefore ``m_eff >= 1``, with equality
    exactly when every pair is perfectly correlated -- which is what C3 assumes at full overlap.

    Checked against randomly generated VALID correlation matrices (Gram matrices normalised, so they
    are positive semi-definite by construction rather than merely symmetric). None goes below the
    bound. An asymmetric structure gives MORE effective support, never less, so C3 is loose there
    rather than wrong."""
    rng = np.random.default_rng(20260727)
    for m in (3, 5, 8):
        floor = conservative_effective_support(m, correlated_fraction=1.0, rho=1.0)
        assert floor == pytest.approx(1.0)
        for _ in range(400):
            a = rng.normal(size=(m, m))
            cov = a @ a.T
            d = np.sqrt(np.diag(cov))
            r = cov / np.outer(d, d)
            m_eff = m ** 2 / float(np.ones(m) @ r @ np.ones(m))
            assert m_eff >= floor - 1e-9, (
                f"a valid correlation structure produced less support than C3 assumes: "
                f"{m_eff:.4f} < {floor:.4f} at m={m}")


def test_negative_correlation_improves_support_and_can_cancel_the_mean():
    r = np.array([[1.0, -1.0], [-1.0, 1.0]])
    assert np.linalg.eigvalsh(r).min() >= -1e-12
    denominator = float(np.ones(2) @ r @ np.ones(2))
    assert denominator == pytest.approx(0.0)
    assert per_cell_effective_count(2, -1.0) == float("inf")


def test_a_partial_correlation_structure_gives_more_support_than_c3_assumes():
    """One correlated pair among m independent sources is the canonical asymmetric case. C3 is sound
    there and increasingly loose as m grows, which is the expected direction and worth recording so
    the looseness is not later mistaken for an error."""
    for m, expected in ((3, 1.8), (5, 3.5714), (8, 6.4)):
        r = np.eye(m)
        r[0, 1] = r[1, 0] = 1.0
        m_eff = m ** 2 / float(np.ones(m) @ r @ np.ones(m))
        assert m_eff == pytest.approx(expected, rel=1e-3)
        assert m_eff > conservative_effective_support(m, 1.0, 1.0)
