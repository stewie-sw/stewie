"""Lander geometry + to-scale map icon."""
from stewie import lander as L


def test_icon_scales_with_map_resolution():
    # to-scale: the icon radius in px tracks the map GSD (zoom in -> bigger icon)
    coarse = L.icon_radius_px(L.NOVA_C, 5.0)        # 5 m/px Haworth tile
    fine = L.icon_radius_px(L.NOVA_C, 0.5)          # 0.5 m/px worksite map
    assert abs(coarse - 0.46) < 1e-6 and abs(fine - 4.6) < 1e-6 and fine > coarse


def test_footprint_in_cells_and_keepout():
    assert abs(L.footprint_cells(L.NOVA_C, 5.0) - 0.92) < 1e-6     # ~1 cell on the 5 m DEM
    assert abs(L.footprint_cells(L.NOVA_C, 0.5) - 9.2) < 1e-6      # ~9 cells on a 0.5 m map
    assert abs(L.keepout_radius_m(L.NOVA_C, margin_m=2.0) - 4.3) < 1e-6


def test_place_on_map_descriptor():
    d = L.place_on_map(L.NOVA_C, 250.0, 300.0, meters_per_pixel=0.5)
    assert d["x"] == 250.0 and d["radius_px"] == 4.6 and d["n_legs"] == 6
    assert d["footprint_is_estimate"] is True and d["glyph"] == "hexagon-legs"
    assert L.GRIFFIN.footprint_diameter_m > L.NOVA_C.footprint_diameter_m   # cargo class is larger
