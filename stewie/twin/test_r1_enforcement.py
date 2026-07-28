"""[R1] The theorem's premise, enforced on the path where nothing was enforcing it.

The rebuilt result rests entirely on **R1**: the accepted value is a function of the observations
alone. Given R1, ``{promote and harmful}`` is a subset of ``{harmful}`` pointwise and the bound holds
uniformly over any model bias, with no branch partition. The Lean formalisation encodes R1 in the
*type* of the candidate (``Observation -> State``), so it proves the conclusion follows from the
premise. **It cannot check that the implementation satisfies the premise.** That bridge is Python,
and this file is the bridge.

Established by mutation rather than by reading, on 2026-07-28:

* Blending 1% of the physics prediction into the accepted value is caught. Eight tests fail,
  including ``test_every_promoted_value_is_the_same_observation_aggregate`` across physics bias.
* **Using the physics prediction to fill cells no sensor observed is NOT caught.** The whole twin
  suite passed, 302 of 302, with the model supplying values for unobserved ground.

The second is the one that matters, for three reasons. It is the *tempting* mistake -- the map has
holes, a model is available, so fill them. It is on the **partial-coverage path**, which F8
established is the only path a real sensor produces, every other measurement in this benchmark
having been taken at 100% coverage. And it was already a written requirement: the rebuild record
says "unobserved cells are not silently filled" and "never fill missing cells as part of the
theorem", twice, with nothing testing either sentence.

That is this project's signature defect for the third time: a property stated in prose, relied on by
a proof, and unenforced in code. The first let a flat plane 1559 m from the surface be promoted
because "every accepted state is an observation" was a comment rather than a check. The second let a
raw count stand in for an independence test.

Real Haworth LOLA terrain; coverage patterns are controlled fault injection.
"""

from __future__ import annotations

import numpy as np
import pytest

from stewie.twin.promotion import Decision, Evidence, evaluate

SIGMA_O = 0.05
SIGMA_P = 0.08

#: Wildly different physical predictions. R1 says none of them may reach the accepted value.
PHYSICS_BIASES_M = [0.0, 0.7, -0.7, 50.0, -50.0, 1.0e6]


@pytest.fixture(scope="module")
def truth() -> np.ndarray:
    dem = np.fromfile("samples/lunar_dem/haworth_10km_5m/heightmap.rf32", dtype=np.float32)
    n = int(np.sqrt(dem.size))
    return dem.reshape(n, n)[1000:1032, 1000:1032].astype(float)


@pytest.fixture(scope="module")
def partial_observations(truth: np.ndarray) -> list[Evidence]:
    """Three readings with different holes, leaving a strip that no sensor saw.

    Rows 0-2 are seen by nobody, rows 3-5 and 30-31 by two sources, rows 6-29 by all three. So
    there is a genuinely unobserved strip for the anti-fill gate to test, and the observed region
    still varies in multiplicity.

    **Every observed cell is seen by at least two sources on purpose.** The override branch requires
    two distinct dependency components at every promoted cell, so a single cell with one observer
    makes the whole patch un-overridable and every biased model abstains -- which leaves the
    invariance test with one datum and nothing to compare. Correct behaviour, conservative in the
    right direction, and easy to design a fixture past by accident.
    """
    rng = np.random.default_rng(3)
    a = truth + rng.normal(0.0, SIGMA_O, truth.shape)
    a[:3, :] = np.nan
    b = truth + rng.normal(0.0, SIGMA_O, truth.shape)
    b[:3, :] = np.nan
    c = truth + rng.normal(0.0, SIGMA_O, truth.shape)
    c[:6, :] = np.nan
    c[30:, :] = np.nan
    return [Evidence("agent_a", "observation", a, SIGMA_O),
            Evidence("agent_b", "observation", b, SIGMA_O),
            Evidence("agent_c", "observation", c, SIGMA_O)]


def _expected_aggregate(observations: list[Evidence]) -> tuple[np.ndarray, np.ndarray]:
    """The per-cell mean over exactly the sources that saw each cell. Physics-free by construction."""
    stack = np.stack([np.asarray(o.values, dtype=float) for o in observations])
    seen = np.isfinite(stack)
    mask = seen.any(axis=0)
    total = np.where(seen, stack, 0.0).sum(axis=0)
    count = seen.sum(axis=0)
    with np.errstate(invalid="ignore"):
        mean = np.where(mask, total / np.maximum(count, 1), np.nan)
    return mean, mask


