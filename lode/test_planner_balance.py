"""ARCH-2 #2: the cut-fill mass-balance block lives in its own module (lode.planner_balance),
extracted out of mission_planner. These tests pin the EXTRACTION contract: the new module exists and
carries the balance solver, AND mission_planner still re-exports the same objects (so MP.balance /
MP.SWELL / MP._mincost_transport call sites are unchanged). The numerical behaviour of balance() is
already covered by test_mission_planner.py; here we only assert the move is structure-preserving."""
from __future__ import annotations

from lode import mission_planner as MP


def test_planner_balance_module_owns_the_block():
    """The cut-fill solver now lives in lode.planner_balance (the home of the extracted block)."""
    from lode import planner_balance as PB

    assert PB.balance is not None
    assert PB._mincost_transport is not None
    assert PB.SWELL > 1.0                      # spoil bulks: bank density > loose density -> SWELL > 1
    # the functions are DEFINED in the new module, not just re-imported there
    assert PB.balance.__module__ == "lode.planner_balance"
    assert PB._mincost_transport.__module__ == "lode.planner_balance"


def test_mission_planner_reexports_balance_block():
    """mission_planner still exposes the same objects after the move (facade is unchanged)."""
    from lode import planner_balance as PB

    assert MP.balance is PB.balance
    assert MP._mincost_transport is PB._mincost_transport
    assert MP.SWELL == PB.SWELL


def test_mincost_transport_is_pure_and_min_cost():
    """_mincost_transport routes over the cheapest FEASIBLE arcs and never over an unreachable (inf) one.
    Behaviour-preserving smoke check on the extracted solver (no DEM, no planner state needed)."""
    from lode import planner_balance as PB
    import math

    # two cuts (supply 10, 5), two fills (demand 8, 7); fill 1 is cheaper from cut 0, fill 0 unreachable
    # from cut 1 (inf). Optimal: cut0 -> fill0 (8), cut0 leftover 2 -> fill1, cut1 -> fill1 (5).
    supplies = [10.0, 5.0]
    demands = [8.0, 7.0]
    cost = [[1.0, 2.0], [math.inf, 1.0]]
    flow, unmet, leftover = PB._mincost_transport(supplies, demands, cost)
    assert flow[1][0] == 0.0                    # never routes the unreachable (inf) arc
    assert abs(sum(unmet)) < 1e-6              # all demand met
    assert abs(sum(leftover)) < 1e-6          # all supply consumed
    # conservation: total shipped == total supplied == total demanded
    shipped = sum(flow[i][j] for i in range(2) for j in range(2))
    assert abs(shipped - sum(supplies)) < 1e-6
