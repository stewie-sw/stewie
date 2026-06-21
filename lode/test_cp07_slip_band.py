"""CP-07 (per-source uncertainty band propagation): the separable per-source uncertainty model
(``lode.plan_uncertainty``), surfaced as a planner VIEW. Unlike the core ``_plan_uncertainty`` block
(which honestly leaves slip ``quantified: False``), this VIEW QUANTIFIES the slip term from the real
Janosi-Hanamoto slip ladder over the sourced soil-traction [CALIB] envelope: the slip energy band is
ZERO on a flat haul (slip ~0) and NON-ZERO on a sloped haul, and the composite band is the honest
RSS combination of the independent contributions (no false precision). Grounded on a real Haworth plan.
"""
import math

import numpy as np

import lode.mission_planner as MP

_NAMED = {"slip", "dig_rate", "energy_estimate", "localization", "terrain", "drum_fill"}


def _flat_plan():
    """A plan over a perfectly FLAT synthetic tile (zero relief): every haul leg has zero grade, so the
    real slip model returns ~0 slip and the slip ENERGY band must collapse to ~zero. (Not synthetic
    DATA: a zero-relief surface is the analytic flat-ground control, the honest 'no slope' baseline.)"""
    Z = np.zeros((80, 80), dtype=float)
    dem = (Z, 5.0)
    m = MP.mission_from_dict({"name": "flat", "body": "moon", "charger": [0, 0], "orders": [
        {"action": "cut", "kind": "cut", "x": 60.0, "y": 60.0, "footprint_m2": 36.0, "depth_m": 0.10},
        {"action": "fill", "kind": "fill", "x": 320.0, "y": 320.0, "footprint_m2": 36.0, "depth_m": 0.10}]})
    res = MP.plan(m, dem=dem, dem_origin=(0.0, 0.0))
    return res, dem


def _haworth_sloped_plan():
    """A real-Haworth plan whose cut->fill haul crosses genuinely SLOPED LOLA terrain, so the real slip
    model develops non-zero slip and the slip energy band is non-trivial. Anchored to a DEM origin (M11)."""
    Z, cell = MP.load_haworth_dem()
    r0, c0 = 800, 1600
    crop = Z[r0:r0 + 80, c0:c0 + 80].copy()
    smap = MP.slope_deg_map(crop, cell)
    Wc = smap.shape[1]
    # flattest cell in the left third (a buildable cut) and in the right third (a buildable fill);
    # the haul between them crosses the sloped middle band -> non-zero slip on the real grade.
    sl = np.unravel_index(int(np.argmin(smap[:, :Wc // 3])), smap[:, :Wc // 3].shape)
    gl = np.unravel_index(int(np.argmin(smap[:, 2 * Wc // 3:])), smap[:, 2 * Wc // 3:].shape)
    a = (sl[1] * cell, sl[0] * cell)
    b = ((gl[1] + 2 * Wc // 3) * cell, gl[0] * cell)
    m = MP.mission_from_dict({"name": "haworth", "body": "moon", "charger": [a[0], a[1]], "orders": [
        {"action": "cut pad", "kind": "cut", "x": a[0], "y": a[1], "footprint_m2": 36.0, "depth_m": 0.10},
        {"action": "fill berm", "kind": "fill", "x": b[0], "y": b[1], "footprint_m2": 36.0, "depth_m": 0.10}]})
    res = MP.plan(m, dem=(crop, cell), dem_origin=(0.0, 0.0))
    return res, (crop, cell)


def test_view_enumerates_every_named_source_each_inspectable():  # [REQ:CP-07]
    res, dem = _haworth_sloped_plan()
    pu = MP.plan_uncertainty_view(res, dem=dem, dem_origin=(0.0, 0.0))
    assert set(pu["sources"]) == _NAMED                               # every named contribution present
    _energy_chan = {"slip", "dig_rate", "energy_estimate"}
    for name, src in pu["sources"].items():
        assert "into" in src and "quantified" in src                 # each source self-describes its channel
        if src["quantified"]:
            assert "source" in src                                   # a quantified source names its grounding
            if name in _energy_chan:                                 # energy-channel sources carry a (lo,hi) band
                assert src["into"] == "energy"
                assert "band" in src and len(src["band"]) == 2 and src["band"][0] <= src["band"][1]
            else:                                                    # feasibility/time channels carry their own figure
                assert src["into"] in ("feasibility", "time")
                assert any(k in src for k in ("band", "corridor_margin_m", "cell_sigma_m"))


def test_slip_term_is_zero_on_flat_terrain():  # [REQ:CP-07]
    res, dem = _flat_plan()
    pu = MP.plan_uncertainty_view(res, dem=dem, dem_origin=(0.0, 0.0))
    slip = pu["sources"]["slip"]
    assert slip["into"] == "energy"
    # flat ground -> the real slip model develops ~0 slip -> the half-width of the slip ENERGY band is
    # negligible relative to the nominal drive energy (no slope -> no slip -> no slip-driven band).
    lo, hi = slip["band"]
    half_width = 0.5 * (hi - lo)
    assert half_width / max(1.0, res.totals["energy_J"]) < 1e-3       # collapses to ~zero on flat


def test_slip_term_is_nonzero_on_sloped_haworth_terrain():  # [REQ:CP-07]
    res, dem = _haworth_sloped_plan()
    pu = MP.plan_uncertainty_view(res, dem=dem, dem_origin=(0.0, 0.0))
    slip = pu["sources"]["slip"]
    assert slip["quantified"] is True and slip["into"] == "energy"
    lo, hi = slip["band"]
    assert hi > lo                                                    # a real, non-degenerate band on slope
    # the band straddles the plan's nominal haul/drive energy (the slip term inflates drive by 1/(1-slip))
    nominal = float(slip["nominal_J"])
    assert lo <= nominal <= hi
    assert (hi - lo) > 0.0                                            # slope -> non-zero slip-driven spread


def test_composite_band_is_honest_rss_of_independent_sources():  # [REQ:CP-07]
    res, dem = _haworth_sloped_plan()
    pu = MP.plan_uncertainty_view(res, dem=dem, dem_origin=(0.0, 0.0))
    # the composite half-width is the root-sum-of-squares of the independent quantified source
    # half-widths (no false precision: independent errors add in quadrature, not linearly).
    halves = [0.5 * (s["band"][1] - s["band"][0])
              for s in pu["sources"].values() if s["quantified"] and s.get("into") == "energy"]
    rss = math.sqrt(sum(h * h for h in halves))
    comp = pu["composite"]["energy_J_band"]
    comp_half = 0.5 * (comp[1] - comp[0])
    assert abs(comp_half - rss) < 1.0                                # composite == RSS of the parts
    # honesty: RSS <= linear sum (quadrature never over-states), and >= the largest single source
    assert comp_half <= sum(halves) + 1e-6
    assert comp_half >= (max(halves) if halves else 0.0) - 1e-6


def test_view_does_not_mutate_the_plan_totals():  # [REQ:CP-07]
    res, dem = _haworth_sloped_plan()
    before = dict(res.totals)
    _ = MP.plan_uncertainty_view(res, dem=dem, dem_origin=(0.0, 0.0))
    # the VIEW is read-only: requesting the band leaves the existing plan outputs byte-identical
    assert res.totals == before
    assert "plan_uncertainty_view" not in res.totals                 # not injected into core totals
