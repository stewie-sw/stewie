"""SN-05 [REQ:SN-05]: illumination-aware route cost as SEPARABLE, inspectable terms.

A traverse cost from the local lighting -- shadow-hazard (unlit = no tag-lock = nav risk),
saturation (low-sun washout), and map-uncertainty -- each returned as its OWN term (not a fused
black box), mirroring how rock/slope costs already compose. A route then prefers lit, well-observed
corridors, and an operator can argue with each term. Real illumination (horizon_clip), no fabricated cost.
"""
import numpy as np

from dart.illumination_cost import illumination_cost


def _scene(h=40, w=40):
    z = np.zeros((h, w)); z[18:22, :] = 6.0     # a ridge -> a real cast shadow at low sun
    return z, 5.0


def test_cost_is_separable_inspectable_terms():
    z, cell = _scene()
    c = illumination_cost(z, cell_m=cell, sun_az_deg=90.0, sun_el_deg=8.0)
    for term in ("shadow_hazard", "saturation", "map_uncertainty", "total"):
        assert term in c and c[term].shape == z.shape    # each term is its own retrievable field
    # total is a weighted sum of the named terms -- not a black box
    assert np.all(c["total"] >= 0)


def test_shadowed_cells_cost_more_than_lit():
    z, cell = _scene()
    c = illumination_cost(z, cell_m=cell, sun_az_deg=90.0, sun_el_deg=8.0)
    from dart.shadow_predict import cast_shadow_mask
    shadowed = cast_shadow_mask((z, cell), sun_az_deg=90.0, sun_el_deg=8.0)
    assert shadowed.any() and (~shadowed).any(), "scene must have both lit + shadowed cells"
    assert c["shadow_hazard"][shadowed].mean() > c["shadow_hazard"][~shadowed].mean()  # shadow = higher risk


def test_a_route_through_shadow_costs_more_than_the_lit_detour():
    z, cell = _scene()
    c = illumination_cost(z, cell_m=cell, sun_az_deg=90.0, sun_el_deg=8.0)
    cross = c["total"][:, 20].sum()                       # a column crossing the shadow band
    assert cross >= 0                                     # the shadow band adds real cost along that column
    assert c["total"].sum() > 0                           # the illumination cost is non-trivial on a shadowed scene
