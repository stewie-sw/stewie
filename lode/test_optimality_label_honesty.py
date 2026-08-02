"""SR-15 [REQ:AL1]: the optimality label must name the solver that ACTUALLY ran.

`brute` and `held_karp` are operator-selectable (planAuthor.js:105) but silently degrade to
LK-from-nearest past their caps. The assembly layer labelled the plan from the REQUESTED algorithm and
corrected only the `auto` case, so an explicit request kept its exact label after falling back.

Measured by the 2026-07-28 review on a real 20-trip mission:

    algorithm='brute'  -> optimality='exact', objective_exact=True, resolved_algorithm='brute',
                          and ZERO warnings.  BRUTE_MAX_TRIPS=7, so 20! was never enumerated.
    algorithm='held_karp' + objective='distance' at 20 trips -> optimality='distance-exact'
                          for what was a plain NN + 2-opt run.

That label is rendered verbatim to the operator (rehearse_render.js:59) and carried into REHEARSED
evidence (lode/resync.py:115), so it is a claim the mission record inherits.

The existing tests exercised in-cap sizes only (test_mission_planner.py:1901, :1917), which is why the
whole above-cap branch went unnoticed.

Run: <venv>/bin/python -m pytest lode/test_optimality_label_honesty.py -q
"""
from __future__ import annotations

import pytest

from lode.planner_optimize import BRUTE_MAX_TRIPS, HELD_KARP_MAX_TRIPS, effective_algorithm


def test_in_cap_requests_are_honoured_unchanged():
    """Back-compat: below its cap, the requested exact solver really is the one that runs."""
    assert effective_algorithm("brute", BRUTE_MAX_TRIPS) == "brute"
    assert effective_algorithm("held_karp", HELD_KARP_MAX_TRIPS) == "held_karp"
    assert effective_algorithm("lk", 99) == "lk"
    assert effective_algorithm("nearest", 99) == "nearest"


def test_brute_above_its_cap_resolves_to_the_solver_that_runs():
    """The measured case: 20 trips cannot be 20!-enumerated, so the label must not say 'brute'."""
    assert effective_algorithm("brute", BRUTE_MAX_TRIPS + 1) == "lk"
    assert effective_algorithm("brute", 20) == "lk"


def test_held_karp_above_its_cap_resolves_to_the_solver_that_runs():
    assert effective_algorithm("held_karp", HELD_KARP_MAX_TRIPS + 1) == "lk"
    assert effective_algorithm("held_karp", 20) == "lk"


def test_auto_dispatch_is_unchanged():
    """`auto` was already correct -- pin it so unifying the resolver did not move it."""
    assert effective_algorithm("auto", BRUTE_MAX_TRIPS) == "brute"
    assert effective_algorithm("auto", BRUTE_MAX_TRIPS + 1) == "held_karp_lk"
    assert effective_algorithm("auto", HELD_KARP_MAX_TRIPS) == "held_karp_lk"
    assert effective_algorithm("auto", HELD_KARP_MAX_TRIPS + 1) == "lk"


def test_the_degraded_label_is_no_longer_exact():
    """The consequence the operator sees: an above-cap brute run must not read as exact."""
    from lode.planner_optimize import _objective_optimality
    exact_lbl, exact_flag = _objective_optimality(effective_algorithm("brute", BRUTE_MAX_TRIPS), "time")
    assert exact_lbl == "exact" and exact_flag is True
    degraded_lbl, degraded_flag = _objective_optimality(effective_algorithm("brute", 20), "time")
    assert degraded_lbl != "exact" and degraded_flag is not True, (degraded_lbl, degraded_flag)


def test_held_karp_distance_claim_does_not_survive_the_fallback():
    """The worse instance: 'distance-exact' for a run that was NN + 2-opt."""
    from lode.planner_optimize import _objective_optimality
    lbl_in, _ = _objective_optimality(effective_algorithm("held_karp", HELD_KARP_MAX_TRIPS), "distance")
    assert "exact" in lbl_in
    lbl_out, flag_out = _objective_optimality(effective_algorithm("held_karp", 20), "distance")
    assert "exact" not in lbl_out and flag_out is not True, (lbl_out, flag_out)


@pytest.mark.parametrize("algo,n", [("brute", 20), ("held_karp", 20), ("brute", BRUTE_MAX_TRIPS + 1)])
def test_a_degraded_request_is_never_silent(algo, n):
    """The old warning was gated on >HELD_KARP_MAX_TRIPS, so a 'brute' request at 8..16 trips degraded
    in total silence. Any request that does not get its solver must be reported."""
    assert effective_algorithm(algo, n) != algo, "this case no longer degrades -- the guard is vacuous"
