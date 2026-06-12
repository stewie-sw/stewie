"""Annotated-measurement evidence: marked + measured + math, on real imagery."""
import glob
import math

import numpy as np
import pytest

from dart import annotate as AN

CE3 = sorted(glob.glob("/mnt/projects/datasets/lunar_ce3/yolo/images/**/*.png", recursive=True))


def test_parallax_range_annotation_math_matches():
    """The worked R = fx*dh/dv equals the instrument range, and the math lines carry the numbers."""
    from dart.articulated_parallax import range_from_pixel_parallax
    a = AN.parallax_range_annotation(tip_a_v=300.0, tip_b_v=347.6, dh_m=0.174, fx_px=2190.0)
    assert a["range_m"] == pytest.approx(range_from_pixel_parallax(0.174, a["shift_px"], 2190.0), rel=1e-9)
    assert a["shift_px"] == pytest.approx(47.6, abs=1e-6)
    assert any("R = fx * dh / dv" in m for m in a["math_lines"])


def test_shadow_length_height_annotation_math():
    """L_m = L_px*m_per_px and H = L_m*tan(e) appear with the substituted numbers."""
    g = np.full((80, 200), 210.0)
    g[40, 100:140] = 30.0                                   # a 40 px shadow east of the anchor
    a = AN.shadow_length_annotation(g, (100, 40), sun_az_deg=180.0, m_per_px=0.05, sun_el_deg=5.0)
    assert a["length_px"] > 30
    assert a["length_m"] == pytest.approx(a["length_px"] * 0.05, rel=1e-9)
    assert a["height_m"] == pytest.approx(a["length_m"] * math.tan(math.radians(5.0)), rel=1e-9)
    assert any("H = L * tan(e)" in m for m in a["math_lines"])


@pytest.mark.skipif(len(CE3) < 1, reason="CE-3 imagery not present")
def test_edge_fit_annotation_on_real_ce3():
    """On a real Chang'e-3 image, the erf fit returns a sub-pixel edge + a plausible width + the math."""
    from PIL import Image
    from dart.shadow_edge_sigma import measure_edge_sigma_px
    g = np.asarray(Image.open(CE3[0]).convert("L"), float)
    # find a strong edge to annotate (same selection the measurement uses)
    gx = np.abs(g[:, 1:] - g[:, :-1]); ys, xs = np.where(gx > 40)
    assert len(xs)
    k = np.argmax(gx[ys, xs]); v, u = int(ys[k]), int(xs[k])
    a = AN.edge_fit_annotation(g, (u, v))
    assert 0.2 < a["width_px"] < 6.0
    assert any("sigma_edge" in m for m in a["math_lines"])
