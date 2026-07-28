"""[GATE2] No-model operation after the accepted-state repair.

Physics availability changes operational protection and availability, but it
is not a separate branch of the repaired model-bias theorem: every promotion
still returns the same observation mean.

These tests establish two narrower facts on real Haworth terrain with a
labelled common-mode fault. Unknown dependency produces abstention. An
explicit but false all-independent graph can admit an arbitrarily large common
fault, while a faithful dependency mask refuses it. The latter experiment
violates marginal calibration deliberately; it is an identifiability and graph
fidelity limit, not a counterexample to the conditional theorem.
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
    """Controlled common observation error applied to two graph-linked sources."""
    reading = truth + common_m
    return [Evidence("agent_a", "observation", reading + rng.normal(0, 0.005, truth.shape),
                     SIGMA_O, 1.0),
            Evidence("agent_b", "observation", reading + rng.normal(0, 0.005, truth.shape),
                     SIGMA_O, 1.0)]


def test_operational_reasons_distinguish_three_physics_availability_cases(truth):
    """Agreement, override, and no-model promotion report distinct reasons."""
    rng = np.random.default_rng(3)
    good = truth + rng.normal(0, SIGMA_O * 0.1, truth.shape)
    obs = [Evidence("a", "observation", good, SIGMA_O, 1.0),
           Evidence("b", "observation", truth + rng.normal(0, SIGMA_O * 0.1, truth.shape),
                    SIGMA_O, 1.0)]

    independent = np.zeros(truth.shape, dtype=bool)
    agreed = evaluate(
        [
            *obs,
            Evidence(
                "terramech",
                "physics",
                truth + rng.normal(0, 0.08, truth.shape),
                0.10,
                1.0,
            ),
        ],
        correlation_mask=independent,
        min_effective_support=2.0,
    )
    overruled = evaluate(
        [*obs, Evidence("terramech", "physics", truth + 5.0, 0.10, 1.0)],
        correlation_mask=independent,
        min_effective_support=2.0,
    )
    unvetoed = evaluate(
        obs,
        correlation_mask=independent,
        min_effective_support=2.0,
    )

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
    result = evaluate(ev, min_effective_support=2.0)

    assert result.decision is Decision.ABSTAIN
    assert result.detail["n_physics"] == 0
    assert result.detail["veto_available"] is False
    assert "dependency relation was not supplied" in result.reason
    assert result.residual_rms_m == 0.0 and result.tolerance_m == 0.0


def test_a_log_that_falsely_claims_independence_offers_no_bound(truth):
    """With unbounded common error, a false graph supplies no worst-case bound."""
    worst_accepted = 0.0
    independent = np.zeros(truth.shape, dtype=bool)
    for common in (0.30, 0.90, 2.0, 10.0):
        rng = np.random.default_rng(11)
        harmful = 0
        for _ in range(20):
            ev = _shared_error_evidence(truth, common, rng)
            result = evaluate(
                ev,
                correlation_mask=independent,
                min_effective_support=2.0,
            )
            assert result.accepted_state is not None
            err = float(np.sqrt(np.mean((result.accepted_state - truth) ** 2)))
            if result.decision is Decision.PROMOTE and err > TAU_M:
                harmful += 1
                worst_accepted = max(worst_accepted, err)
        assert harmful == 20, (
            f"common error {common} m: expected the unprotected regime to accept every trial, "
            f"got {harmful}/20 -- if this drops, some mechanism started working and the "
            "characterisation of 4b needs revisiting"
        )
    assert worst_accepted > 10.0, "a 10 m error was accepted; the regime has no bound at all"


def test_a_faithful_mask_stops_the_no_model_common_fault(truth):
    """Graph support stops every sampled common fault without physics."""
    mask = np.zeros(truth.shape, dtype=bool)
    mask.flat[:mask.size // 4] = True          # a quarter of cells worked by both agents

    for common in (0.30, 0.90, 10.0):
        rng = np.random.default_rng(11)
        for _ in range(20):
            ev = _shared_error_evidence(truth, common, rng)
            result = evaluate(
                ev,
                correlation_mask=mask,
                min_effective_support=2.0,
            )
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
    assert evaluate(
        ev,
        correlation_mask=none_correlated,
        min_effective_support=2.0,
    ).decision is Decision.PROMOTE

    one_cell = np.zeros(truth.shape, dtype=bool)
    one_cell.flat[0] = True
    result = evaluate(
        ev,
        correlation_mask=one_cell,
        min_effective_support=2.0,
    )
    assert result.decision is Decision.ABSTAIN
    assert result.effective_n < 2.0


def test_the_platform_can_refuse_physics_while_the_rule_supports_no_model_operation():
    """Pin the model-availability seam without turning it into a theorem premise.

    The platform's own governance contract refuses to resolve a physics model for a LIVE mission
    when the model has no validated profile for the body in question -- deliberately, fail-closed,
    so an unvalidated model cannot drive real hardware. Outside the gravity-loaded Bekker regime
    that refusal is the designed behaviour, not an error.

    The repaired theorem does not assume model availability: no-model
    promotions still return the same observation mean. This test retains the
    operational fact that the veto may be unavailable, so availability and
    graph-fidelity policy must be evaluated explicitly rather than smuggled
    into a residual branch.
    """
    from stewie.contracts.physics_model_control import PhysicsModelRefused, resolve_live_backend

    resolve_live_backend(body="moon")          # in regime: a model is available

    for body in ("bennu", "phobos"):
        with pytest.raises(PhysicsModelRefused):
            resolve_live_backend(body=body)
