"""[GATE2] The rule must gate the thing it promotes, and the verdict must not depend on list order.

Three defects found by an external mathematical review of the construction, all confirmed by
running them before anything was changed. They are implementation defects rather than errors in the
measurements: every experiment in the suite passes ``obs[0].values`` as the candidate and lists its
evidence in a fixed order, so the reported numbers stand. What was wrong is that the function
permitted -- and the theorem described -- something the code did not enforce.

**1. The candidate was never examined.** It was read for its shape and its finiteness and for
nothing else. Every branch reasons about the *evidence*: observation against physics, observation
against observation. Nothing ever asked what was being promoted. Measured before the fix: a flat
plane at zero, 1559 m from the real surface, was PROMOTED on three good readings of Haworth,
because the readings agreed with each other and with the model.

This matters to the theorem and not only to the code. The soundness argument runs "every accepted
state is an observation, so its error is governed by sigma_o and the model bias never enters". That
sentence was true of the experiments and false of the function they call.

**2. Only the first two observations were compared.** ``obs[0]`` against ``obs[1]``, in a list with
no defined order. On ``[bad, bad, good]`` two of the six permutations promoted a 0.900 m error,
because the two faulty readings happened to be adjacent and agreed with each other. The same
evidence set gave different verdicts depending on how it was written down.

**3. Only the first physical model was consulted.** A second model was silently ignored, and which
one counted depended on list order. Physics may only veto, so every model is read now and any
disagreement is a veto: consulting fewer models can only miss an objection, never invent one, which
is what keeps the veto-only property intact.

Real Haworth LOLA terrain throughout; the faults are controlled injection.
"""

from __future__ import annotations

import itertools

import numpy as np
import pytest

from stewie.twin.promotion import Decision, Evidence, evaluate

SIGMA_O = 0.05
SIGMA_P = 0.08


@pytest.fixture(scope="module")
def truth() -> np.ndarray:
    dem = np.fromfile("samples/lunar_dem/haworth_10km_5m/heightmap.rf32", dtype=np.float32)
    n = int(np.sqrt(dem.size))
    return dem.reshape(n, n)[1000:1032, 1000:1032].astype(float)


@pytest.fixture(scope="module")
def good_evidence(truth: np.ndarray) -> list[Evidence]:
    rng = np.random.default_rng(1)
    obs = [Evidence(f"agent_{i}", "observation", truth + rng.normal(0, SIGMA_O, truth.shape),
                    SIGMA_O, 1.0) for i in range(3)]
    return [*obs, Evidence("terramech", "physics", truth + rng.normal(0, SIGMA_P, truth.shape),
                           SIGMA_P, 1.0)]


@pytest.mark.parametrize("fabricate", [
    pytest.param(lambda t, r: t + 50.0, id="fifty_metres_high"),
    pytest.param(lambda t, r: np.zeros_like(t), id="flat_plane_at_zero"),
    pytest.param(lambda t, r: r.normal(0.0, 100.0, t.shape), id="pure_noise"),
    pytest.param(lambda t, r: t * -1.0, id="inverted_surface"),
])
def test_a_fabricated_candidate_cannot_ride_on_good_evidence(truth, good_evidence, fabricate):
    """The severe one. Before the fix every one of these was PROMOTE."""
    candidate = fabricate(truth, np.random.default_rng(99))
    result = evaluate(candidate, good_evidence, min_effective_support=2.0)

    assert result.decision is Decision.REJECT, (
        f"a candidate {float(np.sqrt(np.mean((candidate - truth) ** 2))):.1f} m from the surface "
        "was accepted; the rule is not gating what it promotes"
    )
    assert "not any of the offered observations" in result.reason


def test_the_real_observation_is_still_promoted(truth, good_evidence):
    """The fix must not close the door on the case the rule exists to serve."""
    result = evaluate(good_evidence[0].values, good_evidence, min_effective_support=2.0)
    assert result.decision is Decision.PROMOTE


def test_the_verdict_does_not_depend_on_the_order_of_the_evidence(truth):
    """Two faulty readings agreeing with each other must not out-vote a dissenting good one."""
    rng = np.random.default_rng(2)
    shared = 0.9
    bad_a = Evidence("bad_a", "observation", truth + shared + rng.normal(0, 0.005, truth.shape),
                     SIGMA_O, 1.0)
    bad_b = Evidence("bad_b", "observation", truth + shared + rng.normal(0, 0.005, truth.shape),
                     SIGMA_O, 1.0)
    good = Evidence("good", "observation", truth + rng.normal(0, SIGMA_O, truth.shape),
                    SIGMA_O, 1.0)
    physics = Evidence("terramech", "physics", truth + rng.normal(0, SIGMA_P, truth.shape),
                       SIGMA_P, 1.0)

    verdicts = set()
    for order in itertools.permutations([bad_a, bad_b, good]):
        result = evaluate(order[0].values, [*order, physics], min_effective_support=2.0)
        verdicts.add(result.decision)

    assert verdicts == {Decision.ABSTAIN}, (
        f"got {sorted(v.name for v in verdicts)}: a dissenting observation must withhold "
        "corroboration whatever position it occupies in the list"
    )


def test_every_physical_model_gets_a_veto_not_only_the_first(truth):
    """A model that objects must be heard wherever it sits in the list."""
    rng = np.random.default_rng(3)
    obs = [Evidence(f"agent_{i}", "observation", truth + 0.9 + rng.normal(0, 0.005, truth.shape),
                    SIGMA_O, 1.0) for i in range(2)]
    agreeing = Evidence("colluding", "physics", truth + 0.9, SIGMA_P, 1.0)
    objecting = Evidence("terramech", "physics", truth + rng.normal(0, SIGMA_P, truth.shape),
                         SIGMA_P, 1.0)

    for order in ([agreeing, objecting], [objecting, agreeing]):
        result = evaluate(obs[0].values, [*obs, *order], min_effective_support=2.0)
        assert result.detail["physics_disagrees"], (
            "the objecting model must register a veto regardless of list position"
        )


def test_the_experiments_were_using_the_rule_correctly_all_along(truth, good_evidence):
    """Why the measurements stand: the sweeps always promote an observation they actually offered.

    This is the check that separates "the numbers are wrong" from "the API permitted something the
    numbers never did". It is the second, and this test is what pins it.
    """
    for source in (e for e in good_evidence if e.kind == "observation"):
        result = evaluate(source.values, good_evidence, min_effective_support=2.0)
        assert result.decision is not Decision.REJECT, (
            f"offering {source.source} as the candidate must remain admissible"
        )
