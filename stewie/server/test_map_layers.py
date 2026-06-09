"""Map layer registry: selectable layers, to-scale lander, excavation + zone overlays."""
from stewie.server import map_layers as ML


def test_layer_defs_are_selectable_set():
    defs = ML.layer_defs()
    ids = {d["id"] for d in defs}
    assert ids == {"imagery", "dem", "topology", "hazard", "excavation", "lander"}
    assert all("name" in d and "kind" in d and "default" in d for d in defs)
    # everything loads by default except topology (the opt-in slope raster)
    assert {d["id"] for d in defs if not d["default"]} == {"topology"}


def test_lander_marker_is_to_scale():
    coarse = ML.lander_marker(100, 50, meters_per_pixel=5.0)
    fine = ML.lander_marker(100, 50, meters_per_pixel=0.5)
    assert abs(fine["radius_px"] - 4.6) < 1e-9 and abs(coarse["radius_px"] - 0.46) < 1e-9   # scales with GSD
    assert fine["n_legs"] == 6 and fine["footprint_is_estimate"] is True
    assert abs(fine["keepout_radius_m"] - (0.5 * 4.6 + 2.0)) < 1e-9          # footprint/2 + margin


def test_excavation_and_zone_features():
    ops = [{"kind": "cut", "x": 10, "y": 20, "footprint_m2": math_pi_area(), "depth_m": 0.3}]
    f = ML.excavation_features(ops)
    assert len(f) == 1 and abs(f[0]["radius_m"] - 2.0) < 1e-9 and f[0]["kind"] == "cut"
    z = ML.zone_features([{"x": 5, "y": 5, "r": 8, "zone_type": "no_go", "label": "crevasse"}])
    assert z[0]["radius_m"] == 8 and z[0]["zone_type"] == "no_go"


def math_pi_area():
    import math
    return math.pi * 4.0          # radius 2 m -> area pi*r^2