@pytest.mark.parametrize("bias_m", PHYSICS_BIASES_M)
def test_physics_never_fills_a_cell_no_sensor_observed(truth, partial_observations, bias_m):
    """The gate that was missing. A model may not supply ground truth for unseen ground."""
    _, expected_mask = _expected_aggregate(partial_observations)
    physics = Evidence("terramech", "physics", truth + bias_m, SIGMA_P)

    result = evaluate([*partial_observations, physics],
                      correlation_mask=np.zeros(truth.shape, dtype=bool),
                      min_effective_support=1.0)

    if result.decision is not Decision.PROMOTE:
        return                      # refusing is always permitted; filling is not
    assert result.accepted_mask is not None and result.accepted_state is not None
    assert np.array_equal(result.accepted_mask, expected_mask), (
        "coverage changed: the accepted patch claims cells the sensors did not observe"
    )
    unobserved = ~expected_mask
    assert unobserved.any(), "the fixture must leave some cell unobserved or this proves nothing"
    assert np.isnan(result.accepted_state[unobserved]).all(), (
        "an unobserved cell carries a value; something filled it, and the only thing available "
        "to fill it with is the model"
    )


@pytest.mark.parametrize("bias_m", PHYSICS_BIASES_M)
def test_observed_cells_equal_the_observation_only_aggregate(truth, partial_observations, bias_m):
    """R1 proper, under partial coverage: each cell is the mean of the sources that saw it."""
    expected, expected_mask = _expected_aggregate(partial_observations)
    physics = Evidence("terramech", "physics", truth + bias_m, SIGMA_P)

    result = evaluate([*partial_observations, physics],
                      correlation_mask=np.zeros(truth.shape, dtype=bool),
                      min_effective_support=1.0)

    if result.decision is not Decision.PROMOTE:
        return
    assert result.accepted_state is not None
    np.testing.assert_array_equal(result.accepted_state[expected_mask], expected[expected_mask])


def test_the_accepted_bytes_are_identical_across_every_physical_model(truth, partial_observations):
    """The strongest form: not merely observation-derived, but invariant to what physics says.

    A model that shifted the value by a hair would satisfy a tolerance-based check and still break
    the theorem, so this compares raw bytes over the observed region.
    """
    promoted = {}
    for bias_m in PHYSICS_BIASES_M:
        physics = Evidence("terramech", "physics", truth + bias_m, SIGMA_P)
        result = evaluate([*partial_observations, physics],
                          correlation_mask=np.zeros(truth.shape, dtype=bool),
                          min_effective_support=1.0)
        if result.decision is Decision.PROMOTE:
            assert result.accepted_state is not None and result.accepted_mask is not None
            promoted[bias_m] = result.accepted_state[result.accepted_mask].tobytes()

    assert len(promoted) >= 2, (
        f"only {len(promoted)} biases promoted; the invariance claim needs at least two to compare"
    )
    assert len(set(promoted.values())) == 1, (
        "the accepted value differs between physical models, which is exactly what R1 forbids"
    )


def test_removing_physics_entirely_changes_nothing_about_the_value(truth, partial_observations):
    """If physics is only a veto, deleting it can change the decision but never the value."""
    with_physics = evaluate([*partial_observations,
                             Evidence("terramech", "physics", truth, SIGMA_P)],
                            correlation_mask=np.zeros(truth.shape, dtype=bool),
                            min_effective_support=1.0)
    without = evaluate(list(partial_observations),
                       correlation_mask=np.zeros(truth.shape, dtype=bool),
                       min_effective_support=1.0)

    assert with_physics.decision is Decision.PROMOTE and without.decision is Decision.PROMOTE
    assert with_physics.accepted_state is not None and without.accepted_state is not None
    np.testing.assert_array_equal(with_physics.accepted_mask, without.accepted_mask)
    assert (with_physics.accepted_state[with_physics.accepted_mask].tobytes()
            == without.accepted_state[without.accepted_mask].tobytes())
