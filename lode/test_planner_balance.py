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


def test_swell_factor_never_silently_diverges_from_planner_balance():
    """task #53 Finding 2 (honesty): constants.SWELL_FACTOR used to be a dead literal (1.2) that
    disagreed with the swell the planner ACTUALLY applies (RHO_DEEP/RHO_SPOIL, ~1.477). It is now
    derived from the same constants, so the two can never silently diverge again."""
    from lode import planner_balance as PB
    from stewie.specs import constants as C

    assert C.SWELL_FACTOR == PB.SWELL == C.RHO_DEEP / C.RHO_SPOIL


def test_insitu_bank_density_shallow_surface_is_below_deep():
    """[task #78 Part C] A shallow cut excavates loose near-surface material (~RHO_SURFACE); a deep cut
    approaches the compacted RHO_DEEP ceiling. The depth-averaged in-situ bank density is monotone in depth
    and bounded by [RHO_SURFACE, RHO_DEEP]. This is what stops a shallow cut being costed at RHO_DEEP."""
    import math

    from lode import planner_balance as PB
    from stewie.specs import constants as C

    shallow = PB.insitu_bank_density(0.03, C.RHO_SURFACE)      # < Z_T -> entirely loose surface mantle
    mid = PB.insitu_bank_density(0.30, C.RHO_SURFACE)          # crosses Z_T -> denser
    deep = PB.insitu_bank_density(5.0, C.RHO_SURFACE)          # >> Z_T -> near the compacted ceiling
    assert math.isclose(shallow, C.RHO_SURFACE)
    assert shallow < mid < deep
    assert C.RHO_SURFACE <= deep <= C.RHO_DEEP + 1e-9


def test_balance_costs_a_rho_surface_cut_below_a_rho_deep_cut():
    """[task #78 Part C, the TDD] A cut of RHO_SURFACE material yields a SMALLER bank mass (hence volume /
    dig energy) than an otherwise-identical cut of RHO_DEEP material -- balance() costs each cut at its
    ACTUAL in-situ density, no longer treating every cut as the deep RHO_DEEP density."""
    import math

    from lode import mission_planner as MP
    from lode import planner_balance as PB
    from stewie.specs import constants as C

    def cut_only_bank_mass(density):
        m = MP.mission_from_dict({"name": "t", "body": "moon", "charger": [0, 0], "orders": [
            {"action": "dig", "kind": "cut", "x": 0.0, "y": 0.0, "footprint_m2": 40.0, "depth_m": 0.10,
             "insitu_density_kg_m3": density}]})
        _flows, surplus_kg = PB.balance(m)                    # cut-only -> all cut (bank) mass is surplus spoil
        return surplus_kg

    m_surface = cut_only_bank_mass(C.RHO_SURFACE)
    m_deep = cut_only_bank_mass(C.RHO_DEEP)
    assert m_surface < m_deep                                 # loose-material cut costs less bank mass
    # equal footprint + depth -> the bank-mass ratio is exactly the density ratio (mass = vol * density)
    assert math.isclose(m_deep / m_surface, C.RHO_DEEP / C.RHO_SURFACE, rel_tol=1e-9)


def test_balance_fallback_uses_the_depth_profile_not_flat_rho_deep():
    """[task #78 Part C] Absent an explicit per-cell density, balance() falls back to the depth-averaged
    in-situ profile (NOT a flat RHO_DEEP): a shallow cut of equal VOLUME costs less bank mass than a deep
    cut, so a near-surface dig is not over-costed as deeply-buried compacted regolith."""
    from lode import mission_planner as MP
    from lode import planner_balance as PB

    def bank_mass(depth_m, footprint_m2):                     # equal volume across the two calls below
        m = MP.mission_from_dict({"name": "t", "body": "moon", "charger": [0, 0], "orders": [
            {"action": "dig", "kind": "cut", "x": 0.0, "y": 0.0,
             "footprint_m2": footprint_m2, "depth_m": depth_m}]})   # no insitu_density -> profile fallback
        return PB.balance(m)[1]

    shallow = bank_mass(0.05, 40.0)                           # 2.0 m^3 of loose surface material
    deep = bank_mass(2.0, 1.0)                                # 2.0 m^3 reaching the compacted layer
    assert shallow < deep


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
