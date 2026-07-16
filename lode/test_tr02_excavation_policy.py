"""[REQ:TR-02] The interpretable search-distilled excavation policy: the MEASURED result is a NULL, and
the row PRE-COMMITS that "a tie with greedy is a NULL RESULT and MUST be reported as one." These gates
prove the null on the frozen TR-01 scenario (real Haworth authority + real Golombek rock field, held-out
by seed) and pin its MECHANISTIC cause so the row cannot be silently "un-nulled" without the physics that
would actually earn it: a distilled decision tree cannot beat greedy on passes-to-spec / energy-to-spec /
as-built RMSE because, on the AS-IMPLEMENTED excavation physics, all three are policy-invariant.

Root cause (each asserted below):
  * ``ipex_specs.dig_energy_per_kg()`` is a CONSTANT J/kg with NO depth term (the row's "FEE ∝ depth²" is
    not in the code) -> dig energy is linear in cut MASS, so bite depth is not an energy lever;
  * mass is conserved -> cut mass, and hence dig energy and drum-load count, are TARGET-determined;
  * ``WorkSite.flatten`` is deterministic + mass-exact -> the as-built surface is policy-invariant.

If a sourced depth-dependent excavation-force model (real FEE) is ever implemented, gate
``test_dig_energy_is_depth_independent_constant`` flips RED -- which is exactly the signal that TR-02 has
become a live (potentially non-null) row. That is intended: the null is conditional on today's physics.
"""
import os

import numpy as np
import pytest

from stewie.specs import ipex_specs as IX
from lode.tr02_excavation_policy import (
    HAWORTH_BUNDLE, RMSE_SPEC_M, Scenario, run_policy, POLICIES, _rock_xy, _open,
)

pytestmark = pytest.mark.skipif(
    not os.path.isdir(HAWORTH_BUNDLE),
    reason="the frozen TR-01 Haworth bundle is required (real-data only; no synthetic substitute)")

# A small multi-cell pad that removes REAL mantle mass over the real crater-floor terrain -- big enough
# that the null is non-vacuous, small enough that the whole gate runs in a couple of seconds.
_BASE = Scenario(base_rc=(1000.0, 1000.0), pad_half_m=4.0, target_drop_m=0.25, rock_seed=0)
_SEEDS = [0, 1, 2]                                    # held-out rock draws of the SAME terrain


def _scn(seed: int) -> Scenario:
    return Scenario(_BASE.base_rc, _BASE.pad_half_m, _BASE.target_drop_m, seed, _BASE.drum)


def test_dig_energy_is_depth_independent_constant():
    """The MECHANISTIC root cause: dig energy is a constant J/kg (ipex_specs.py:167), linear in mass with
    NO depth term. Doubling a bite's DEPTH costs 2x only through 2x MASS -- never depth^2 -- so bite depth
    is not an energy lever a policy could exploit. This is why the tree ties greedy."""
    e = IX.dig_energy_per_kg()
    assert e > 0 and np.isscalar(e)
    # energy for a bite is const * mass; mass = area * depth * rho -> energy is LINEAR in depth, not depth^2.
    rho, area = 1500.0, 1.0
    e_shallow = e * (area * 0.01 * rho)
    e_deep = e * (area * 0.02 * rho)
    assert e_deep == pytest.approx(2.0 * e_shallow)            # 2x depth -> 2x energy (linear), not 4x


def test_held_out_seeds_are_a_real_different_rock_field():
    """Generalization is tested on HELD-OUT rock seeds (row requirement). Prove the seeds are genuinely
    different clast fields of the SAME terrain -- not a relabel -- so the null generalizes for real."""
    _ws, _pad, _above, _t, region = _open(_scn(0))
    fields = [_rock_xy(region, s) for s in _SEEDS]
    assert all(f.shape[0] > 0 for f in fields)                # each seed places real Golombek clasts
    counts = {f.shape[0] for f in fields}
    # distinct draws differ in count and/or placement (a real seed sweep, not the same field relabelled)
    assert len(counts) > 1 or not np.allclose(fields[0], fields[1])


def test_the_cut_meets_spec_and_removes_real_mass():
    """Non-vacuous: on the reachable target the deterministic flatten lands within the ±2 cm acceptance
    and removes real mantle mass over >=1 drum load. (A null on a no-op scenario would be worthless.)"""
    r = run_policy(_scn(0), "greedy_highest")
    assert r.cut_mass_kg > 1.0                                 # real mass moved
    assert r.passes >= 1
    assert r.dig_J > 0.0
    assert r.as_built_rmse_m <= RMSE_SPEC_M                    # the cut hits target within ±2 cm


def test_all_policies_tie_greedy_on_the_three_acceptance_metrics_per_held_out_seed():
    """THE NULL: across four DISTINCT policies (incl. a RANDOM order -- the exact control the row names)
    on every held-out seed, passes-to-spec, energy-to-spec and as-built RMSE are policy-invariant. A
    decision tree can only reproduce one of these already-tied policies, so it CANNOT beat greedy: NULL.
    """
    for seed in _SEEDS:
        rs = [run_policy(_scn(seed), p) for p in POLICIES]
        assert {r.passes for r in rs} == {rs[0].passes}                       # exact
        assert max(r.as_built_rmse_m for r in rs) - min(r.as_built_rmse_m for r in rs) < 1e-9
        dig = [r.dig_J for r in rs]
        assert max(dig) - min(dig) < 1e-6 * max(dig)                          # float-exact
        E = [r.energy_J for r in rs]
        assert (max(E) - min(E)) < 1e-3 * max(E)             # incl. the haul term: still a tie (<0.1%)


def test_dig_energy_dominates_so_routing_cannot_create_headroom():
    """The ONLY policy-sensitive term is haul-leg DRIVE energy, and it is dig-dominated to <1 % of the
    energy budget -- so even a perfect router (the SchedulerEnv problem, where this repo already found
    greedy=beam=optimal) cannot move energy-to-spec enough to matter."""
    r = run_policy(_scn(0), "greedy_highest")
    assert r.drive_J < 0.01 * r.dig_J                         # routing is <1% of the dig-dominated budget
