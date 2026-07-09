"""Tests for the site-plan validate-and-advise analyzer (Gap B core, 2026-06-23).

The analyzer reasons ACROSS a set of placed structures (not one at a time): it accounts the base-wide
mass economy, pairs sources<->sinks to minimise haul, checks inter-structure clearances, orders the
build so each cut precedes the fill it feeds, and emits advisories. The operator keeps placement
authority; the solver validates + advises.

All inputs are REAL structure templates from leap.structures (the domain objects), placed at chosen
site coordinates -- no synthetic data; the layout IS the operator's authored input.
"""
from __future__ import annotations

import pytest

from leap.siteplan import analyze_siteplan, PlacedStructure
from stewie.specs import constants as K


def _bank_mass(footprint_m2: float, depth_m: float) -> float:
    # task #78: a cut yields bank mass at its PER-CUT depth-averaged in-situ density (siteplan._order_mass),
    # not the flat deep RHO_DEEP ceiling. Matches siteplan's own per-cut model so a self-balanced structure
    # nets ~0 and a borrow pit's surplus is its real per-cut bank mass.
    from lode.planner_balance import insitu_bank_density
    return insitu_bank_density(depth_m, K.RHO_SPOIL) * footprint_m2 * depth_m


def test_single_balanced_structure_nets_to_zero():
    """A blast_berm self-balances (its borrow cut yields exactly the berm fill's mass) -> net ~ 0."""
    rpt = analyze_siteplan([PlacedStructure(name="blast_berm", x=0.0, y=0.0)])
    assert rpt.total_cut_mass_kg > 0.0
    # mass conserved by construction (structures.py swell): cut mass == fill mass
    assert rpt.net_mass_kg == pytest.approx(0.0, abs=1e-6 * rpt.total_cut_mass_kg)


def test_borrow_pit_adds_surplus():
    """A cut-only borrow_pit is a pure source; placed beside a self-balanced crater_fill the base nets
    a POSITIVE surplus equal to the borrow_pit's bank mass (crater_fill balances itself)."""
    pit_mass = _bank_mass(6.0 * 6.0, 0.3)  # borrow_pit defaults: side_m=6, depth_m=0.3
    rpt = analyze_siteplan([
        PlacedStructure(name="borrow_pit", x=-30.0, y=0.0),
        PlacedStructure(name="crater_fill", x=20.0, y=0.0),
    ])
    assert rpt.net_mass_kg == pytest.approx(pit_mass, rel=1e-9)
    assert rpt.net_mass_kg > 0.0


def test_routing_pairs_nearest_source_to_sink():
    """Global routing assigns each sink its nearest available source. With two cut sources (one near,
    one far) and one fill sink, the sink must draw from the NEAR source first."""
    # a fill that needs material, a near source, a far source -- placed by hand via raw orders
    rpt = analyze_siteplan([
        PlacedStructure(name="borrow_pit", x=2.0, y=0.0, params={"side_m": 10.0, "depth_m": 0.5}),   # near, big
        PlacedStructure(name="borrow_pit", x=100.0, y=0.0, params={"side_m": 10.0, "depth_m": 0.5}),  # far, big
        PlacedStructure(name="crater_fill", x=0.0, y=0.0, params={"radius_m": 4.0, "depth_m": 0.2}),
    ])
    assert rpt.pairings, "expected at least one source->sink pairing"
    # the crater_fill sink (the fill order) should be fed from the nearest source coordinate
    near_x = 2.0
    fed_xs = [p.source_x for p in rpt.pairings if p.mass_kg > 0]
    assert min(fed_xs, key=lambda xx: abs(xx - 0.0)) == pytest.approx(near_x, abs=2.0)
    assert rpt.total_haul_work_kg_m >= 0.0


def test_clearance_overlap_flagged():
    """Two structures stacked at the same coordinate overlap -> a clearance violation is flagged."""
    rpt = analyze_siteplan([
        PlacedStructure(name="landing_pad", x=0.0, y=0.0),
        PlacedStructure(name="solar_pad", x=0.0, y=0.0),
    ], min_gap_m=2.0)
    assert any(c.overlap for c in rpt.clearances), "stacked structures must flag an overlap"


def test_clearance_clear_when_far_apart():
    rpt = analyze_siteplan([
        PlacedStructure(name="landing_pad", x=0.0, y=0.0),
        PlacedStructure(name="solar_pad", x=200.0, y=0.0),
    ], min_gap_m=2.0)
    assert not any(c.overlap for c in rpt.clearances)


def test_build_order_cut_before_its_fill():
    """Each fill's paired source cut must precede it in the build order."""
    rpt = analyze_siteplan([PlacedStructure(name="habitat_foundation", x=0.0, y=0.0)])
    pos = {idx: i for i, idx in enumerate(rpt.build_order)}
    for p in rpt.pairings:
        if p.mass_kg > 0:
            assert pos[p.source_order_idx] < pos[p.sink_order_idx], \
                "the source cut must be built before the fill it feeds"


def test_unknown_structure_rejected():
    with pytest.raises(ValueError):
        analyze_siteplan([PlacedStructure(name="not_a_structure", x=0.0, y=0.0)])


def test_advisory_on_multiple_sources():
    """When the base has surplus sources, the report advises base-wide routing."""
    rpt = analyze_siteplan([
        PlacedStructure(name="borrow_pit", x=-30.0, y=0.0),
        PlacedStructure(name="borrow_pit", x=30.0, y=0.0),
        PlacedStructure(name="crater_fill", x=0.0, y=0.0),
    ])
    assert any("route" in a.lower() or "surplus" in a.lower() for a in rpt.advisories)
